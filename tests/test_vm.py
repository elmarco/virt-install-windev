from __future__ import annotations

from unittest.mock import patch
import subprocess

import pytest

from virt_install_windev.config import Config, WinVersion
from virt_install_windev.util import CommandError
from virt_install_windev.vm import (
    _DISK_PROGRESS,
    _build_steps,
    _get_disk_target,
    _get_disk_writes,
    create_snapshot,
)


def test_build_steps_contains_disk_progress():
    config = Config(win_version=WinVersion.WIN11)
    steps = _build_steps(config)
    markers = [m for m, _ in steps]
    idx = markers.index(_DISK_PROGRESS)
    assert markers[idx - 1] == "starting Boot"
    assert markers[idx + 1].startswith("[SPECIALIZE]")


def test_build_steps_disk_progress_present_all_versions():
    for ver in WinVersion:
        config = Config(win_version=ver)
        markers = [m for m, _ in _build_steps(config)]
        assert _DISK_PROGRESS in markers


DOMBLKSTAT_OUTPUT = """\
vda rd_req 12345
vda rd_bytes 123456789
vda wr_req 67890
vda wr_bytes 5368709120
vda flush_operations 100
"""


DOMBLKLIST_OUTPUT = """\
 Type   Device   Target   Source
 ------------------------------------------------
 file   disk     sda      /home/user/.cache/virt-install-windev/testvm.qcow2
 file   cdrom    sdb      /tmp/win11.iso
"""


def test_get_disk_target_parses_output():
    fake = subprocess.CompletedProcess([], 0, stdout=DOMBLKLIST_OUTPUT, stderr="")
    with patch("virt_install_windev.vm.run", return_value=fake):
        assert _get_disk_target("testvm") == "sda"


def test_get_disk_target_handles_error():
    with patch("virt_install_windev.vm.run",
               side_effect=CommandError(["virsh"], 1, "")):
        assert _get_disk_target("testvm") is None


def test_get_disk_writes_parses_output():
    fake = subprocess.CompletedProcess([], 0, stdout=DOMBLKSTAT_OUTPUT, stderr="")
    with patch("virt_install_windev.vm.run", return_value=fake):
        assert _get_disk_writes("testvm", "vda") == 5368709120


def test_get_disk_writes_handles_error():
    with patch("virt_install_windev.vm.run",
               side_effect=CommandError(["virsh"], 1, "")):
        assert _get_disk_writes("testvm", "vda") is None


def test_get_disk_writes_handles_bad_output():
    fake = subprocess.CompletedProcess([], 0, stdout="garbage\n", stderr="")
    with patch("virt_install_windev.vm.run", return_value=fake):
        assert _get_disk_writes("testvm", "vda") is None


def test_create_snapshot_success():
    config = Config(name="testvm")
    fake = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with patch("virt_install_windev.vm.run", return_value=fake):
        assert create_snapshot(config) is True


def test_create_snapshot_failure():
    config = Config(name="testvm")
    with patch("virt_install_windev.vm.run",
               side_effect=CommandError(["virsh"], 1, "")):
        assert create_snapshot(config) is False
