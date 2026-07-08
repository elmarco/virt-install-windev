from __future__ import annotations

import grp
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from virt_install_windev.config import Config
from virt_install_windev.util import run, CommandError

VIRTIO_ISO = Path("/usr/share/virtio-win/virtio-win.iso")
OVMF_CODE = Path("/usr/share/OVMF/OVMF_CODE.secboot.fd")
OVMF_VARS = Path("/usr/share/OVMF/OVMF_VARS.fd")

REQUIRED_COMMANDS = ("virt-install", "virsh", "qemu-img", "genisoimage", "curl", "swtpm")


@dataclass(frozen=True)
class MissingDep:
    what: str
    hint: str
    warning: bool = False


def check_dependencies(config: Config) -> list[MissingDep]:
    missing: list[MissingDep] = []

    cmds = [c for c in REQUIRED_COMMANDS if shutil.which(c) is None]
    if cmds:
        missing.append(MissingDep(
            f"missing commands: {', '.join(cmds)}",
            "sudo dnf install " + " ".join(
                _package_for(c) for c in cmds
            ),
        ))

    if not VIRTIO_ISO.exists():
        missing.append(MissingDep(
            f"virtio-win ISO not found at {VIRTIO_ISO}",
            "sudo dnf install virtio-win",
        ))

    if not OVMF_CODE.exists():
        missing.append(MissingDep(
            f"OVMF firmware not found at {OVMF_CODE}",
            "sudo dnf install edk2-ovmf",
        ))

    if config.insider:
        try:
            import selenium  # noqa: F401
        except ImportError:
            missing.append(MissingDep(
                "selenium is required for --insider ISO download",
                "pip install virt-install-windev[insider]",
            ))

    return missing


def preflight_checks(config: Config) -> list[MissingDep]:
    issues: list[MissingDep] = []

    if not Path("/dev/kvm").exists():
        issues.append(MissingDep(
            "KVM not available (/dev/kvm not found)",
            "Enable VT-x/AMD-V in BIOS, or: sudo modprobe kvm_intel (or kvm_amd)",
        ))

    try:
        run(["virsh", "uri"], capture=True)
    except (CommandError, FileNotFoundError):
        issues.append(MissingDep(
            "Cannot connect to libvirt",
            "Is libvirtd running? Try: sudo systemctl start libvirtd",
        ))

    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    needed_bytes = (config.disk_gb + 7) * 1024 ** 3
    free = shutil.disk_usage(cache_dir).free
    if free < needed_bytes:
        free_gb = free / 1024 ** 3
        need_gb = config.disk_gb + 7
        issues.append(MissingDep(
            f"Not enough disk space: {free_gb:.1f} GiB free, need ~{need_gb} GiB",
            f"Free up space in {cache_dir}",
        ))

    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                    avail_mb = avail_kb // 1024
                    if avail_mb < config.ram_mb:
                        issues.append(MissingDep(
                            f"Not enough RAM: {avail_mb} MiB available, need {config.ram_mb} MiB",
                            "Close other applications or reduce --ram",
                        ))
                    break
    except OSError:
        pass

    if os.getuid() != 0:
        try:
            libvirt_gid = grp.getgrnam("libvirt").gr_gid
            if libvirt_gid not in os.getgroups():
                issues.append(MissingDep(
                    "Current user is not in the 'libvirt' group",
                    "sudo usermod -aG libvirt $USER && newgrp libvirt",
                    warning=True,
                ))
        except KeyError:
            pass

    return issues


_CMD_TO_PKG: dict[str, str] = {
    "virt-install": "virt-install",
    "virsh": "libvirt-client",
    "qemu-img": "qemu-img",
    "genisoimage": "genisoimage",
    "curl": "curl",
    "swtpm": "swtpm-tools",
}


def _package_for(cmd: str) -> str:
    return _CMD_TO_PKG.get(cmd, cmd)
