from __future__ import annotations

from unittest import mock

from virt_install_windev.config import Config
from virt_install_windev.deps import check_dependencies, preflight_checks, MissingDep
from virt_install_windev.util import CommandError


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


def test_preflight_no_kvm(tmp_path):
    cfg = Config(cache_dir=str(tmp_path))
    with mock.patch("virt_install_windev.deps.Path") as MockPath, \
         mock.patch("virt_install_windev.deps.run"), \
         mock.patch("shutil.disk_usage", return_value=mock.Mock(free=200 * 1024**3)), \
         mock.patch("builtins.open", mock.mock_open(read_data="MemAvailable: 16000000 kB\n")), \
         mock.patch("os.getuid", return_value=0):
        kvm_path = mock.Mock()
        kvm_path.exists.return_value = False
        cache_path = mock.Mock()
        cache_path.mkdir = mock.Mock()
        def path_side_effect(p):
            if p == "/dev/kvm":
                return kvm_path
            return cache_path
        MockPath.side_effect = path_side_effect
        result = preflight_checks(cfg)
        assert any("KVM" in d.what for d in result)


def test_preflight_virsh_fails(tmp_path):
    cfg = Config(cache_dir=str(tmp_path))
    with mock.patch("virt_install_windev.deps.Path") as MockPath, \
         mock.patch("virt_install_windev.deps.run", side_effect=CommandError(["virsh"], 1, "")), \
         mock.patch("shutil.disk_usage", return_value=mock.Mock(free=200 * 1024**3)), \
         mock.patch("builtins.open", mock.mock_open(read_data="MemAvailable: 16000000 kB\n")), \
         mock.patch("os.getuid", return_value=0):
        kvm_path = mock.Mock()
        kvm_path.exists.return_value = True
        cache_path = mock.Mock()
        cache_path.mkdir = mock.Mock()
        def path_side_effect(p):
            if p == "/dev/kvm":
                return kvm_path
            return cache_path
        MockPath.side_effect = path_side_effect
        result = preflight_checks(cfg)
        assert any("libvirt" in d.what for d in result)


def test_preflight_low_disk(tmp_path):
    cfg = Config(cache_dir=str(tmp_path), disk_gb=64)
    with mock.patch("virt_install_windev.deps.Path") as MockPath, \
         mock.patch("virt_install_windev.deps.run"), \
         mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10 * 1024**3)), \
         mock.patch("builtins.open", mock.mock_open(read_data="MemAvailable: 16000000 kB\n")), \
         mock.patch("os.getuid", return_value=0):
        kvm_path = mock.Mock()
        kvm_path.exists.return_value = True
        cache_path = mock.Mock()
        cache_path.mkdir = mock.Mock()
        def path_side_effect(p):
            if p == "/dev/kvm":
                return kvm_path
            return cache_path
        MockPath.side_effect = path_side_effect
        result = preflight_checks(cfg)
        assert any("disk space" in d.what for d in result)


def test_preflight_libvirt_group_warning(tmp_path):
    cfg = Config(cache_dir=str(tmp_path))
    with mock.patch("virt_install_windev.deps.Path") as MockPath, \
         mock.patch("virt_install_windev.deps.run"), \
         mock.patch("shutil.disk_usage", return_value=mock.Mock(free=200 * 1024**3)), \
         mock.patch("builtins.open", mock.mock_open(read_data="MemAvailable: 16000000 kB\n")), \
         mock.patch("os.getuid", return_value=1000), \
         mock.patch("os.getgroups", return_value=[1000, 100]), \
         mock.patch("grp.getgrnam", return_value=mock.Mock(gr_gid=999)):
        kvm_path = mock.Mock()
        kvm_path.exists.return_value = True
        cache_path = mock.Mock()
        cache_path.mkdir = mock.Mock()
        def path_side_effect(p):
            if p == "/dev/kvm":
                return kvm_path
            return cache_path
        MockPath.side_effect = path_side_effect
        result = preflight_checks(cfg)
        warnings = [d for d in result if d.warning]
        assert any("libvirt" in d.what for d in warnings)
