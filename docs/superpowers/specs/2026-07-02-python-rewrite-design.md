# Python rewrite of virt-install-windev

**Date:** 2026-07-02
**Status:** Design (pending approval)
**Scope:** Rewrite the monolithic 1563-line `virt-install-windev.sh` as a small Python package, preserving user-facing behavior while making the code easier to read, extend, and test.

## Goals

- **Readability:** focused modules each with one responsibility, instead of one 1500-line script.
- **Extensibility:** adding a Windows version or a registry tweak is a localized change, not a copy-paste across four `BEGIN_*_ONLY` marker blocks.
- **Testability:** the pure generators (autounattend.xml, setup.ps1, version detection, caching) are unit-tested with pytest. The fragile `sed` marker-stripping and `YOURUSER`/`YOURPASSWORD` substitution are eliminated.
- **Modernization:** stdlib Python, argparse, dataclasses, pathlib; `pyproject.toml` with a console-script entry point; optional `selenium` extra for the Insider path.

## Non-goals

- No new user-facing features. The CLI flags and defaults stay the same.
- No change to the VM hardware, the unattended install *semantics*, or the serial-port completion protocol. The generated `autounattend.xml` and `setup.ps1` remain byte-equivalent to today's output (validated by golden-file snapshots — see Testing).
- No risky redesign of working-but-fragile mechanisms: the OVMF `starting Boot` boot-key timing and the `for %d in (D E F G H I)` drive-letter scans in the generated Windows commands are preserved as-is. They work in practice and changing them is out of scope for a refactor.

## Assumptions (to confirm with user)

1. **Scope = rewrite + fold in open review fixes.** Beyond structure, fix the review findings that are natural in Python and low-risk:
   - **#3** OpenSSH ZIP download uses `curl --fail` (or `urllib`) so a 404 HTML page is never bundled as the ZIP; failure is a clear warning, not a silent no-SSH VM.
   - **#4** A failed `virsh start` during the reboot loop is non-fatal: log the error with diagnostics and break out with a clear message, instead of `set -e` aborting silently mid-install.
   - **#6** The dependency check verifies `python3` and, for `--insider`, that `selenium` is importable — with an actionable error message.
   - **#7** The Insider ISO cache filename is version-specific (`win11-insider.iso` / `win10-insider.iso` / …) so cross-version runs don't reuse the wrong cached ISO.
   - The Insider `--timeout` flag is surfaced in the main CLI (currently hidden inside the helper).
2. **Preserve current USB-redirection behavior** exactly as it is today: all three reg-adds under `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services` (`fDisablePNPRedir=0`, `fUsbRedirectionEnable=1`, `fUsbRedirectionUseDefaultList=1`). The user restored the latter two after review #1; the rewrite replicates the *current* bash output.
3. **Python 3.9+** (dataclasses, enums, f-strings, pathlib). Fedora ships 3.12+.
4. **Distribution:** `pyproject.toml` with a `virt-install-windev` console-script entry point. The old `virt-install-windev.sh` is removed; the README is updated to the new invocation (`virt-install-windev …` or `python -m virt_install_windev`).

## Architecture

### Package layout

```
src/virt_install_windev/
  __init__.py
  __main__.py          # `python -m virt_install_windev` → cli.main()
  cli.py               # argparse + top-level orchestration (the "main" flow)
  config.py            # Config dataclass, WinVersion enum, per-version params, ISO-filename detection
  deps.py              # check_dependencies() — external commands + files + python pkgs
  iso.py               # acquire_iso(): eval download + cache + manual path
  insider.py           # get_insider_download_url() — folded from download-insider-iso.py
  autounattend.py      # generate_autounattend(config) -> str
  setup_ps1.py         # generate_setup_ps1(config) -> str
  answer_iso.py        # build_answer_iso(work_dir, files) -> Path  (genisoimage wrapper)
  vm.py                # libvirt ops: remove_existing, create_and_start, send_boot_keys,
                       #   wait_for_install, detach_cdroms
  util.py              # run() subprocess wrapper, xml_escape, logging helpers
tests/
  conftest.py
  test_config.py       # ISO-filename → WinVersion detection
  test_autounattend.py # per-version XML: well-formed, right key/index/drivers, escaping, no wrong-version blocks
  test_setup_ps1.py    # client vs server variants
  test_iso.py          # caching logic; version-specific Insider cache key
  test_util.py         # xml_escape, run() error behavior
  golden/              # pinned autounattend.xml / setup.ps1 per version (equivalence guard)
pyproject.toml
README.md
```

~10 small modules. Each has one responsibility and can be read and tested independently.

### Module responsibilities

- **config.py** — `WinVersion` enum (`WIN10`, `WIN11`, `SERVER2016`, `SERVER2022`) plus a `@dataclass Config` holding all CLI-derived settings (name, vcpus, ram, disk, user, password, win_version, iso_path, insider flags, …). `detect_win_version(iso_filename) -> WinVersion` encodes today's regexes as explicit Python. Per-version params (`virtio_driver_dir`, `os_variant`, `image_index`) live in a dict keyed by `WinVersion` — replacing the `case` statement.
- **deps.py** — `check_dependencies(config) -> list[MissingDep]`. Checks external commands (virt-install, virsh, qemu-img, genisoimage, curl, swtpm), the virtio-win ISO, OVMF firmware, and (for `--insider`) that `selenium` is importable. Errors are collected and reported with install hints, instead of one `exit 1`.
- **iso.py** — `acquire_iso(config, cache_dir) -> Path`. Three paths: provided `--iso`, Insider (calls `insider.get_insider_download_url` then downloads with `curl --fail -C -` for resume), or eval download. Cache check first; Insider cache filename is version-specific (fix #7).
- **insider.py** — the current `download-insider-iso.py` refactored into `get_insider_download_url(edition, lang, timeout) -> str`, raising a typed exception on failure. The Selenium logic is otherwise unchanged.
- **autounattend.py** — `generate_autounattend(config) -> str`. See "autounattend generation" below.
- **setup_ps1.py** — `generate_setup_ps1(config) -> str`. One template string; the client-vs-server split (WSL vs Server-Manager suppression) is an explicit Python `if`, replacing `BEGIN_CLIENT_ONLY`/`END_CLIENT_ONLY` marker stripping.
- **answer_iso.py** — `build_answer_iso(work_dir, files) -> Path`: wraps `genisoimage`.
- **vm.py** — all `virsh`/`virt-install` interaction: `remove_existing_vm`, `create_and_start_vm`, `send_boot_keys` (the `starting Boot` subshell logic), `wait_for_install` (the domstate-polling + `INSTALLATION_COMPLETE` sentinel loop, with the non-fatal restart fix #4), `detach_cdroms`.
- **util.py** — `run(cmd, ...)`: a `subprocess.run` wrapper that raises `CommandError` carrying the command, return code, and captured stderr; callers decide fatal vs non-fatal. `xml_escape(s)`: escapes `&` `<` `>` for XML text content. Small logging helpers that prefix lines like the current `[vm]` tail.

### autounattend generation (the core testability win)

Today: three giant heredocs + `BEGIN_WIN10_ONLY`/`BEGIN_SERVER2016_ONLY`/… marker comments + a `sed` loop that deletes the non-matching blocks + `sed` substitution of `YOURUSER`/`YOURPASSWORD`/`VIRTIO_DRIVER_DIR`/`IMAGE_INDEX`.

New approach — **template + Python composition** (chosen over building the XML with lxml):

- The autounattend XML stays as readable template strings, close to today's heredocs, so it can be diffed against the current output and remains the human-readable spec.
- Version-specific fragments are **functions** returning XML strings, composed by explicit Python conditionals:
  - `user_data_for(version)` — the `<UserData>` product-key block per version (replaces the four marker blocks).
  - `openssh_firstlogon_for(version)` — Win11/Server2022 use `Add-WindowsCapability`; Win10/Server2016 just `Start-Service` (replaces four blocks, two distinct).
  - `rdsh_firstlogon_for(version)` — present only for Server2016/Server2022 (one shared fragment, used for both — eliminates the byte-identical duplication).
  - `copy_openssh_zip_for(version)` — present only for Win10/Server2016 (one shared fragment).
- The marker-comment mechanism is **deleted entirely**. Version selection is explicit and testable: `test_autounattend.py` asserts that, e.g., a Win10 render contains no RDSH block and no Win11 product key, and a Server2022 render contains the RDSH block and the Server2022 GVLK.
- User-controlled values (`user`, `password`, `computer_name`) are inserted with `xml_escape` (the same two-layer fix already applied in bash commit `2f376b5`, but here only one layer is needed — XML — because there's no `sed`). `VIRTIO_DRIVER_DIR` and `IMAGE_INDEX` are internal constants, substituted as-is.

Why not lxml: unattend XML is verbose boilerplate with fixed component attributes and namespaces. Building it as a tree would bury the XML behind a wall of Python and make byte-equivalence verification painful. Template strings keep the XML readable and diffable; `xml.etree.ElementTree.fromstring` in tests still guarantees the output is well-formed.

### Error handling

`set -euo pipefail` + scattered `2>/dev/null` is replaced by `util.run()`:

- A failing command raises `CommandError` with the full command, return code, and stderr.
- The caller decides: `vm.wait_for_install` catches a `virsh start` failure, logs it with diagnostics, and breaks the loop with a clear message (fix #4) — no silent abort.
- Fatal paths print an actionable error and exit non-zero, never swallowing the reason.

### Testing strategy

pytest, focused on the pure generators (highest value, easiest):

- **`test_config.py`** — `detect_win_version` over many filenames: `Win11_24H2_English_x64.iso`, `Win10_22H2_…iso`, `en_windows_server_2016…iso`, `SERVER_EVAL_x64FRE_en-us.iso`, mixed case, insider filenames, and an unknown name → default `WIN11`.
- **`test_autounattend.py`** — for each `WinVersion`: the rendered XML parses (`ElementTree.fromstring`); it contains the correct GVLK / `IMAGE_INDEX` / `VIRTIO_DRIVER_DIR`; `user`/`password` with metacharacters (`&`, `<`, `/`) are XML-escaped; and version-incompatible blocks are absent (no RDSH on Win10/Win11; no Win11 product key on Win10).
- **`test_setup_ps1.py`** — client variants contain the WSL section and not the Server-Manager block; server variants the reverse.
- **`test_iso.py`** — a second `acquire_iso` call with a cached file does not re-download; the Insider cache path differs by `win_version` (fix #7). Downloads are mocked.
- **`test_util.py`** — `xml_escape` cases; `run()` raises `CommandError` on non-zero and captures stderr.
- **Golden files (`tests/golden/`)** — `autounattend_<version>.xml` and `setup_<version>.ps1` pinned for all four versions. Tests assert `generate_*(config) == golden`. This is the **equivalence guard**: it proves the rewrite produces the same answer-file content as today. Golden files are generated once (see Migration) and reviewed before commit.

Subprocess-heavy modules (`vm.py`, `answer_iso.py`, `iso.py` download) are tested by injecting a fake `run`/`requests` — no real libvirt/QEMU in CI.

### Packaging

- `pyproject.toml` (setuptools backend). Core depends on **stdlib only**. `selenium` is an optional extra: `pip install virt-install-windev[insider]`.
- Console-script entry point: `virt-install-windev = virt_install_windev.cli:main`.
- `__main__.py` enables `python -m virt_install_windev`.
- The Fedora/dnF install instructions in the README stay (external packages unchanged); the run command changes from `./virt-install-windev.sh` to `virt-install-windev`.

## Migration / risk

1. **Port the generators first**, unit-tested against golden files captured from the *current* bash output for all four versions. This is where correctness lives; the rest is plumbing.
2. **Port the orchestration** (deps, iso, vm, wait loop) module by module, each calling `util.run`.
3. **Manual end-to-end smoke test**: run the Python tool against a real eval ISO for one version (e.g. Win11) and confirm the VM installs identically — same serial-log progress markers, same completion, same CD-ROM cleanup.
4. **Remove** `virt-install-windev.sh` and `download-insider-iso.py` once the package is verified; update the README.
5. Risk is bounded by the golden-file equivalence: if the generators match and the orchestration calls the same external commands with the same arguments, behavior is preserved. The main residual risk is in the orchestration (argument ordering to `virt-install`/`virsh`), mitigated by keeping the exact command lines and by the smoke test.

## Open questions for the user

- Confirm the **scope** (rewrite + fold in fixes #3/#4/#6/#7 + Insider `--timeout`) vs. strict behavior preservation vs. broader design latitude.
- Confirm **packaging**: console-script entry point + drop the `.sh`, vs. keep a thin shell wrapper that execs the Python module.
- Confirm **Python version floor** (3.9).
