from __future__ import annotations

import subprocess
import time
from pathlib import Path

from virt_install_windev.config import Config, VERSION_PARAMS
from virt_install_windev.deps import VIRTIO_ISO, OVMF_CODE
from virt_install_windev.util import log, run, CommandError


def remove_existing_vm(config: Config) -> None:
    name = config.name
    try:
        run(["virsh", "dominfo", name], capture=True)
    except CommandError:
        return

    if not config.force:
        raise RuntimeError(
            f"VM '{name}' already exists.\n"
            f"Remove it with: virsh destroy {name}; "
            f"virsh undefine {name} --nvram --tpm\n"
            f"Or re-run with --force to replace it."
        )

    log(f"Removing existing VM '{name}'...")
    run(["virsh", "destroy", name], check=False, capture=True)
    run(["virsh", "undefine", name, "--nvram", "--tpm"], check=False, capture=True)
    disk = Path(config.cache_dir) / f"{name}.qcow2"
    disk.unlink(missing_ok=True)


def create_disk(config: Config) -> Path:
    cache = Path(config.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    disk = cache / f"{config.name}.qcow2"

    if disk.exists():
        if config.force:
            disk.unlink()
        else:
            raise RuntimeError(
                f"Disk image already exists: {disk}\n"
                "Remove it first if you want a fresh install."
            )

    run(["qemu-img", "create", "-f", "qcow2", str(disk), f"{config.disk_gb}G"])
    log(f"Created disk image: {disk} ({config.disk_gb} GiB)")
    return disk


def create_and_start_vm(
    config: Config,
    disk_path: Path,
    win_iso: Path,
    unattend_iso: Path,
    install_log: Path,
) -> None:
    params = VERSION_PARAMS[config.win_version]
    install_log.write_text("")

    log("")
    log(f"Creating VM '{config.name}'...")
    log(f"  Windows: {config.win_version.value}")
    log(f"  vCPUs:   {config.vcpus}")
    log(f"  RAM:     {config.ram_mb} MiB")
    log(f"  Disk:    {config.disk_gb} GiB")
    log(f"  User:    {config.user_name}")
    log("")

    cmd = [
        "virt-install",
        "--name", config.name,
        "--memory", str(config.ram_mb),
        "--vcpus", str(config.vcpus),
        "--os-variant", params.os_variant,
        "--boot", "uefi,cdrom,hd",
        "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-crb",
        "--disk", f"path={disk_path},format=qcow2,bus=virtio,cache=writeback",
        "--cdrom", str(win_iso),
        "--disk", f"{VIRTIO_ISO},device=cdrom,bus=sata",
        "--disk", f"{unattend_iso},device=cdrom,bus=sata",
        "--network", "bridge=virbr0,model=virtio",
        "--graphics", "spice,listen=none",
        "--video", "qxl",
        "--channel", "spicevmc",
        "--channel", "unix,target.type=virtio,target.name=org.qemu.guest_agent.0",
        "--sound", "default",
        "--serial", f"file,path={install_log}",
        "--controller", "type=scsi,model=virtio-scsi",
        "--vsock", "cid.auto=yes",
        "--features", "vmcoreinfo=on",
        "--noautoconsole",
    ]
    run(cmd)


def send_boot_keys(config: Config, install_log: Path) -> None:
    for _ in range(30):
        try:
            if "starting Boot" in install_log.read_text():
                break
        except OSError:
            pass
        time.sleep(1)
    time.sleep(2)

    for _ in range(15):
        try:
            run(["virsh", "send-key", config.name, "KEY_ENTER"], capture=True)
        except CommandError:
            break
        time.sleep(1)


def wait_for_install(config: Config, install_log: Path) -> None:
    log("Waiting for installation to complete (this may take 30-60 minutes)...")
    log(f"Connect with: virt-viewer --attach {config.name}")
    log(f"Install log:  {install_log}")
    log("")

    tail = subprocess.Popen(
        ["tail", "-F", str(install_log)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    sed = subprocess.Popen(
        ["sed", "-u", "s/^/  [vm] /"],
        stdin=tail.stdout,
        stderr=subprocess.DEVNULL,
    )
    if tail.stdout:
        tail.stdout.close()

    max_boots = 5
    boot_count = 1
    full_log = install_log.with_suffix(".log.full")

    try:
        while True:
            try:
                result = run(
                    ["virsh", "domstate", config.name],
                    capture=True,
                )
                state = result.stdout.strip()
            except CommandError:
                break

            if state == "shut off":
                try:
                    content = install_log.read_text()
                except OSError:
                    content = ""
                if "INSTALLATION_COMPLETE" in content:
                    break

                boot_count += 1
                if boot_count > max_boots:
                    log("")
                    log(f"Warning: VM shut down {max_boots} times without completing.")
                    log(f"Check the log: {install_log}")
                    log(f"Start manually: virsh start {config.name}")
                    break

                log("")
                log(f"  VM shut down mid-install (boot {boot_count}/{max_boots}), restarting...")

                try:
                    with open(full_log, "a") as f:
                        f.write(install_log.read_text())
                except OSError:
                    pass

                try:
                    run(["virsh", "start", config.name], capture=True)
                except CommandError as exc:
                    log(f"Warning: failed to restart VM: {exc}")
                    log(f"Start manually: virsh start {config.name}")
                    break
                time.sleep(10)

            time.sleep(15)
    finally:
        tail.terminate()
        tail.wait()
        sed.wait()

        try:
            with open(full_log, "a") as f:
                f.write(install_log.read_text())
        except OSError:
            pass


def detach_cdroms(config: Config) -> None:
    try:
        result = run(
            ["virsh", "domblklist", config.name, "--details"],
            capture=True,
            check=False,
        )
    except Exception:
        return

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "cdrom":
            run(
                ["virsh", "detach-disk", config.name, parts[2], "--config"],
                check=False,
                capture=True,
            )


def print_success(config: Config) -> None:
    log("")
    log("================================================================")
    log(f"  VM '{config.name}' created successfully!")
    log("================================================================")
    log("")
    log("Connect with:")
    log(f"  virt-viewer {config.name}")
    log(f"  (or: virsh domdisplay {config.name})")
    log("")
    log("Get VM IP (requires guest agent):")
    log(f"  virsh domifaddr {config.name} --source agent")
    log("")
    log("SSH:")
    log(f"  ssh {config.user_name}@<IP>")
    log("")
    log("RDP:")
    log(f"  xfreerdp /v:<IP> /u:{config.user_name} /p:{config.user_password} /dynamic-resolution")
    if config.win_version.value.startswith("server"):
        log("")
        log("RDP with USB redirection:")
        log(f"  xfreerdp /v:<IP> /u:{config.user_name} /p:{config.user_password} /dynamic-resolution /usb:auto")
    log("")
    log("VM management:")
    log(f"  virsh start {config.name}")
    log(f"  virsh shutdown {config.name}")
    log(f"  virsh destroy {config.name}        # force stop")
    log(f"  virsh undefine {config.name} --nvram --tpm  # remove completely")
