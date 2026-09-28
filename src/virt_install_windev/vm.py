from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path

from virt_install_windev.config import Config, WinVersion, VERSION_PARAMS
from virt_install_windev.ui import StepTracker, log, print_vm_info, _DISK_PROGRESS
from virt_install_windev.util import run, CommandError


def _read_log(path: Path) -> str:
    return path.read_text(errors="replace")


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
    destroy_vm(config)
    undefine_vm(config)
    disk = Path(config.cache_dir) / f"{name}.qcow2"
    disk.unlink(missing_ok=True)


def destroy_vm(config: Config) -> None:
    run(["virsh", "destroy", config.name], check=False, capture=True)


def undefine_vm(config: Config) -> None:
    run(["virsh", "undefine", config.name, "--nvram", "--tpm"],
        check=False, capture=True)


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

    print_vm_info(config)

    cmd = [
        "virt-install",
        "--name", config.name,
        "--memory", str(config.ram_mb),
        "--vcpus", str(config.vcpus),
        "--os-variant", params.os_variant,
        "--boot", ("uefi,cdrom,hd,"
                   "firmware.feature0.name=secure-boot,"
                   "firmware.feature0.enabled=no"
                   if config.kd else "uefi,cdrom,hd"),
        "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-crb",
        "--disk", f"path={disk_path},format=qcow2,bus=virtio,cache=writeback",
        "--cdrom", str(win_iso),
        "--disk", f"{config.virtio_iso},device=cdrom,bus=sata",
        "--disk", f"{unattend_iso},device=cdrom,bus=sata",
        "--network", f"{config.network},model=virtio",
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
    if config.iommu:
        cmd += ["--iommu", f"model={config.iommu}"]
    run(cmd)


def send_boot_keys(config: Config, install_log: Path) -> None:
    for _ in range(30):
        try:
            if "starting Boot" in _read_log(install_log):
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


def _tail_raw(install_log: Path) -> tuple[subprocess.Popen, subprocess.Popen]:
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
    return tail, sed


def _get_disk_target(vm_name: str) -> str | None:
    try:
        result = run(
            ["virsh", "domblklist", vm_name, "--details"], capture=True)
    except CommandError:
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "disk":
            return parts[2]
    return None


def _get_disk_writes(vm_name: str, target: str) -> int | None:
    try:
        result = run(["virsh", "domblkstat", vm_name, target], capture=True)
    except CommandError:
        return None
    for line in result.stdout.splitlines():
        parts = line.split()
        try:
            idx = parts.index("wr_bytes")
            return int(parts[idx + 1])
        except (ValueError, IndexError):
            continue
    return None


def _build_steps(config: Config) -> list[tuple[str, str]]:
    steps: list[tuple[str, str]] = [
        ("starting Boot", "Booting from installer"),
        (_DISK_PROGRESS, "Installing Windows"),
        ("[SPECIALIZE] Configuring system settings", "Configuring system settings"),
        ("[SPECIALIZE] Disabling Defender services", "Disabling Defender"),
        ("[SPECIALIZE] Running setup.ps1", "Running setup script"),
        ("[SETUP] Starting PowerShell configuration", "Applying PowerShell configuration"),
    ]
    if config.win_version in (WinVersion.WIN10, WinVersion.WIN11):
        steps.append(("[SETUP] Enabling WSL", "Enabling WSL"))
    else:
        steps.append(("[SETUP] Suppressing Server Manager", "Configuring Server Manager"))
    if config.win_version in (WinVersion.WIN10, WinVersion.SERVER2016):
        steps.append(("[SETUP] Installing Win32-OpenSSH", "Installing OpenSSH (bundled)"))
    steps.append(("[SPECIALIZE] Done, rebooting into OOBE", "Rebooting into OOBE"))
    steps.append(("[OOBE] First login", "Installing VirtIO guest tools"))
    if config.win_version in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        steps.append(("[OOBE] Installing RDSH", "Installing Remote Desktop Session Host"))
    steps.append(("[OOBE] Installing OpenSSH", "Installing OpenSSH Server"))
    steps.append(("[OOBE] Removing bloatware", "Removing bloatware"))
    steps.append(("[OOBE] Installing WinDbg", "Installing WinDbg & Sysinternals"))
    steps.append(("INSTALLATION_COMPLETE", "Installation complete"))
    return steps


def wait_for_install(config: Config, install_log: Path,
                     win_iso: Path | None = None) -> None:
    log("Waiting for installation to complete (this may take 30-60 minutes)...")
    log(f"Connect with: [cyan]virt-viewer --attach {config.name}[/cyan]")
    log(f"Install log:  {install_log}")
    log()

    tail = sed = None
    if config.debug:
        tail, sed = _tail_raw(install_log)

    use_tracker = not config.debug
    steps = _build_steps(config) if use_tracker else []
    done: set[str] = set()
    warnings: list[str] = []
    disk_written: int | None = None
    disk_target: str | None = None
    disk_total: int | None = None
    if win_iso:
        try:
            disk_total = int(win_iso.stat().st_size * 3.5)
        except OSError:
            pass

    tracker: StepTracker | None = None
    if use_tracker:
        tracker = StepTracker(steps, disk_total)
        tracker.start()

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

            if use_tracker:
                try:
                    content = _read_log(install_log)
                except OSError:
                    content = ""
                for marker, _ in steps:
                    if marker == _DISK_PROGRESS:
                        continue
                    if marker not in done and marker in content:
                        done.add(marker)
                        if marker.startswith("[SPECIALIZE]") and _DISK_PROGRESS not in done:
                            done.add(_DISK_PROGRESS)

                disk_active = (
                    _DISK_PROGRESS not in done
                    and "starting Boot" in done
                )
                if disk_active:
                    if disk_target is None:
                        disk_target = _get_disk_target(config.name)
                    if disk_target:
                        disk_written = _get_disk_writes(config.name, disk_target)

                tracker.update(done, disk_written, warnings)

            if state == "shut off":
                try:
                    content = _read_log(install_log)
                except OSError:
                    content = ""
                if "INSTALLATION_COMPLETE" in content:
                    if use_tracker:
                        for marker, _ in steps:
                            if marker == _DISK_PROGRESS:
                                continue
                            if marker in content:
                                done.add(marker)
                        done.add(_DISK_PROGRESS)
                        tracker.update(done, disk_written, warnings)
                    break

                boot_count += 1
                if boot_count > max_boots:
                    warnings.append(
                        f"VM shut down {max_boots} times without completing.")
                    warnings.append(f"Check the log: {install_log}")
                    warnings.append(f"Start manually: virsh start {config.name}")
                    if tracker:
                        tracker.update(done, disk_written, warnings)
                    else:
                        for w in warnings:
                            log(f"[yellow]Warning:[/yellow] {w}")
                    break

                msg = f"VM shut down mid-install (boot {boot_count}/{max_boots}), restarting..."
                warnings.append(msg)
                if tracker:
                    tracker.update(done, disk_written, warnings)
                else:
                    log(msg)

                try:
                    with open(full_log, "a") as f:
                        f.write(_read_log(install_log))
                except OSError:
                    pass

                try:
                    run(["virsh", "start", config.name], capture=True)
                except CommandError as exc:
                    warnings.append(f"Failed to restart VM: {exc}")
                    warnings.append(f"Start manually: virsh start {config.name}")
                    if tracker:
                        tracker.update(done, disk_written, warnings)
                    else:
                        log(f"[yellow]Warning:[/yellow] failed to restart VM: {exc}")
                        log(f"Start manually: virsh start {config.name}")
                    break

                time.sleep(10)

            time.sleep(15)
    finally:
        if tracker:
            tracker.finish()
        if tail:
            tail.terminate()
            tail.wait()
        if sed:
            sed.wait()

        try:
            with open(full_log, "a") as f:
                f.write(_read_log(install_log))
        except OSError:
            pass


def create_snapshot(config: Config) -> bool:
    log("Creating snapshot 'fresh-install'...")
    try:
        run(["virsh", "snapshot-create-as", config.name,
             "fresh-install", "Clean install, ready to use"],
            capture=True, timeout=120)
        log(f"Created snapshot 'fresh-install' for VM '{config.name}'")
        return True
    except CommandError:
        log("Warning: failed to create snapshot")
        return False
    except subprocess.TimeoutExpired:
        log("Warning: snapshot creation timed out, skipping")
        return False


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


def detach_serial_console(config: Config) -> None:
    """Remove the COM1-to-file serial device used only for install progress logging."""
    run(
        ["virt-xml", config.name, "--remove-device", "--serial", "1"],
        check=False,
        capture=True,
    )


def _guest_exec(name: str, path: str, args: list[str]) -> None:
    cmd_json = json.dumps({
        "execute": "guest-exec",
        "arguments": {"path": path, "arg": args, "capture-output": True},
    })
    run(["virsh", "qemu-agent-command", name, cmd_json], capture=True)


def _wait_for_guest_agent(name: str, timeout: int = 300) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            run(["virsh", "qemu-agent-command", name,
                 '{"execute":"guest-ping"}'], capture=True)
            return True
        except CommandError:
            time.sleep(5)
    return False


def configure_kd(config: Config) -> None:
    name = config.name
    kd_sock = Path(config.cache_dir) / f"{name}-kd.sock"

    run(
        ["virt-xml", name, "--add-device",
         "--serial", f"unix,path={kd_sock}"],
        check=False,
        capture=True,
    )

    log("Configuring kernel debugging...")
    run(["virsh", "start", name], capture=True)

    if not _wait_for_guest_agent(name):
        log("[yellow]Warning:[/yellow] guest agent not responding, skipping KD setup")
        run(["virsh", "destroy", name], check=False, capture=True)
        return

    _guest_exec(name, "bcdedit", ["/debug", "on"])
    _guest_exec(name, "bcdedit",
                ["/dbgsettings", "serial", "debugport:2", "baudrate:115200"])

    run(["virsh", "shutdown", name], capture=True)
    for _ in range(60):
        try:
            result = run(["virsh", "domstate", name], capture=True)
            if result.stdout.strip() == "shut off":
                break
        except CommandError:
            break
        time.sleep(5)

    log(f"Kernel debugging serial: {kd_sock}")


def reset_boot_order(config: Config) -> None:
    """Drop 'cdrom' from the boot order now that the install media is detached."""
    run(
        ["virt-xml", config.name, "--boot", "hd"],
        check=False,
        capture=True,
    )


def cleanup_install_logs(install_log: Path) -> None:
    install_log.unlink(missing_ok=True)
    install_log.with_suffix(".log.full").unlink(missing_ok=True)

