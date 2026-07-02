from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from virt_install_windev.config import Config, WinVersion
from virt_install_windev.iso import acquire_iso, IsoError, _insider_cache_name


def test_provided_iso_path_returned(tmp_path: Path):
    iso = tmp_path / "test.iso"
    iso.write_bytes(b"fake")
    cfg = Config(iso_path=str(iso))
    assert acquire_iso(cfg) == iso


def test_provided_iso_missing_raises(tmp_path: Path):
    cfg = Config(iso_path=str(tmp_path / "nope.iso"))
    with pytest.raises(IsoError, match="not found"):
        acquire_iso(cfg)


def test_cached_eval_iso_not_redownloaded(tmp_path: Path):
    iso = tmp_path / "win11-enterprise-eval.iso"
    iso.write_bytes(b"cached")
    cfg = Config(cache_dir=str(tmp_path), win_version=WinVersion.WIN11)
    assert acquire_iso(cfg) == iso


def test_insider_cache_name_is_version_specific():
    assert _insider_cache_name(WinVersion.WIN11) == "11-insider.iso"
    assert _insider_cache_name(WinVersion.WIN10) == "10-insider.iso"
    assert _insider_cache_name(WinVersion.SERVER2022) == "server2022-insider.iso"


def test_server2016_requires_manual_download(tmp_path: Path):
    cfg = Config(cache_dir=str(tmp_path), win_version=WinVersion.SERVER2016)
    with pytest.raises(IsoError, match="manual download"):
        acquire_iso(cfg)


def test_win10_no_eval_available(tmp_path: Path):
    cfg = Config(cache_dir=str(tmp_path), win_version=WinVersion.WIN10)
    with pytest.raises(IsoError, match="no longer offers"):
        acquire_iso(cfg)


def test_eval_download_uses_curl_fail(tmp_path: Path):
    cfg = Config(cache_dir=str(tmp_path), win_version=WinVersion.WIN11)
    with mock.patch("virt_install_windev.iso.run") as mock_run, \
         mock.patch("pathlib.Path.rename"):
        mock_run.return_value = None
        acquire_iso(cfg)
        args = mock_run.call_args[0][0]
        assert "--fail" in args
        assert "curl" in args[0]
