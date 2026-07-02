from __future__ import annotations

import subprocess

import pytest

from virt_install_windev import util


def test_xml_escape():
    assert util.xml_escape("plain") == "plain"
    assert util.xml_escape("a&b") == "a&amp;b"
    assert util.xml_escape("a<b>c") == "a&lt;b&gt;c"


def test_run_success_capture():
    r = util.run(["true"], capture=True)
    assert r.returncode == 0


def test_run_failure_raises_command_error():
    with pytest.raises(util.CommandError) as exc:
        util.run(["sh", "-c", "echo boom 1>&2; exit 7"], capture=True)
    assert exc.value.returncode == 7
    assert "boom" in exc.value.stderr
    assert exc.value.cmd == ["sh", "-c", "echo boom 1>&2; exit 7"]


def test_run_no_check_returns_nonzero():
    r = util.run(["sh", "-c", "exit 7"], check=False, capture=True)
    assert r.returncode == 7
