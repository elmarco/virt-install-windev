from __future__ import annotations

import enum
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
class VMSettings:
    locale: str = "en-US"
    timezone: str = "UTC"
    defender: bool = False
    uac: bool = False
    vbs: bool = False
    telemetry: int = 0
    recall: bool = False
    copilot: bool = False
    widgets: bool = False
    consumer_features: bool = False
    bing_search: bool = False
    update_notify: bool = True
    no_auto_reboot: bool = True
    dark_mode: bool = True
    animations: bool = False
    lock_screen: bool = False
    file_extensions: bool = True
    hidden_files: bool = True
    launch_to: str = "this_pc"
    hibernation: bool = False
    monitor_timeout: int = 0
    sleep_timeout: int = 0
    developer_mode: bool = True
    long_paths: bool = True
    wsl: bool = True
    remove_bloatware: bool = True
    bloatware_keep: list[str] = field(default_factory=lambda: [
        "Calculator", "Photos", "Terminal", "Store",
        "DesktopAppInstaller", "WindowsNotepad",
    ])
    windows_terminal: bool = True
    winget_packages: list[str] = field(default_factory=lambda: [
        "Microsoft.WinDbg",
        "Microsoft.Sysinternals.Suite",
        "WinFsp.WinFsp",
    ])
    openssh: bool = True
    rdp: bool = True
    rdp_usb_redirection: bool = True


_TOML_SETTINGS_MAP: list[tuple[str, str, str]] = [
    ("locale", "language", "locale"),
    ("locale", "timezone", "timezone"),
    ("security", "defender", "defender"),
    ("security", "uac", "uac"),
    ("security", "vbs", "vbs"),
    ("privacy", "telemetry", "telemetry"),
    ("privacy", "recall", "recall"),
    ("privacy", "copilot", "copilot"),
    ("privacy", "widgets", "widgets"),
    ("privacy", "consumer_features", "consumer_features"),
    ("privacy", "bing_search", "bing_search"),
    ("updates", "notify_only", "update_notify"),
    ("updates", "no_auto_reboot", "no_auto_reboot"),
    ("desktop", "dark_mode", "dark_mode"),
    ("desktop", "animations", "animations"),
    ("desktop", "lock_screen", "lock_screen"),
    ("explorer", "file_extensions", "file_extensions"),
    ("explorer", "hidden_files", "hidden_files"),
    ("explorer", "launch_to", "launch_to"),
    ("power", "hibernation", "hibernation"),
    ("power", "monitor_timeout", "monitor_timeout"),
    ("power", "sleep_timeout", "sleep_timeout"),
    ("developer", "mode", "developer_mode"),
    ("developer", "long_paths", "long_paths"),
    ("apps", "wsl", "wsl"),
    ("apps", "remove_bloatware", "remove_bloatware"),
    ("apps", "bloatware_keep", "bloatware_keep"),
    ("apps", "windows_terminal", "windows_terminal"),
    ("packages", "winget", "winget_packages"),
    ("services", "openssh", "openssh"),
    ("services", "rdp", "rdp"),
    ("services", "rdp_usb_redirection", "rdp_usb_redirection"),
]

_TOML_VM_MAP: dict[str, str] = {
    "name": "name",
    "vcpus": "vcpus",
    "ram": "ram_mb",
    "disk": "disk_gb",
    "user": "user_name",
    "password": "user_password",
    "network": "network",
}


def settings_from_toml(data: dict[str, Any]) -> VMSettings:
    kwargs: dict[str, Any] = {}
    for section, key, field_name in _TOML_SETTINGS_MAP:
        if section in data and key in data[section]:
            kwargs[field_name] = data[section][key]
    return VMSettings(**kwargs)


def vm_overrides_from_toml(data: dict[str, Any]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    vm = data.get("vm", {})
    for toml_key, config_field in _TOML_VM_MAP.items():
        if toml_key in vm:
            overrides[config_field] = vm[toml_key]
    return overrides


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
    settings: VMSettings = field(default_factory=VMSettings)
    post_install_scripts: list[Path] = field(default_factory=list)


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
