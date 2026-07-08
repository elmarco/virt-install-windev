from __future__ import annotations

import os
from pathlib import Path

from virt_install_windev.config import Config, WinVersion
from virt_install_windev.ui import log
from virt_install_windev.util import run, CommandError


EVAL_URL = "https://go.microsoft.com/fwlink/?linkid=2334167&clcid=0x409&culture=en-us&country=us"

_SERVER_DOWNLOAD_URLS: dict[WinVersion, str] = {
    WinVersion.SERVER2016: "https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2016",
    WinVersion.SERVER2022: "https://www.microsoft.com/en-us/evalcenter/evaluate-windows-server-2022",
}


class IsoError(Exception):
    pass


def _insider_cache_name(version: WinVersion) -> str:
    return f"{version.value}-insider.iso"


def _download(url: str, dest: Path) -> None:
    part = dest.with_suffix(".iso.part")
    try:
        run(["curl", "--fail", "-L", "-o", str(part), "--progress-bar", url])
    except CommandError as exc:
        part.unlink(missing_ok=True)
        raise IsoError(f"download failed: {exc}") from exc
    part.rename(dest)


def acquire_iso(config: Config) -> Path:
    cache = Path(config.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    if config.iso_path:
        p = Path(config.iso_path)
        if not p.is_file():
            raise IsoError(f"ISO not found at {p}")
        log(f"Using provided ISO: {p}")
        return p

    if config.insider:
        iso = cache / _insider_cache_name(config.win_version)
        if iso.is_file():
            log(f"Insider ISO already cached: {iso}")
            log(f"Delete it to re-download: rm {iso}")
            return iso

        from virt_install_windev.insider import get_insider_download_url, InsiderDownloadError

        log("Launching browser to download Windows Insider Preview ISO...")
        log("You will need to sign in with your Microsoft (Insider) account.")
        try:
            url = get_insider_download_url(
                edition=config.insider_edition,
                lang=config.insider_lang,
                timeout=config.insider_timeout,
            )
        except InsiderDownloadError as exc:
            raise IsoError(
                f"failed to get Insider Preview download URL: {exc}\n"
                "You can download manually from:\n"
                "  https://www.microsoft.com/en-us/software-download/windowsinsiderpreviewiso\n"
                "Then re-run with: virt-install-windev --iso /path/to/downloaded.iso"
            ) from exc

        log(f"Downloading: {url}")
        log("This is ~6 GB and may take a while.")
        _download(url, iso)
        log(f"ISO saved to: {iso}")
        return iso

    v = config.win_version

    if v in _SERVER_DOWNLOAD_URLS:
        raise IsoError(
            f"Windows {v.value} evaluation ISOs require manual download.\n"
            f"Download from: {_SERVER_DOWNLOAD_URLS[v]}\n"
            f"Then re-run with: virt-install-windev --{v.value} --iso /path/to/iso"
        )

    if v == WinVersion.WIN10:
        raise IsoError(
            "Microsoft no longer offers Windows 10 evaluation ISOs for download.\n"
            "Provide a Windows 10 ISO with: virt-install-windev --iso /path/to/Win10.iso"
        )

    iso = cache / "win11-enterprise-eval.iso"
    if iso.is_file():
        log(f"ISO already cached: {iso}")
        return iso

    log("Downloading Windows 11 Enterprise Evaluation ISO...")
    log("This is ~6 GB and may take a while.")
    _download(EVAL_URL, iso)
    log(f"ISO saved to: {iso}")
    return iso
