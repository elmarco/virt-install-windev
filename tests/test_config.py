from __future__ import annotations

import pytest

from virt_install_windev.config import (
    Config, SharedFolder, VMSettings, WinVersion, VERSION_PARAMS,
    detect_win_version, sanitize_computer_name, settings_from_toml,
    vm_overrides_from_toml,
)


def test_detect_win11():
    assert detect_win_version("Win11_24H2_English_x64.iso") is WinVersion.WIN11


def test_detect_win10():
    assert detect_win_version("Win10_22H2_English_x64.iso") is WinVersion.WIN10


def test_detect_server2016():
    assert detect_win_version("en_windows_server_2016_x64_dvd.iso") is WinVersion.SERVER2016


def test_detect_server2022_eval():
    assert detect_win_version("SERVER_EVAL_x64FRE_en-us.iso") is WinVersion.SERVER2022


def test_detect_server2022_named():
    assert detect_win_version("Windows_Server_2022_x64.iso") is WinVersion.SERVER2022


def test_detect_unknown_returns_none():
    assert detect_win_version("foo.iso") is None


def test_version_params():
    assert VERSION_PARAMS[WinVersion.WIN10].virtio_driver_dir == "w10"
    assert VERSION_PARAMS[WinVersion.WIN10].os_variant == "win10"
    assert VERSION_PARAMS[WinVersion.WIN10].image_index == 1
    assert VERSION_PARAMS[WinVersion.SERVER2016].image_index == 2
    assert VERSION_PARAMS[WinVersion.SERVER2022].os_variant == "win2k22"
    assert VERSION_PARAMS[WinVersion.WIN11].virtio_driver_dir == "w11"


def test_config_defaults():
    c = Config()
    assert c.name == "windev"
    assert c.user_name == "user"
    assert c.user_password == "pass"
    assert c.win_version is WinVersion.WIN11
    assert c.insider is False
    assert c.network == "bridge=virbr0"


@pytest.mark.parametrize("name, expected", [
    ("windev", "WINDEV"),
    ("my-vm", "MY-VM"),
    ("My VM Name", "MY-VM-NAME"),
    ("a.b.c", "A-B-C"),
    ("hello_world!", "HELLO-WORLD"),
    ("a--b--c", "A-B-C"),
    ("-leading-", "LEADING"),
    ("this-is-a-very-long-computer-name", "THIS-IS-A-VERY"),
    ("", "WINDEV"),
    ("---", "WINDEV"),
    ("vm123", "VM123"),
])
def test_sanitize_computer_name(name, expected):
    assert sanitize_computer_name(name) == expected


def test_vmsettings_defaults():
    s = VMSettings()
    assert s.locale == "en-US"
    assert s.timezone == "UTC"
    assert s.defender is False
    assert s.dark_mode is True
    assert s.openssh is True
    assert s.winget_packages == [
        "Microsoft.WinDbg",
        "Microsoft.Sysinternals.Suite",
        "WinFsp.WinFsp",
    ]


def test_settings_from_toml_empty():
    s = settings_from_toml({})
    assert s == VMSettings()


def test_settings_from_toml_partial():
    data = {
        "security": {"defender": True},
        "desktop": {"dark_mode": False},
        "packages": {"winget": ["My.Package"]},
    }
    s = settings_from_toml(data)
    assert s.defender is True
    assert s.dark_mode is False
    assert s.winget_packages == ["My.Package"]
    assert s.locale == "en-US"


def test_settings_from_toml_all_sections():
    data = {
        "locale": {"language": "fr-FR", "timezone": "CET"},
        "security": {"defender": True, "uac": True, "vbs": True},
        "privacy": {"telemetry": 1, "recall": True, "copilot": True,
                    "widgets": True, "consumer_features": True,
                    "bing_search": True},
        "updates": {"notify_only": False, "no_auto_reboot": False},
        "desktop": {"dark_mode": False, "animations": True,
                    "lock_screen": True},
        "explorer": {"file_extensions": False, "hidden_files": False,
                     "launch_to": "quick_access"},
        "power": {"hibernation": True, "monitor_timeout": 10,
                  "sleep_timeout": 30},
        "developer": {"mode": False, "long_paths": False},
        "apps": {"wsl": False, "remove_bloatware": False,
                "bloatware_keep": ["Store"], "windows_terminal": False},
        "packages": {"winget": []},
        "services": {"openssh": False, "rdp": False,
                     "rdp_usb_redirection": False},
    }
    s = settings_from_toml(data)
    assert s.locale == "fr-FR"
    assert s.timezone == "CET"
    assert s.defender is True
    assert s.telemetry == 1
    assert s.animations is True
    assert s.launch_to == "quick_access"
    assert s.monitor_timeout == 10
    assert s.wsl is False
    assert s.winget_packages == []
    assert s.openssh is False


def test_vm_overrides_from_toml():
    data = {
        "vm": {"name": "myvm", "ram": 16384, "disk": 128, "user": "admin"},
    }
    overrides = vm_overrides_from_toml(data)
    assert overrides == {
        "name": "myvm",
        "ram_mb": 16384,
        "disk_gb": 128,
        "user_name": "admin",
    }


def test_vm_overrides_from_toml_empty():
    assert vm_overrides_from_toml({}) == {}
    assert vm_overrides_from_toml({"vm": {}}) == {}


def test_config_with_settings():
    s = VMSettings(defender=True, locale="de-DE")
    c = Config(settings=s)
    assert c.settings.defender is True
    assert c.settings.locale == "de-DE"


def test_shared_folders_default_empty():
    s = VMSettings()
    assert s.shared_folders == []


def test_shared_folder_tag_from_source():
    sf = SharedFolder(source="/tmp/qemu-cc-panopticon")
    assert sf.tag == "qemu-cc-panopticon"


def test_shared_folder_explicit_tag():
    sf = SharedFolder(source="/tmp/shared", tag="custom")
    assert sf.tag == "custom"


def test_shared_folder_readonly():
    sf = SharedFolder(source="/tmp/shared", readonly=True)
    assert sf.readonly is True
    assert SharedFolder(source="/tmp/shared").readonly is False


def test_settings_from_toml_shared_folders():
    data = {
        "sharing": {
            "folders": [
                {"source": "/tmp/shared", "tag": "my-share"},
                {"source": "/home/user/data", "tag": "data"},
            ],
        },
    }
    s = settings_from_toml(data)
    assert s.shared_folders == [
        SharedFolder(source="/tmp/shared", tag="my-share"),
        SharedFolder(source="/home/user/data", tag="data"),
    ]


def test_settings_from_toml_shared_folders_string_form():
    data = {
        "sharing": {
            "folders": ["/tmp/shared", "/home/user/data"],
        },
    }
    s = settings_from_toml(data)
    assert s.shared_folders == [
        SharedFolder(source="/tmp/shared", tag="shared"),
        SharedFolder(source="/home/user/data", tag="data"),
    ]


def test_settings_from_toml_no_sharing_section():
    s = settings_from_toml({})
    assert s.shared_folders == []
