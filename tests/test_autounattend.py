from __future__ import annotations

import pathlib
import re

import pytest
from defusedxml import ElementTree as ET

from virt_install_windev.config import Config, VMSettings, WinVersion
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


def test_openssh_zip_in_win10_server2016():
    for v in (WinVersion.WIN10, WinVersion.SERVER2016):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "OpenSSH-Win64.zip" in xml


def test_no_openssh_zip_in_win11_server2022():
    for v in (WinVersion.WIN11, WinVersion.SERVER2022):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "OpenSSH-Win64.zip" not in xml


def test_rdsh_only_for_servers():
    for v in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "RDS-RD-Server" in xml
    for v in (WinVersion.WIN10, WinVersion.WIN11):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "RDS-RD-Server" not in xml


def test_openssh_capability_for_win11_server2022():
    for v in (WinVersion.WIN11, WinVersion.SERVER2022):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "Add-WindowsCapability" in xml
        assert "OpenSSH.Server~~~~0.0.1.0" in xml
    for v in (WinVersion.WIN10, WinVersion.SERVER2016):
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "Add-WindowsCapability" not in xml


def test_winget_packages_all_versions():
    for v in WinVersion:
        xml = autounattend.generate_autounattend(Config(win_version=v))
        assert "Microsoft.WinDbg" in xml


def test_generate_is_well_formed_xml():
    for v in WinVersion:
        ET.fromstring(autounattend.generate_autounattend(Config(win_version=v)))


def test_generate_escapes_user_password():
    cfg = Config(win_version=WinVersion.WIN11, user_name="a&b", user_password="p<x")
    xml = autounattend.generate_autounattend(cfg)
    assert "a&amp;b" in xml
    assert "p&lt;x" in xml
    assert "a&b" not in xml and "p<x" not in xml


def test_generate_password_containing_token_not_resubstituted():
    cfg = Config(win_version=WinVersion.WIN11, user_name="alice", user_password="YOURUSER")
    xml = autounattend.generate_autounattend(cfg)
    assert "<Value>YOURUSER</Value>" in xml
    assert "<Name>alice</Name>" in xml
    assert "<Username>alice</Username>" in xml


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


# --- Settings-conditional tests ---

def test_defender_enabled_skips_disable():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(defender=True))
    xml = autounattend.generate_autounattend(cfg)
    assert "Services\\Sense" not in xml
    assert "Services\\WinDefend" not in xml


def test_defender_disabled_includes_disable():
    cfg = Config(win_version=WinVersion.WIN11)
    xml = autounattend.generate_autounattend(cfg)
    assert "Services\\Sense" in xml
    assert "Services\\WinDefend" in xml


def test_rdp_disabled_removes_components():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(rdp=False))
    xml = autounattend.generate_autounattend(cfg)
    assert "fDenyTSConnections" not in xml
    assert "RemoteDesktop" not in xml


def test_openssh_disabled():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(openssh=False))
    xml = autounattend.generate_autounattend(cfg)
    assert "OpenSSH" not in xml
    assert "sshd" not in xml


def test_bloatware_removal_disabled():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(remove_bloatware=False))
    xml = autounattend.generate_autounattend(cfg)
    assert "AppxProvisionedPackage" not in xml


def test_custom_winget_packages():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(winget_packages=["My.Package"]))
    xml = autounattend.generate_autounattend(cfg)
    assert "My.Package" in xml
    assert "Microsoft.WinDbg" not in xml


def test_no_winget_packages():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(winget_packages=[]))
    xml = autounattend.generate_autounattend(cfg)
    assert "winget install" not in xml


def test_locale_and_timezone():
    cfg = Config(win_version=WinVersion.WIN11,
                 settings=VMSettings(locale="fr-FR", timezone="Romance Standard Time"))
    xml = autounattend.generate_autounattend(cfg)
    assert "fr-FR" in xml
    assert "en-US" not in xml
    assert "Romance Standard Time" in xml
    assert "UTC" not in xml
