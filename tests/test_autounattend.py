from __future__ import annotations

import pathlib
import re

import pytest
from defusedxml import ElementTree as ET

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import autounattend

GOLDEN = pathlib.Path(__file__).parent / "golden"


def _strip_markers(text: str) -> str:
    text = re.sub(r"<!-- BEGIN_[A-Z0-9]+_ONLY.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<!-- END_[A-Z0-9]+_ONLY -->", "", text)
    text = re.sub(r"^# (BEGIN|END)_[A-Z]+_ONLY\s*$", "", text, flags=re.MULTILINE)
    return text


def test_user_data_win11_has_gvlk():
    xml = autounattend.user_data_for(WinVersion.WIN11)
    assert "NPPR9-FWDCX-D2C8J-H872K-2YT43" in xml
    assert "<AcceptEula>true</AcceptEula>" in xml


def test_user_data_win10_has_no_product_key():
    xml = autounattend.user_data_for(WinVersion.WIN10)
    assert "ProductKey" not in xml
    assert "<AcceptEula>true</AcceptEula>" in xml


def test_user_data_server2022_gvlk():
    assert "VDYBN-27WPP-V4HQT-9VMD4-VMK7H" in autounattend.user_data_for(WinVersion.SERVER2022)


def test_copy_openssh_zip_win10_server2016_only():
    assert "OpenSSH-Win64.zip" in autounattend.copy_openssh_zip_for(WinVersion.WIN10)
    assert "OpenSSH-Win64.zip" in autounattend.copy_openssh_zip_for(WinVersion.SERVER2016)
    assert autounattend.copy_openssh_zip_for(WinVersion.WIN11) == ""
    assert autounattend.copy_openssh_zip_for(WinVersion.SERVER2022) == ""


def test_rdsh_only_for_servers():
    assert "RDS-RD-Server" in autounattend.rdsh_firstlogon_for(WinVersion.SERVER2016)
    assert "RDS-RD-Server" in autounattend.rdsh_firstlogon_for(WinVersion.SERVER2022)
    assert autounattend.rdsh_firstlogon_for(WinVersion.WIN11) == ""
    assert autounattend.rdsh_firstlogon_for(WinVersion.WIN10) == ""


def test_openssh_firstlogon_variants():
    win11 = autounattend.openssh_firstlogon_for(WinVersion.WIN11)
    assert "Add-WindowsCapability" in win11 and "OpenSSH.Server~~~~0.0.1.0" in win11
    win10 = autounattend.openssh_firstlogon_for(WinVersion.WIN10)
    assert "Start-Service sshd" in win10 and "Add-WindowsCapability" not in win10


def test_winget_windbg_win11_only():
    assert "Microsoft.WinDbg" in autounattend.winget_windbg_for(WinVersion.WIN11)
    assert autounattend.winget_windbg_for(WinVersion.WIN10) == ""


def test_generate_is_well_formed_xml():
    for v in WinVersion:
        ET.fromstring(autounattend.generate_autounattend(Config(win_version=v)))


def test_generate_escapes_user_password():
    cfg = Config(win_version=WinVersion.WIN11, user_name="a&b", user_password="p<x")
    xml = autounattend.generate_autounattend(cfg)
    assert "a&amp;b" in xml
    assert "p&lt;x" in xml
    assert "a&b" not in xml and "p<x" not in xml


def test_generate_win11_has_drivers_and_usb_keys():
    xml = autounattend.generate_autounattend(Config(win_version=WinVersion.WIN11))
    assert "E:\\NetKVM\\w11\\amd64" in xml
    assert "fDisablePNPRedir" in xml and "fUsbRedirectionEnable" in xml
    assert "fUsbRedirectionUseDefaultList" in xml
    assert "<ComputerName>WinDev</ComputerName>" in xml


@pytest.mark.parametrize("version,filename", [
    (WinVersion.WIN11, "autounattend_11.xml"),
    (WinVersion.WIN10, "autounattend_10.xml"),
    (WinVersion.SERVER2016, "autounattend_server2016.xml"),
    (WinVersion.SERVER2022, "autounattend_server2022.xml"),
])
def test_generate_autounattend_matches_golden(version, filename):
    cfg = Config(win_version=version)
    generated = autounattend.generate_autounattend(cfg)
    golden = (GOLDEN / filename).read_text()
    assert _strip_markers(generated) == _strip_markers(golden)
