from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
from pathlib import Path

from virt_install_windev.config import Config, WinVersion, detect_win_version


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="virt-install-windev",
        description=(
            "Download a Windows ISO and create a fully-unattended libvirt VM "
            "with virtio drivers, UEFI, and TPM 2.0."
        ),
    )
    p.add_argument("--name", default="windev", help="VM name (default: windev)")
    p.add_argument("--iso", dest="iso_path", help="Use an existing Windows ISO")
    p.add_argument("--win10", action="store_const", const=WinVersion.WIN10,
                   dest="win_version", help="Use Windows 10")
    p.add_argument("--server2016", action="store_const", const=WinVersion.SERVER2016,
                   dest="win_version", help="Use Windows Server 2016")
    p.add_argument("--server2022", action="store_const", const=WinVersion.SERVER2022,
                   dest="win_version", help="Use Windows Server 2022")
    p.add_argument("--insider", action="store_true",
                   help="Download Insider Preview ISO via browser automation")
    p.add_argument("--edition", default="Release Preview",
                   help="Insider edition substring (default: 'Release Preview')")
    p.add_argument("--lang", default="English (United States)",
                   help="Insider language substring (default: 'English (United States)')")
    p.add_argument("--timeout", type=int, default=300,
                   help="Insider sign-in timeout in seconds (default: 300)")
    p.add_argument("--vcpus", type=int, default=4, help="Number of vCPUs (default: 4)")
    p.add_argument("--ram", type=int, default=8192, dest="ram_mb",
                   help="RAM in MiB (default: 8192)")
    p.add_argument("--disk", type=int, default=64, dest="disk_gb",
                   help="Disk size in GiB (default: 64)")
    p.add_argument("--user", default="user", dest="user_name",
                   help="Local admin username (default: user)")
    p.add_argument("--password", default="pass", dest="user_password",
                   help="Local admin password (default: pass)")
    p.add_argument("--no-wait", action="store_true",
                   help="Don't wait for installation to finish")
    p.add_argument("--force", action="store_true",
                   help="Destroy and remove existing VM with the same name")
    p.add_argument("--debug", action="store_true",
                   help="Show raw VM console output instead of progress summary")
    p.add_argument("--generate-only", metavar="DIR",
                   help="Emit answer files to DIR and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    win_version = args.win_version

    if win_version is None and args.iso_path:
        detected = detect_win_version(os.path.basename(args.iso_path))
        if detected:
            win_version = detected

    if win_version is None:
        win_version = WinVersion.WIN11

    config = Config(
        name=args.name,
        vcpus=args.vcpus,
        ram_mb=args.ram_mb,
        disk_gb=args.disk_gb,
        user_name=args.user_name,
        user_password=args.user_password,
        computer_name="WinDev",
        win_version=win_version,
        iso_path=args.iso_path,
        insider=args.insider,
        insider_edition=args.edition,
        insider_lang=args.lang,
        insider_timeout=args.timeout,
        no_wait=args.no_wait,
        force=args.force,
        debug=args.debug,
    )

    from virt_install_windev.autounattend import generate_autounattend
    from virt_install_windev.setup_ps1 import generate_setup_ps1

    xml = generate_autounattend(config)
    ps1 = generate_setup_ps1(config)

    if args.generate_only:
        out = Path(args.generate_only)
        out.mkdir(parents=True, exist_ok=True)
        (out / "autounattend.xml").write_text(xml)
        (out / "setup.ps1").write_text(ps1)
        print(f"Generated answer files in {out}", file=sys.stderr)
        return 0

    from virt_install_windev.deps import check_dependencies
    from virt_install_windev.iso import acquire_iso, IsoError
    from virt_install_windev.answer_iso import build_answer_iso
    from virt_install_windev import vm

    missing = check_dependencies(config)
    if missing:
        for dep in missing:
            print(f"Error: {dep.what}", file=sys.stderr)
            print(f"  Fix: {dep.hint}", file=sys.stderr)
        return 1

    try:
        vm.remove_existing_vm(config)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        win_iso = acquire_iso(config)
    except IsoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="virt-install-windev-") as tmpdir:
        unattend_iso = build_answer_iso(
            Path(tmpdir), xml, ps1, config,
        )

        disk = vm.create_disk(config)
        install_log = Path(config.cache_dir) / f"{config.name}-install.log"

        vm.create_and_start_vm(config, disk, win_iso, unattend_iso, install_log)

        boot_thread = threading.Thread(
            target=vm.send_boot_keys,
            args=(config, install_log),
            daemon=True,
        )
        boot_thread.start()

        try:
            if not config.no_wait:
                vm.wait_for_install(config, install_log)
                vm.detach_cdroms(config)
        except KeyboardInterrupt:
            print("", file=sys.stderr)
            return _handle_interrupt(config, disk)

    vm.print_success(config)
    return 0


def _handle_interrupt(config: Config, disk: Path) -> int:
    from virt_install_windev import vm

    try:
        answer = input(f"\nStop and delete VM '{config.name}' and disk ({disk})? [Y/n] ")
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)
        answer = "y"

    if answer.strip().lower() in ("", "y", "yes"):
        vm.destroy_vm(config)
        vm.undefine_vm(config)
        disk.unlink(missing_ok=True)
        print("VM and disk removed.", file=sys.stderr)
    else:
        print(f"VM kept. Resume: virsh start {config.name}",
              file=sys.stderr)

    return 130
