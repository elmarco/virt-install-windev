from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from virt_install_windev.config import Config

VIRTIO_ISO = Path("/usr/share/virtio-win/virtio-win.iso")
OVMF_CODE = Path("/usr/share/OVMF/OVMF_CODE.secboot.fd")
OVMF_VARS = Path("/usr/share/OVMF/OVMF_VARS.fd")

REQUIRED_COMMANDS = ("virt-install", "virsh", "qemu-img", "genisoimage", "curl", "swtpm")


@dataclass(frozen=True)
class MissingDep:
    what: str
    hint: str


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
