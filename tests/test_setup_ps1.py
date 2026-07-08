from __future__ import annotations

import pathlib
import re

import pytest

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import setup_ps1

GOLDEN = pathlib.Path(__file__).parent / "golden"


def _strip_markers(text: str) -> str:
    text = re.sub(r"<!-- BEGIN_[A-Z0-9]+_ONLY.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<!-- END_[A-Z0-9]+_ONLY -->", "", text)
    text = re.sub(r"^# (BEGIN|END)_[A-Z]+_ONLY\s*$", "", text, flags=re.MULTILINE)
    return text


def test_client_has_wsl():
    ps1 = setup_ps1.generate_setup_ps1(Config(win_version=WinVersion.WIN11))
    assert "Microsoft-Windows-Subsystem-Linux" in ps1
    assert "VirtualMachinePlatform" in ps1
    assert "ServerManager" not in ps1


def test_server_has_server_manager():
    ps1 = setup_ps1.generate_setup_ps1(Config(win_version=WinVersion.SERVER2022))
    assert "DoNotOpenServerManagerAtLogon" in ps1
    assert "Microsoft-Windows-Subsystem-Linux" not in ps1


def test_all_versions_have_openssh_zip_block():
    for v in WinVersion:
        ps1 = setup_ps1.generate_setup_ps1(Config(win_version=v))
        assert "OpenSSH-Win64.zip" in ps1


def test_client_has_windows_terminal_config():
    for v in (WinVersion.WIN10, WinVersion.WIN11):
        ps1 = setup_ps1.generate_setup_ps1(Config(win_version=v))
        assert "WindowsTerminal" in ps1
        assert "settings.json" in ps1
        assert "Cascadia Mono" in ps1


def test_server_has_no_windows_terminal_config():
    for v in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        ps1 = setup_ps1.generate_setup_ps1(Config(win_version=v))
        assert "WindowsTerminal" not in ps1


def test_all_versions_have_dark_mode():
    for v in WinVersion:
        ps1 = setup_ps1.generate_setup_ps1(Config(win_version=v))
        assert "AppsUseLightTheme" in ps1
        assert "SystemUsesLightTheme" in ps1


@pytest.mark.parametrize("version,filename", [
    (WinVersion.WIN11, "setup_11.ps1"),
    (WinVersion.WIN10, "setup_10.ps1"),
    (WinVersion.SERVER2016, "setup_server2016.ps1"),
    (WinVersion.SERVER2022, "setup_server2022.ps1"),
])
def test_generate_setup_ps1_matches_golden(version, filename):
    cfg = Config(win_version=version)
    generated = setup_ps1.generate_setup_ps1(cfg)
    golden = (GOLDEN / filename).read_text()
    assert _strip_markers(generated) == _strip_markers(golden)
