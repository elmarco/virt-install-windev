from __future__ import annotations

import enum
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


class WinVersion(enum.Enum):
    WIN10 = "10"
    WIN11 = "11"
    SERVER2016 = "server2016"
    SERVER2022 = "server2022"


@dataclass(frozen=True)
class VersionParams:
    virtio_driver_dir: str
    os_variant: str
    image_index: int


VERSION_PARAMS: dict[WinVersion, VersionParams] = {
    WinVersion.WIN10:        VersionParams("w10",  "win10",   1),
    WinVersion.SERVER2016:   VersionParams("2k16", "win2k16", 2),
    WinVersion.SERVER2022:   VersionParams("2k22", "win2k22", 2),
    WinVersion.WIN11:        VersionParams("w11",  "win11",   1),
}


@dataclass
class Config:
    name: str = "windev"
    vcpus: int = 4
    ram_mb: int = 8192
    disk_gb: int = 64
    user_name: str = "user"
    user_password: str = "pass"
    computer_name: str = "WinDev"
    win_version: WinVersion = WinVersion.WIN11
    iso_path: str | None = None
    insider: bool = False
    insider_edition: str = "Release Preview"
    insider_lang: str = "English (United States)"
    insider_timeout: int = 300
    no_wait: bool = False
    force: bool = False
    network: str = "bridge=virbr0"
    debug: bool = False
    iommu: str | None = None
    kd: bool = False
    virtio_iso: Path = Path("/usr/share/virtio-win/virtio-win.iso")
    ovmf_code: Path = Path("/usr/share/OVMF/OVMF_CODE.secboot.fd")
    cache_dir: str = field(
        default_factory=lambda: os.path.join(
            os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
            "virt-install-windev"))


# Detection patterns mirror virt-install-windev.sh:250-253 (Server first, then 10, then 11).
_RE_SERVER_2016 = re.compile(r"[Ss]erver.*2016")
_RE_SERVER_2022 = re.compile(r"([Ss]erver.*2022|SERVER_EVAL)")
_RE_WIN10 = re.compile(r"[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*10")
_RE_WIN11 = re.compile(r"[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*11")


def sanitize_computer_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9-]", "-", name).upper()
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    sanitized = sanitized[:15]
    sanitized = sanitized.rstrip("-")
    return sanitized or "WINDEV"


def detect_win_version(iso_filename: str) -> WinVersion | None:
    if _RE_SERVER_2016.search(iso_filename):
        return WinVersion.SERVER2016
    if _RE_SERVER_2022.search(iso_filename):
        return WinVersion.SERVER2022
    if _RE_WIN10.search(iso_filename):
        return WinVersion.WIN10
    if _RE_WIN11.search(iso_filename):
        return WinVersion.WIN11
    return None
