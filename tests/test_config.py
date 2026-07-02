from __future__ import annotations

from virt_install_windev.config import (
    Config, WinVersion, VERSION_PARAMS, detect_win_version,
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
