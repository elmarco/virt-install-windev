from __future__ import annotations

from unittest import mock

from virt_install_windev.config import Config
from virt_install_windev.deps import check_dependencies, MissingDep


def test_no_missing_when_all_present():
    cfg = Config()
    with mock.patch("shutil.which", return_value="/usr/bin/x"), \
         mock.patch("pathlib.Path.exists", return_value=True):
        assert check_dependencies(cfg) == []


def test_missing_command_reported():
    def fake_which(name: str) -> str | None:
        return None if name == "swtpm" else f"/usr/bin/{name}"

    cfg = Config()
    with mock.patch("shutil.which", side_effect=fake_which), \
         mock.patch("pathlib.Path.exists", return_value=True):
        result = check_dependencies(cfg)
        assert len(result) == 1
        assert "swtpm" in result[0].what
        assert "swtpm-tools" in result[0].hint


def test_missing_virtio_iso():
    def fake_exists(self: object) -> bool:
        return "virtio" not in str(self)

    cfg = Config()
    with mock.patch("shutil.which", return_value="/usr/bin/x"), \
         mock.patch("pathlib.Path.exists", fake_exists):
        result = check_dependencies(cfg)
        assert any("virtio-win" in d.what for d in result)


def test_missing_ovmf():
    def fake_exists(self: object) -> bool:
        return "OVMF" not in str(self)

    cfg = Config()
    with mock.patch("shutil.which", return_value="/usr/bin/x"), \
         mock.patch("pathlib.Path.exists", fake_exists):
        result = check_dependencies(cfg)
        assert any("OVMF" in d.what for d in result)


def test_insider_without_selenium():
    cfg = Config(insider=True)
    with mock.patch("shutil.which", return_value="/usr/bin/x"), \
         mock.patch("pathlib.Path.exists", return_value=True), \
         mock.patch.dict("sys.modules", {"selenium": None}):
        result = check_dependencies(cfg)
        assert any("selenium" in d.what for d in result)


def test_insider_not_checked_when_disabled():
    cfg = Config(insider=False)
    with mock.patch("shutil.which", return_value="/usr/bin/x"), \
         mock.patch("pathlib.Path.exists", return_value=True):
        result = check_dependencies(cfg)
        assert not any("selenium" in d.what for d in result)
