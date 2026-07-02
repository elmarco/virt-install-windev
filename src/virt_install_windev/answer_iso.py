from __future__ import annotations

import glob
from pathlib import Path

from virt_install_windev.config import Config, WinVersion
from virt_install_windev.util import log, run

OPENSSH_URL = "https://github.com/PowerShell/Win32-OpenSSH/releases/latest/download/OpenSSH-Win64.zip"


def _collect_ssh_keys(work_dir: Path) -> Path | None:
    pub_keys = sorted(glob.glob(str(Path.home() / ".ssh" / "id_*.pub")))
    if not pub_keys:
        return None
    dest = work_dir / "authorized_keys"
    with open(dest, "w") as f:
        for key_file in pub_keys:
            f.write(Path(key_file).read_text())
    count = sum(1 for line in dest.read_text().splitlines() if line.strip())
    log(f"Bundled {count} SSH public key(s)")
    return dest


def _download_openssh_zip(work_dir: Path) -> Path | None:
    dest = work_dir / "OpenSSH-Win64.zip"
    log("Downloading Win32-OpenSSH...")
    try:
        run(["curl", "-sL", "--fail", "-o", str(dest), OPENSSH_URL])
    except Exception:
        log("Warning: failed to download Win32-OpenSSH, SSH may not work")
        return None
    if not dest.is_file() or dest.stat().st_size == 0:
        log("Warning: failed to download Win32-OpenSSH, SSH may not work")
        dest.unlink(missing_ok=True)
        return None
    return dest


def build_answer_iso(
    work_dir: Path,
    autounattend_xml: str,
    setup_ps1: str,
    config: Config,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)

    (work_dir / "autounattend.xml").write_text(autounattend_xml)
    (work_dir / "setup.ps1").write_text(setup_ps1)

    files: list[str] = [
        str(work_dir / "autounattend.xml"),
        str(work_dir / "setup.ps1"),
    ]

    key_file = _collect_ssh_keys(work_dir)
    if key_file:
        files.append(str(key_file))

    if config.win_version in (WinVersion.WIN10, WinVersion.SERVER2016):
        openssh = _download_openssh_zip(work_dir)
        if openssh:
            files.append(str(openssh))

    cache = Path(config.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    iso_path = cache / f"{config.name}-autounattend.iso"

    run(["genisoimage", "-quiet", "-o", str(iso_path), "-J", "-r"] + files)
    log(f"Created answer-file ISO: {iso_path}")
    return iso_path
