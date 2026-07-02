# virt-install-windev Python Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 1563-line `virt-install-windev.sh` with a small, tested Python package that preserves user-facing behavior and folds in four open review fixes.

**Architecture:** A `src/virt_install_windev/` package of ~10 focused modules (config, deps, iso, insider, autounattend, setup_ps1, answer_iso, vm, util, cli) orchestrated by `cli.main`. Answer-file generation uses readable XML/PowerShell template strings composed by explicit Python conditionals (no `sed` marker-stripping). Golden-file snapshots captured from the current bash script prove byte-equivalence of the generated `autounattend.xml` and `setup.ps1`.

**Tech Stack:** Python 3.9+, stdlib only for core, `selenium` optional extra, `pytest` for tests, `pyproject.toml` (setuptools) with a `virt-install-windev` console-script entry point.

## Global Constraints

- Python 3.9+ floor. Use `from __future__ import annotations` in every module so dataclass/annotation typing works on 3.9.
- Core package depends on **stdlib only**. `selenium` is an optional extra (`virt-install-windev[insider]`); import it lazily inside `insider.py` so the core never requires it.
- Preserve the current CLI flags and defaults exactly: `--name` (default `windev`), `--iso`, `--win10`, `--server2016`, `--server2022`, `--insider`, `--edition` (default `Release Preview`), `--lang` (default `English (United States)`), `--vcpus` (4), `--ram` (8192), `--disk` (64), `--user` (`user`), `--password` (`pass`), `--no-wait`, `--force`, `-h/--help`. Add `--timeout` (default 300) for the Insider sign-in wait (surfaced from the helper).
- Preserve current USB-redirection behavior: only `fDisablePNPRedir=0` under `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services` (the user's review #1 fix). Do not restore the removed `fUsbRedirectionEnable`/`fUsbRedirectionUseDefaultList`.
- Keep the OVMF `starting Boot` boot-key timing and the `for %d in (D E F G H I)` drive-letter scans in the generated Windows commands **unchanged**.
- `COMPUTER_NAME` is a fixed constant `"WinDev"` (no CLI flag today).
- Generated `autounattend.xml` and `setup.ps1` must be **byte-identical** to the current bash output for each of the four versions when run with default config (enforced by golden files).
- Every task ends with `pytest` green and a commit. Commit messages: `refactor: …` or `feat: …`, end with the Co-Authored-By line.
- **XML parsing in tests uses `defusedxml.ElementTree`** (in the `[dev]` extra), never stdlib `xml.etree.ElementTree` — stdlib parsers are vulnerable to XXE/billion-laughs. Production code only *generates* XML strings and never parses, so the core package stays stdlib-only.

---

## File Structure

```
pyproject.toml                         # packaging, entry point, optional [insider] extra, pytest config
src/virt_install_windev/
  __init__.py                          # package version
  __main__.py                          # `python -m virt_install_windev` -> sys.exit(cli.main())
  util.py                              # run(), CommandError, xml_escape(), log()
  config.py                            # WinVersion, VersionParams, Config, VERSION_PARAMS, detect_win_version()
  deps.py                              # check_dependencies(config) -> list[str]
  autounattend.py                      # generate_autounattend(config) -> str + per-version fragment fns
  setup_ps1.py                         # generate_setup_ps1(config) -> str
  insider.py                           # get_insider_download_url(edition, lang, timeout) + helpers (port of download-insider-iso.py)
  iso.py                               # acquire_iso(config, cache_dir) -> Path
  answer_iso.py                        # build_answer_iso(work_dir, files) -> Path
  vm.py                                # remove_existing_vm / create_and_start_vm / send_boot_keys / wait_for_install / detach_cdroms
  cli.py                               # build_parser() + main(argv)
tests/
  conftest.py                          # shared fixtures (default Config per version, tmp cache dir)
  test_util.py
  test_config.py
  test_deps.py
  test_autounattend.py
  test_setup_ps1.py
  test_insider.py
  test_iso.py
  test_answer_iso.py
  test_vm.py
  test_cli.py
  golden/
    autounattend_11.xml
    autounattend_10.xml
    autounattend_server2016.xml
    autounattend_server2022.xml
    setup_11.ps1
    setup_10.ps1
    setup_server2016.ps1
    setup_server2022.ps1
```

The current `virt-install-windev.sh` and `download-insider-iso.py` remain in the repo until the final task, so golden files can be captured and the bash behavior is referenceable. They are deleted in the last task.

---

## Task 1: Project scaffolding and test infrastructure

**Files:**
- Create: `pyproject.toml`
- Create: `src/virt_install_windev/__init__.py`, `src/virt_install_windev/__main__.py`, `src/virt_install_windev/cli.py` (stub)
- Create: `tests/conftest.py`
- Modify: `.gitignore` (add `__pycache__/` if not present, build dirs)

**Interfaces:**
- Produces: an importable package `virt_install_windev` with `cli.main(argv: list[str] | None = None) -> int` (stub returning 0 and printing nothing yet), and `python -m virt_install_windev` working.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "virt-install-windev"
version = "0.1.0"
description = "Create a fully-unattended Windows dev VM with libvirt/QEMU/KVM"
requires-python = ">=3.9"
dependencies = []

[project.optional-dependencies]
insider = ["selenium"]
dev = ["pytest", "defusedxml"]

[project.scripts]
virt-install-windev = "virt_install_windev.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Write the package `__init__.py`**

```python
"""virt-install-windev: create a fully-unattended Windows dev VM."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Write `__main__.py`**

```python
import sys

from virt_install_windev.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write the `cli.py` stub**

```python
from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    # Real implementation arrives in a later task.
    return 0
```

- [ ] **Step 5: Write `tests/conftest.py`** with a default-config fixture per version (used by later tasks; defining it now avoids churn):

```python
from __future__ import annotations

import pytest

from virt_install_windev.config import Config, WinVersion


@pytest.fixture(params=[WinVersion.WIN11, WinVersion.WIN10,
                        WinVersion.SERVER2016, WinVersion.SERVER2022])
def config(request) -> Config:
    return Config(win_version=request.param)
```

(Note: `Config` is created in Task 3. This fixture will fail to import until then — that's fine; it is only used by tasks from Task 3 onward. If Task 1's test run collects it, conftest import errors surface. To keep Task 1 isolated, guard the import: see Step 6.)

- [ ] **Step 6: Make conftest import-tolerant until Task 3**

Replace the conftest body with a lazy fixture so Task 1's `pytest --collect-only` doesn't hard-fail on the missing `config` module:

```python
from __future__ import annotations

import pytest


@pytest.fixture(params=["win11", "win10", "server2016", "server2022"])
def config_version(request) -> str:
    return request.param
```

(Task 3 will replace this with the real `Config` fixture shown in Step 5.)

- [ ] **Step 7: Install in editable mode and verify**

Run: `pip install -e .[dev]`
Then: `python -m virt_install_windev; echo "exit=$?"`
Expected: prints nothing, `exit=0`.

Then: `pytest --collect-only`
Expected: no collection errors (zero tests collected is fine for now).

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py .gitignore
git commit -m "refactor: scaffold Python package and pytest harness

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: `util.py` — `run()`, `CommandError`, `xml_escape()`, `log()`

**Files:**
- Create: `src/virt_install_windev/util.py`
- Test: `tests/test_util.py`

**Interfaces:**
- Produces:
  - `class CommandError(Exception)` with attributes `cmd: list[str]`, `returncode: int`, `stderr: str`
  - `run(cmd: list[str], *, check: bool = True, capture: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess`
  - `xml_escape(s: str) -> str`
  - `log(msg: str, prefix: str = "") -> None`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_util.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'virt_install_windev.util'`.

- [ ] **Step 3: Write `util.py`**

```python
from __future__ import annotations

import subprocess
import sys


class CommandError(Exception):
    def __init__(self, cmd: list[str], returncode: int, stderr: str):
        super().__init__(f"command failed (exit {returncode}): {' '.join(cmd)}\n{stderr}")
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr


def run(cmd: list[str], *, check: bool = True, capture: bool = False,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run a command. If check and it exits non-zero, raise CommandError with stderr."""
    completed = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=capture,
        timeout=timeout,
    )
    if check and completed.returncode != 0:
        raise CommandError(cmd, completed.returncode,
                           (completed.stderr or "") if capture else "")
    return completed


_XML_MAP = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def xml_escape(s: str) -> str:
    """Escape XML text-content metacharacters (&, <, >)."""
    for ch, ent in _XML_MAP.items():
        s = s.replace(ch, ent)
    return s


def log(msg: str, prefix: str = "") -> None:
    """Print a progress line to stderr, mirroring the old [vm]-prefixed tail."""
    line = f"{prefix}{msg}" if prefix else msg
    print(line, file=sys.stderr, flush=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_util.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/util.py tests/test_util.py
git commit -m "refactor: add util.run/CommandError/xml_escape/log

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: `config.py` — `WinVersion`, `VersionParams`, `Config`, detection

**Files:**
- Create: `src/virt_install_windev/config.py`
- Test: `tests/test_config.py`
- Modify: `tests/conftest.py` (replace the placeholder fixture with the real `Config` fixture)

**Interfaces:**
- Produces:
  - `class WinVersion(enum.Enum)`: members `WIN10`, `WIN11`, `SERVER2016`, `SERVER2022` (values `"10"`, `"11"`, `"server2016"`, `"server2022"`)
  - `@dataclass(frozen=True) class VersionParams`: `virtio_driver_dir: str`, `os_variant: str`, `image_index: int`
  - `VERSION_PARAMS: dict[WinVersion, VersionParams]`
  - `@dataclass class Config`: fields `name="windev"`, `vcpus=4`, `ram_mb=8192`, `disk_gb=64`, `user_name="user"`, `user_password="pass"`, `computer_name="WinDev"`, `win_version: WinVersion = WinVersion.WIN11`, `iso_path: str | None = None`, `insider=False`, `insider_edition="Release Preview"`, `insider_lang="English (United States)"`, `insider_timeout=300`, `no_wait=False`, `force=False`, `cache_dir: str = "$HOME/.cache/virt-install-windev"` (resolved in cli)
  - `detect_win_version(iso_filename: str) -> WinVersion | None`

The per-version params come from the bash `case` at `virt-install-windev.sh:266-271`:
- WIN10: `w10`, `win10`, `1`
- SERVER2016: `2k16`, `win2k16`, `2`
- SERVER2022: `2k22`, `win2k22`, `2`
- WIN11 (default): `w11`, `win11`, `1`

The detection regexes come from `virt-install-windev.sh:248-263`. The bash checks Server first, then Win10, then Win11. Preserve that order exactly.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from virt_install_windev.config import (
    Config, WinVersion, VERSION_PARAMS, detect_win_version,
)


def test_detect_win11():
    assert detect_win_version("Win11_24H2_English_x64.iso") is WinVersion.WIN11


def test_detect_win10():
    assert detect_win_version("Win10_22H2_English_x64.iso") is WinVersion.WIN10


def test_detect_server2016():
    assert detect_win_version("en_windows_server_2016_x64_dvd.iso") is WinVersion.SERVER2016


def test_detect_server2022_eval():
    assert detect_win_version("SERVER_EVAL_x64FRE_en-us.iso") is WinVersion.SERVER2022


def test_detect_server2022_named():
    assert detect_win_version("Windows_Server_2022_x64.iso") is WinVersion.SERVER2022


def test_detect_unknown_returns_none():
    assert detect_win_version("foo.iso") is None


def test_version_params():
    assert VERSION_PARAMS[WinVersion.WIN10].virtio_driver_dir == "w10"
    assert VERSION_PARAMS[WinVersion.WIN10].os_variant == "win10"
    assert VERSION_PARAMS[WinVersion.WIN10].image_index == 1
    assert VERSION_PARAMS[WinVersion.SERVER2016].image_index == 2
    assert VERSION_PARAMS[WinVersion.SERVER2022].os_variant == "win2k22"
    assert VERSION_PARAMS[WinVersion.WIN11].virtio_driver_dir == "w11"


def test_config_defaults():
    c = Config()
    assert c.name == "windev"
    assert c.user_name == "user"
    assert c.user_password == "pass"
    assert c.win_version is WinVersion.WIN11
    assert c.insider is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `config.py`**

```python
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field


class WinVersion(enum.Enum):
    WIN10 = "10"
    WIN11 = "11"
    SERVER2016 = "server2016"
    SERVER2022 = "server2022"


@dataclass(frozen=True)
class VersionParams:
    virtio_driver_dir: str
    os_variant: str
    image_index: int


VERSION_PARAMS: dict[WinVersion, VersionParams] = {
    WinVersion.WIN10:        VersionParams("w10",  "win10",   1),
    WinVersion.SERVER2016:   VersionParams("2k16", "win2k16", 2),
    WinVersion.SERVER2022:   VersionParams("2k22", "win2k22", 2),
    WinVersion.WIN11:        VersionParams("w11",  "win11",   1),
}


@dataclass
class Config:
    name: str = "windev"
    vcpus: int = 4
    ram_mb: int = 8192
    disk_gb: int = 64
    user_name: str = "user"
    user_password: str = "pass"
    computer_name: str = "WinDev"
    win_version: WinVersion = WinVersion.WIN11
    iso_path: str | None = None
    insider: bool = False
    insider_edition: str = "Release Preview"
    insider_lang: str = "English (United States)"
    insider_timeout: int = 300
    no_wait: bool = False
    force: bool = False
    cache_dir: str = ""  # resolved by cli from XDG_CACHE_HOME


# Detection patterns mirror virt-install-windev.sh:250-253 (Server first, then 10, then 11).
_RE_SERVER_2016 = re.compile(r"[Ss]erver.*2016")
_RE_SERVER_2022 = re.compile(r"([Ss]erver.*2022|SERVER_EVAL)")
_RE_WIN10 = re.compile(r"[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*10")
_RE_WIN11 = re.compile(r"[Ww]in(dows)?([-_ .][A-Za-z]+)*[-_ .]*11")


def detect_win_version(iso_filename: str) -> WinVersion | None:
    if _RE_SERVER_2016.search(iso_filename):
        return WinVersion.SERVER2016
    if _RE_SERVER_2022.search(iso_filename):
        return WinVersion.SERVER2022
    if _RE_WIN10.search(iso_filename):
        return WinVersion.WIN10
    if _RE_WIN11.search(iso_filename):
        return WinVersion.WIN11
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: 8 passed.

- [ ] **Step 5: Replace the conftest placeholder with the real `Config` fixture**

Overwrite `tests/conftest.py` with:

```python
from __future__ import annotations

import pytest

from virt_install_windev.config import Config, WinVersion


@pytest.fixture(params=[WinVersion.WIN11, WinVersion.WIN10,
                        WinVersion.SERVER2016, WinVersion.SERVER2022])
def config(request) -> Config:
    return Config(win_version=request.param)
```

Run: `pytest -q`
Expected: still green (no tests use the fixture yet).

- [ ] **Step 6: Commit**

```bash
git add src/virt_install_windev/config.py tests/test_config.py tests/conftest.py
git commit -m "refactor: add Config, WinVersion, and ISO-filename detection

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Capture golden answer files from the current bash script

**Files:**
- Modify: `virt-install-windev.sh` (add a temporary `--generate-only DIR` flag)
- Create: `tests/golden/autounattend_11.xml`, `autounattend_10.xml`, `autounattend_server2016.xml`, `autounattend_server2022.xml`
- Create: `tests/golden/setup_11.ps1`, `setup_10.ps1`, `setup_server2016.ps1`, `setup_server2022.ps1`

This task produces the equivalence targets. It does not write Python. The golden files are committed and never edited by hand thereafter.

- [ ] **Step 1: Add `--generate-only` to the bash arg parser**

In `virt-install-windev.sh`, add a default near the other defaults (after `NO_WAIT=0` / `FORCE=0`, around line 72–77):

```bash
GEN_ONLY=""
```

In the `while [[ $# -gt 0 ]]` case block (around line 113–133), add:

```bash
        --generate-only) GEN_ONLY="$2"; shift 2 ;;
```

- [ ] **Step 2: Make the script exit after generation when `--generate-only` is set**

Insert this block immediately **after** the setup.ps1 marker-stripping (right after `virt-install-windev.sh:1303`, the line `sed -i '/# BEGIN_SERVER_ONLY/,/# END_SERVER_ONLY/d' ...`), and before the `echo "Generated setup.ps1"` line:

```bash
if [[ -n "$GEN_ONLY" ]]; then
    mkdir -p "$GEN_ONLY"
    cp "$WORK_DIR/autounattend.xml" "$GEN_ONLY/autounattend_${WIN_VERSION}.xml"
    cp "$WORK_DIR/setup.ps1" "$GEN_ONLY/setup_${WIN_VERSION}.ps1"
    echo "Generated answer files written to $GEN_ONLY for Windows $WIN_VERSION"
    exit 0
fi
```

At this point in the script, `autounattend.xml` has had `YOURUSER`/`YOURPASSWORD`/`VIRTIO_DRIVER_DIR`/`IMAGE_INDEX` substituted and the non-matching version markers deleted, and `setup.ps1` has had its client/server block stripped. These copied files are exactly what the Python generators must reproduce.

- [ ] **Step 3: Sanity-check the bash edit**

Run: `bash -n virt-install-windev.sh`
Expected: no output (syntax OK).

- [ ] **Step 4: Capture golden files for all four versions**

```bash
mkdir -p tests/golden
for v in --win10 "" --server2016 --server2022; do
  bash virt-install-windev.sh $v --generate-only tests/golden >/dev/null 2>&1 || true
done
ls tests/golden
```

Expected: eight files — `autounattend_{11,10,server2016,server2022}.xml` and `setup_{11,10,server2016,server2022}.ps1`. (The empty-`$v` iteration produces the Win11 files; verify all four `WIN_VERSION` values appear.)

If any version is missing, run that version explicitly, e.g. `bash virt-install-windev.sh --server2022 --generate-only tests/golden`.

- [ ] **Step 5: Verify the golden files look right**

Run: `for f in tests/golden/autounattend_*.xml; do python3 -c "import sys; from defusedxml import ElementTree as E; E.parse(sys.argv[1]); print('OK',sys.argv[1])" "$f"; done`
Expected: four `OK` lines — each golden XML is well-formed.

Spot-check that version-specific content is correct:
- `grep -L fDisablePNPRedir tests/golden/autounattend_*.xml` — every file contains the USB policy line.
- `grep -c "RDS-RD-Server" tests/golden/autounattend_server2016.xml` — ≥1 (RDSH present on Server).
- `grep -c "RDS-RD-Server" tests/golden/autounattend_11.xml` — 0 (no RDSH on Win11).
- `grep -c "NPPR9-FWDCX-D2C8J-H872K-2YT43" tests/golden/autounattend_11.xml` — 1 (Win11 GVLK).
- `grep -c "ProductKey" tests/golden/autounattend_10.xml` — 0 (Win10 has no product key).
- `grep -c "Add-WindowsCapability" tests/golden/setup_11.ps1` — 0 (Win11 OpenSSH is in autounattend FirstLogon, not setup.ps1); `grep -c "OpenSSH-Win64.zip" tests/golden/setup_10.ps1` — ≥1.

- [ ] **Step 6: Commit golden files and the bash `--generate-only` flag**

```bash
git add tests/golden virt-install-windev.sh
git commit -m "test: capture golden autounattend/setup.ps1 from bash for 4 versions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: `autounattend.py` — windowsPE pass + `user_data_for()`

**Files:**
- Create: `src/virt_install_windev/autounattend.py`
- Test: `tests/test_autounattend.py`

This task builds the first third of the generator: the `windowsPE` pass (lines `virt-install-windev.sh:282–514` of the heredoc) including the `<UserData>` product-key block, which varies by version. The `specialize` and `oobeSystem` passes are added in Tasks 6 and 7. Until then, `generate_autounattend` returns only the windowsPE section wrapped in the `<unattend>` root — **not** yet golden-comparable. The full golden comparison lands in Task 7.

**Porting rule (applies to this and the next two tasks):** Copy the XML body **verbatim** from the bash heredoc into a Python triple-quoted string, preserving exact indentation and newlines. Replace the four version-conditional `<UserData>` blocks (bash lines `476–512`) with a single `{USERDATA}` token, supplied by `user_data_for(version)`. Replace `${COMPUTER_NAME}` (bash line 547, injected by the separate heredoc) with a `YOURCOMPUTERNAME` token. Keep `YOURUSER`, `YOURPASSWORD`, `VIRTIO_DRIVER_DIR`, `IMAGE_INDEX` as literal tokens in the template; `_render()` substitutes them. Drop every `<!-- BEGIN_*_ONLY -->` / `<!-- END_*_ONLY -->` marker comment — version selection is now explicit Python.

**Interfaces:**
- Produces:
  - `user_data_for(version: WinVersion) -> str`
  - `_render(template: str, config: Config) -> str` (module-private)
  - `generate_autounattend(config: Config) -> str` (returns windowsPE-only stub for now; completed in Task 7)

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from defusedxml import ElementTree as ET

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import autounattend


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


def test_generate_windowspe_is_well_formed_and_has_drivers():
    cfg = Config(win_version=WinVersion.WIN11)
    xml = autounattend.generate_autounattend(cfg)
    ET.fromstring(xml)  # raises if malformed
    assert "Microsoft-Windows-PnpCustomizationsWinPE" in xml
    assert "E:\\NetKVM\\w11\\amd64" in xml  # VIRTIO_DRIVER_DIR substituted for Win11
    assert "BypassTPMCheck" in xml
    assert "<ComputerName>WinDev</ComputerName>" in xml


def test_generate_escapes_user_password():
    cfg = Config(win_version=WinVersion.WIN11, user_name="a&b", user_password="p<x")
    xml = autounattend.generate_autounattend(cfg)
    assert "a&amp;b" in xml
    assert "p&lt;x" in xml
    assert "a&b" not in xml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_autounattend.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `autounattend.py`**

Create the module. Structure:

```python
from __future__ import annotations

from virt_install_windev.config import Config, WinVersion, VERSION_PARAMS
from virt_install_windev.util import xml_escape

# --- version-specific fragments ---

def user_data_for(version: WinVersion) -> str:
    """The <UserData> block for the windowsPE Setup component."""
    if version is WinVersion.WIN10:
        return """      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>"""
    gvlk = {
        WinVersion.WIN11:      "NPPR9-FWDCX-D2C8J-H872K-2YT43",
        WinVersion.SERVER2016: "WC2BQ-8NRM3-FDDYY-2BFGV-KHKQY",
        WinVersion.SERVER2022: "VDYBN-27WPP-V4HQT-9VMD4-VMK7H",
    }[version]
    return f"""      <UserData>
        <AcceptEula>true</AcceptEula>
        <ProductKey>
          <Key>{gvlk}</Key>
          <WillShowUI>Never</WillShowUI>
        </ProductKey>
      </UserData>"""


def _render(template: str, config: Config) -> str:
    p = VERSION_PARAMS[config.win_version]
    return (template
            .replace("YOURUSER", xml_escape(config.user_name))
            .replace("YOURPASSWORD", xml_escape(config.user_password))
            .replace("VIRTIO_DRIVER_DIR", p.virtio_driver_dir)
            .replace("IMAGE_INDEX", str(p.image_index))
            .replace("YOURCOMPUTERNAME", xml_escape(config.computer_name))
            .replace("{USERDATA}", user_data_for(config.win_version)))
```

Then define `_WINDOWSPE_TEMPLATE` as a triple-quoted string copied **verbatim** from `virt-install-windev.sh` lines `283–513`, with these exact edits:
- Keep the `<?xml ...>` line and `<unattend ...>` opening.
- Keep the entire `<settings pass="windowsPE">` block through the end of the `<Microsoft-Windows-Setup>` component.
- In place of the four `BEGIN_*_ONLY`/`END_*_ONLY` `<UserData>` blocks (bash lines `476–512`), put the single token `{USERDATA}` (no surrounding marker comments).
- Replace the `<ComputerName>${COMPUTER_NAME}</ComputerName>` line (bash line 547) — note this line is in the **specialize** pass, not windowsPE, so it is NOT in this template; do not touch it here. (It is handled in Task 6.)

Because the ComputerName line lives in the specialize pass, this windowsPE-only stub ends at the `</settings>` that closes the windowsPE pass (bash line `514`), then `</unattend>`. For the stub, terminate the template after that `</settings>` with `</unattend>` so the XML is well-formed for Task 5's tests. (Task 6 will lift the trailing `</unattend>` and append the specialize pass.)

So the stub template ends:

```python
_WINDOWSPE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  ...
  <settings pass="windowsPE">
    ... (verbatim from bash lines 297-513, with {USERDATA} in place of the 4 UserData blocks) ...
  </settings>
</unattend>
"""


def generate_autounattend(config: Config) -> str:
    return _render(_WINDOWSPE_TEMPLATE, config)
```

**Verification of verbatim copy:** After writing, diff the template body (minus the `{USERDATA}` substitution and removed marker comments) against `tests/golden/autounattend_11.xml`'s windowsPE section. The whitespace must match exactly — golden equivalence in Task 7 depends on it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_autounattend.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/autounattend.py tests/test_autounattend.py
git commit -m "refactor: port autounattend windowsPE pass to Python

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: `autounattend.py` — specialize pass + `copy_openssh_zip_for()`

**Files:**
- Modify: `src/virt_install_windev/autounattend.py`
- Test: `tests/test_autounattend.py` (append cases)

Adds the `<settings pass="specialize">` block (bash heredoc lines `516–857`). The specialize pass contains the `<ComputerName>YOURCOMPUTERNAME</ComputerName>` line and the version-conditional "copy OpenSSH ZIP" `RunSynchronousCommand` (bash lines `823–844`, WIN10 and SERVER2016 only — two byte-identical blocks that become one shared fragment).

**Interfaces:**
- Produces (adds to module): `copy_openssh_zip_for(version: WinVersion) -> str` (returns the `<RunSynchronousCommand>` block or `""`).

- [ ] **Step 1: Write the failing test (append to `tests/test_autounattend.py`)**

```python
def test_copy_openssh_zip_win10():
    xml = autounattend.copy_openssh_zip_for(WinVersion.WIN10)
    assert "OpenSSH-Win64.zip" in xml
    assert "<Order>29</Order>" in xml


def test_copy_openssh_zip_server2016_present():
    assert "OpenSSH-Win64.zip" in autounattend.copy_openssh_zip_for(WinVersion.SERVER2016)


def test_copy_openssh_zip_win11_absent():
    assert autounattend.copy_openssh_zip_for(WinVersion.WIN11) == ""
    assert autounattend.copy_openssh_zip_for(WinVersion.SERVER2022) == ""


def test_generate_specialize_has_computer_name_and_reg_tweaks():
    cfg = Config(win_version=WinVersion.WIN11)
    xml = autounattend.generate_autounattend(cfg)
    assert "<ComputerName>WinDev</ComputerName>" in xml
    assert "BypassNRO" in xml
    assert "WinDefend" in xml  # Defender service disabled
    assert "setup.ps1" in xml


def test_generate_specialize_win10_has_openssh_zip_copy():
    cfg = Config(win_version=WinVersion.WIN10)
    xml = autounattend.generate_autounattend(cfg)
    assert "OpenSSH-Win64.zip" in xml


def test_generate_specialize_win11_no_openssh_zip_copy():
    cfg = Config(win_version=WinVersion.WIN11)
    assert "OpenSSH-Win64.zip" not in autounattend.generate_autounattend(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_autounattend.py -v`
Expected: new cases FAIL (no specialize pass yet).

- [ ] **Step 3: Add `copy_openssh_zip_for()` and the specialize template**

Add the fragment function (one shared block, replacing the two byte-identical WIN10/SERVER2016 blocks at bash lines `824–827` and `830–833`):

```python
def copy_openssh_zip_for(version: WinVersion) -> str:
    """The 'copy OpenSSH ZIP from CD' RunSynchronousCommand, Win10/Server2016 only."""
    if version not in (WinVersion.WIN10, WinVersion.SERVER2016):
        return ""
    return """        <RunSynchronousCommand wcm:action="add">
          <Order>29</Order>
          <Path>cmd /c for %d in (D E F G H I) do @if exist %d:\\OpenSSH-Win64.zip copy /y %d:\\OpenSSH-Win64.zip C:\\Windows\\Temp\\OpenSSH-Win64.zip</Path>
        </RunSynchronousCommand>"""
```

Add `_SPECIALIZE_TEMPLATE` as a triple-quoted string copied **verbatim** from bash heredoc lines `516–856` (the `<settings pass="specialize">` … `</settings>` block), with these edits:
- Replace `<ComputerName>${COMPUTER_NAME}</ComputerName>` (bash line 547) with `<ComputerName>YOURCOMPUTERNAME</ComputerName>`.
- In place of the two `BEGIN_WIN10_ONLY`/`BEGIN_SERVER2016_ONLY` "copy OpenSSH ZIP" blocks (bash lines `823–834`, including their marker comments), put the single token `{COPY_OPENSSH_ZIP}`.
- Drop every other `BEGIN_*_ONLY`/`END_*_ONLY` marker comment that appears in this range (there are none other in specialize besides the OpenSSH ones — verify by grepping the bash range).
- Keep all `<RunSynchronousCommand>` Order numbers exactly as in bash (including the gap 26 → 29 after the USB block; do **not** renumber).

Update `_render` to also substitute `{COPY_OPENSSH_ZIP}`:

```python
            .replace("{COPY_OPENSSH_ZIP}", copy_openssh_zip_for(config.win_version)))
```

Update `generate_autounattend` to concatenate the windowsPE template (with its trailing `</unattend>` removed) and the specialize template, then re-append `</unattend>`:

```python
_WINDOWSPE_BODY = _WINDOWSPE_TEMPLATE.removesuffix("</unattend>\n")
_SPECIALIZE_BODY = _SPECIALIZE_TEMPLATE  # already ends with </settings>

def generate_autounattend(config: Config) -> str:
    return _render(_WINDOWSPE_BODY + "\n" + _SPECIALIZE_BODY + "\n</unattend>\n", config)
```

Adjust the `.removesuffix`/concatenation so the final string has exactly the same newline structure as the golden file. The golden file ends with `</unattend>\n`; match that.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_autounattend.py -v`
Expected: all cases (Task 5 + Task 6) pass.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/autounattend.py tests/test_autounattend.py
git commit -m "refactor: port autounattend specialize pass to Python

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: `autounattend.py` — oobeSystem pass + fragments + golden equivalence

**Files:**
- Modify: `src/virt_install_windev/autounattend.py`
- Test: `tests/test_autounattend.py` (append golden comparison + oobe cases)

Adds the `<settings pass="oobeSystem">` block (bash heredoc lines `859–1091`). It contains the local account, auto-logon, and `FirstLogonCommands`, with three version-conditional fragments:
- `openssh_firstlogon_for(version)` — bash lines `998–1032`: WIN11 & SERVER2022 use `Add-WindowsCapability`; WIN10 & SERVER2016 just `Start-Service`. (Two distinct sub-patterns, each duplicated → two shared fragments selected by version.)
- `rdsh_firstlogon_for(version)` — bash lines `960–991`: SERVER2016 & SERVER2022 only, byte-identical → one shared fragment.
- `winget_windbg_for(version)` — bash lines `1053–1066`: WIN11 only (WinDbg + Sysinternals Suite via winget).

**Interfaces:**
- Produces (adds): `openssh_firstlogon_for(version) -> str`, `rdsh_firstlogon_for(version) -> str`, `winget_windbg_for(version) -> str`.

- [ ] **Step 1: Write the failing test (append)**

```python
import pathlib

GOLDEN = pathlib.Path(__file__).parent / "golden"


def test_openssh_firstlogon_win11_capability():
    xml = autounattend.openssh_firstlogon_for(WinVersion.WIN11)
    assert "Add-WindowsCapability" in xml
    assert "OpenSSH.Server~~~~0.0.1.0" in xml


def test_openssh_firstlogon_win10_start_service():
    xml = autounattend.openssh_firstlogon_for(WinVersion.WIN10)
    assert "Start-Service sshd" in xml
    assert "Add-WindowsCapability" not in xml


def test_rdsh_only_for_servers():
    assert "RDS-RD-Server" in autounattend.rdh_firstlogon_for(WinVersion.SERVER2016)
    assert "RDS-RD-Server" in autounattend.rdh_firstlogon_for(WinVersion.SERVER2022)
    assert autounattend.rdh_firstlogon_for(WinVersion.WIN11) == ""
    assert autounattend.rdh_firstlogon_for(WinVersion.WIN10) == ""


def test_winget_windbg_win11_only():
    assert "Microsoft.WinDbg" in autounattend.winget_windbg_for(WinVersion.WIN11)
    assert autounattend.winget_windbg_for(WinVersion.WIN10) == ""


@pytest.mark.parametrize("version,filename", [
    (WinVersion.WIN11, "autounattend_11.xml"),
    (WinVersion.WIN10, "autounattend_10.xml"),
    (WinVersion.SERVER2016, "autounattend_server2016.xml"),
    (WinVersion.SERVER2022, "autounattend_server2022.xml"),
])
def test_generate_autounattend_matches_golden(version, filename):
    cfg = Config(win_version=version)
    assert autounattend.generate_autounattend(cfg) == (GOLDEN / filename).read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_autounattend.py -v`
Expected: new cases FAIL (no oobe pass; golden comparison fails).

- [ ] **Step 3: Add the three fragment functions and the oobe template**

```python
def openssh_firstlogon_for(version: WinVersion) -> str:
    if version in (WinVersion.WIN11, WinVersion.SERVER2022):
        return """        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' -ErrorAction Continue; Set-Service -Name sshd -StartupType Automatic -ErrorAction Continue; Start-Service sshd -ErrorAction Continue; netsh advfirewall firewall add rule name='OpenSSH Server' dir=in action=allow protocol=TCP localport=22"</CommandLine>
        </SynchronousCommand>"""
    # Win10 / Server2016: OpenSSH installed from bundled ZIP during specialize.
    return """        <SynchronousCommand wcm:action="add">
          <Order>7</Order>
          <CommandLine>powershell -Command "Start-Service sshd -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>"""


def rdh_firstlogon_for(version: WinVersion) -> str:
    """RDSH role install for RDP USB redirection — Server editions only."""
    if version not in (WinVersion.SERVER2016, WinVersion.SERVER2022):
        return ""
    return """        <SynchronousCommand wcm:action="add">
          <Order>3</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing RDSH role for USB redirection &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>4</Order>
          <CommandLine>powershell -Command "Install-WindowsFeature -Name RDS-RD-Server -ErrorAction Continue"</CommandLine>
        </SynchronousCommand>"""


def winget_windbg_for(version: WinVersion) -> str:
    if version is not WinVersion.WIN11:
        return ""
    return """        <SynchronousCommand wcm:action="add">
          <Order>11</Order>
          <CommandLine>cmd /c "echo [OOBE] Installing WinDbg &gt; COM1 || exit /b 0"</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>12</Order>
          <CommandLine>cmd /c winget install Microsoft.WinDbg --accept-source-agreements --accept-package-agreements --silent</CommandLine>
        </SynchronousCommand>
        <SynchronousCommand wcm:action="add">
          <Order>13</Order>
          <CommandLine>cmd /c winget install Microsoft.Sysinternals.Suite --accept-source-agreements --accept-package-agreements --silent</CommandLine>
        </SynchronousCommand>"""
```

**Important — fragment placement and ordering in the oobe template.** The bash `FirstLogonCommands` uses fixed `Order` numbers with version-conditional blocks spliced in. The oobe template must reproduce the exact sequence for each version. Copy the oobe block **verbatim** from bash lines `859–1090` into `_OOBE_TEMPLATE`, and replace:
- The two `BEGIN_SERVER2016_ONLY`/`BEGIN_SERVER2022_ONLY` RDSH blocks (bash lines `960–991`) with `{RDSH_FIRSTLOGON}`.
- The four `BEGIN_*_ONLY` OpenSSH blocks (bash lines `998–1032`) with `{OPENSSH_FIRSTLOGON}`.
- The `BEGIN_WIN11_ONLY` winget block (bash lines `1053–1066`) with `{WINGET_WINDBG}`.
- All `YOURUSER`/`YOURPASSWORD` tokens in `<Name>`, `<Username>`, `<Value>` stay as literal tokens (rendered by `_render`).
- Drop all marker comments.

Then extend `_render` with the three new replacements, and `generate_autounattend` to append the oobe body before the final `</unattend>`.

- [ ] **Step 4: Run the golden equivalence test**

Run: `pytest tests/test_autounattend.py -k matches_golden -v`
Expected: possibly FAIL on whitespace/newline drift. If it fails:
- `diff <(python -c 'from virt_install_windev.config import Config,WinVersion; from virt_install_windev import autounattend; import sys; sys.stdout.write(autounattend.generate_autounattend(Config(win_version=WinVersion.WIN11)))') tests/golden/autounattend_11.xml`
- Fix the template's leading/trailing whitespace and newline joins until the test passes. The most common drift sources: the exact blank lines between passes, the trailing newline after `</unattend>`, and indentation of fragment lines. Match the golden file byte-for-byte.

- [ ] **Step 5: Run the full autounattend suite**

Run: `pytest tests/test_autounattend.py -v`
Expected: all cases pass, including all four golden comparisons.

- [ ] **Step 6: Commit**

```bash
git add src/virt_install_windev/autounattend.py tests/test_autounattend.py
git commit -m "refactor: port autounattend oobeSystem pass; golden equivalence for 4 versions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: `setup_ps1.py` — `generate_setup_ps1()` + golden equivalence

**Files:**
- Create: `src/virt_install_windev/setup_ps1.py`
- Test: `tests/test_setup_ps1.py`

Ports the `setup.ps1` heredoc (bash lines `1122–1297`) and its client/server marker stripping (bash lines `1270–1303`). The `BEGIN_CLIENT_ONLY`/`END_CLIENT_ONLY` block (WSL, bash lines `1259–1272`) and `BEGIN_SERVER_ONLY`/`END_SERVER_ONLY` block (Server Manager suppression, bash lines `1273–1276`) become explicit Python conditionals. `generate_setup_ps1` must be byte-identical to the golden `setup_<version>.ps1` for each version.

**Interfaces:**
- Produces: `generate_setup_ps1(config: Config) -> str`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pathlib

import pytest

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import setup_ps1

GOLDEN = pathlib.Path(__file__).parent / "golden"


def test_setup_client_has_wsl_no_server_manager():
    s = setup_ps1.generate_setup_ps1(Config(win_version=WinVersion.WIN11))
    assert "Microsoft-Windows-Subsystem-Linux" in s
    assert "ServerManager" not in s


def test_setup_server_has_server_manager_no_wsl():
    s = setup_ps1.generate_setup_ps1(Config(win_version=WinVersion.SERVER2022))
    assert "ServerManager" in s
    assert "Microsoft-Windows-Subsystem-Linux" not in s


@pytest.mark.parametrize("version,filename", [
    (WinVersion.WIN11, "setup_11.ps1"),
    (WinVersion.WIN10, "setup_10.ps1"),
    (WinVersion.SERVER2016, "setup_server2016.ps1"),
    (WinVersion.SERVER2022, "setup_server2022.ps1"),
])
def test_generate_setup_ps1_matches_golden(version, filename):
    assert setup_ps1.generate_setup_ps1(Config(win_version=version)) == (GOLDEN / filename).read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_ps1.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `setup_ps1.py`**

Copy the `setup.ps1` heredoc body **verbatim** from bash lines `1123–1296` into a template. Replace:
- The `# BEGIN_CLIENT_ONLY` … `# END_CLIENT_ONLY` block (bash lines `1259–1272`, the WSL `dism` calls) with `{CLIENT_ONLY}`.
- The `# BEGIN_SERVER_ONLY` … `# END_SERVER_ONLY` block (bash lines `1273–1276`, Server Manager suppression) with `{SERVER_ONLY}`.
- Drop the marker comment lines themselves.

```python
from __future__ import annotations

from virt_install_windev.config import Config, WinVersion

_CLIENT_ONLY = """# BEGIN_CLIENT_ONLY
# (WSL enablement — verbatim dism calls from bash lines 1230-1242)
# END_CLIENT_ONLY"""  # replace with the actual WSL block content from bash

_SERVER_ONLY = """# (Server Manager suppression — verbatim from bash lines 1244-1245)"""


def generate_setup_ps1(config: Config) -> str:
    is_server = config.win_version in (WinVersion.SERVER2016, WinVersion.SERVER2022)
    return _TEMPLATE.replace(
        "{CLIENT_ONLY}", _CLIENT_ONLY if not is_server else ""
    ).replace(
        "{SERVER_ONLY}", _SERVER_ONLY if is_server else ""
    )
```

Fill `_CLIENT_ONLY`, `_SERVER_ONLY`, and `_TEMPLATE` with the verbatim bash content (strip the `# BEGIN_*_ONLY` / `# END_*_ONLY` lines themselves, since the golden files were captured **after** marker stripping and therefore do not contain them).

- [ ] **Step 4: Run the golden equivalence test and fix drift**

Run: `pytest tests/test_setup_ps1.py -k matches_golden -v`
Expected: pass after any whitespace drift is fixed. Use the same `diff` technique as Task 7 Step 4 against `tests/golden/setup_11.ps1`.

- [ ] **Step 5: Run the full setup_ps1 suite**

Run: `pytest tests/test_setup_ps1.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/virt_install_windev/setup_ps1.py tests/test_setup_ps1.py
git commit -m "refactor: port setup.ps1 generation to Python with golden equivalence

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: `deps.py` — `check_dependencies()`

**Files:**
- Create: `src/virt_install_windev/deps.py`
- Test: `tests/test_deps.py`

Replaces bash lines `138–155`. Collects all missing dependencies (commands, the virtio-win ISO, OVMF firmware, and — for `--insider` — `selenium`) and returns human-readable messages with install hints. Fixes review #6 (python3/selenium not checked).

**Interfaces:**
- Produces: `check_dependencies(config: Config) -> list[str]` (empty list = all present). Each message is a ready-to-print string.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import deps


def test_all_present_returns_empty(monkeypatch, tmp_path):
    # All commands resolve to a no-op, required files exist.
    monkeypatch.setattr(deps, "_command_exists", lambda cmd: True)
    monkeypatch.setattr(deps, "VIRTIO_ISO", str(tmp_path / "virtio.iso"))
    monkeypatch.setattr(deps, "OVMF_CODE", str(tmp_path / "ovmf.fd"))
    (tmp_path / "virtio.iso").write_text("")
    (tmp_path / "ovmf.fd").write_text("")
    assert deps.check_dependencies(Config()) == []


def test_missing_command_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "_command_exists",
                        lambda cmd: cmd != "genisoimage")
    monkeypatch.setattr(deps, "VIRTIO_ISO", str(tmp_path / "virtio.iso"))
    monkeypatch.setattr(deps, "OVMF_CODE", str(tmp_path / "ovmf.fd"))
    (tmp_path / "virtio.iso").write_text("")
    (tmp_path / "ovmf.fd").write_text("")
    msgs = deps.check_dependencies(Config())
    assert any("genisoimage" in m for m in msgs)


def test_missing_selenium_for_insider(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "_command_exists", lambda cmd: True)
    monkeypatch.setattr(deps, "VIRTIO_ISO", str(tmp_path / "virtio.iso"))
    monkeypatch.setattr(deps, "OVMF_CODE", str(tmp_path / "ovmf.fd"))
    (tmp_path / "virtio.iso").write_text("")
    (tmp_path / "ovmf.fd").write_text("")
    monkeypatch.setattr(deps, "_selenium_available", lambda: False)
    msgs = deps.check_dependencies(Config(insider=True))
    assert any("selenium" in m.lower() for m in msgs)


def test_missing_virtio_iso_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(deps, "_command_exists", lambda cmd: True)
    monkeypatch.setattr(deps, "VIRTIO_ISO", str(tmp_path / "missing.iso"))
    monkeypatch.setattr(deps, "OVMF_CODE", str(tmp_path / "ovmf.fd"))
    (tmp_path / "ovmf.fd").write_text("")
    msgs = deps.check_dependencies(Config())
    assert any("virtio-win" in m for m in msgs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deps.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `deps.py`**

```python
from __future__ import annotations

import shutil
from typing import Callable

from virt_install_windev.config import Config

VIRTIO_ISO = "/usr/share/virtio-win/virtio-win.iso"
OVMF_CODE = "/usr/share/OVMF/OVMF_CODE.secboot.fd"

_REQUIRED_COMMANDS = ["virt-install", "virsh", "qemu-img", "genisoimage", "curl", "swtpm"]


def _command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _selenium_available() -> bool:
    try:
        import selenium  # noqa: F401
    except ImportError:
        return False
    return True


def check_dependencies(config: Config) -> list[str]:
    missing: list[str] = []
    absent = [c for c in _REQUIRED_COMMANDS if not _command_exists(c)]
    if absent:
        missing.append("Missing required commands: " + ", ".join(absent))
    if not __import__("os").path.exists(VIRTIO_ISO):
        missing.append(f"virtio-win ISO not found at {VIRTIO_ISO} "
                       f"(install with: sudo dnf install virtio-win)")
    if not __import__("os").path.exists(OVMF_CODE):
        missing.append(f"OVMF firmware not found at {OVMF_CODE} "
                       f"(install with: sudo dnf install edk2-ovmf)")
    if config.insider and not _selenium_available():
        missing.append("selenium is required for --insider "
                       "(install with: pip install virt-install-windev[insider])")
    return missing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deps.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/deps.py tests/test_deps.py
git commit -m "refactor: add dependency checks incl. selenium for --insider

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: `insider.py` — port `download-insider-iso.py`

**Files:**
- Create: `src/virt_install_windev/insider.py`
- Delete: `download-insider-iso.py` (defer deletion to Task 14; keep for reference until then)
- Test: `tests/test_insider.py`

Ports the Selenium helper into `get_insider_download_url(edition, lang, timeout) -> str`, raising `InsiderError` on failure. The Selenium driver logic is hard to unit-test without a browser; test only the pure helper `find_option_by_substring` and the error type. Import `selenium` lazily so the core package never requires it.

**Interfaces:**
- Produces:
  - `class InsiderError(Exception)`
  - `find_option_by_substring(options: list[dict], substring: str) -> dict | None`
  - `get_insider_download_url(edition: str, lang: str, timeout: int = 300) -> str`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest

from virt_install_windev import insider


def test_find_option_by_substring_match():
    opts = [{"index": 0, "value": "null", "text": "Select..."},
            {"index": 1, "value": "rp", "text": "Release Preview"}]
    assert insider.find_option_by_substring(opts, "release preview") == opts[1]


def test_find_option_by_substring_no_match():
    opts = [{"index": 0, "value": "null", "text": "Select..."}]
    assert insider.find_option_by_substring(opts, "beta") is None


def test_insider_error_is_exception():
    assert issubclass(insider.InsiderError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_insider.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `insider.py`**

Port `download-insider-iso.py` (218 lines). Keep `URL`, `js_get_options`, `make_select_interactable`, `find_option_by_substring` as module functions unchanged. Convert `main()` into `get_insider_download_url(edition, lang, timeout=300) -> str` that returns the URL string on success and raises `InsiderError(message)` on any failure (replacing `print(..., file=sys.stderr); return 1`). Move the `from selenium import ...` imports **inside** the function so importing `insider.py` never requires selenium.

```python
from __future__ import annotations

import time

URL = "https://www.microsoft.com/en-us/software-download/windowsinsiderpreviewiso"


class InsiderError(Exception):
    pass


def js_get_options(driver, select_id):
    # verbatim from download-insider-iso.py:22-32
    ...


def make_select_interactable(driver, select_id):
    # verbatim from download-insider-iso.py:35-54
    ...


def find_option_by_substring(options, substring):
    # verbatim from download-insider-iso.py:57-62
    substring_lower = substring.lower()
    for opt in options:
        if opt["value"] and opt["value"] != "null" and substring_lower in opt["text"].lower():
            return opt
    return None


def get_insider_download_url(edition: str, lang: str, timeout: int = 300) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    # ... body of download-insider-iso.py main(), adapted:
    #   - use `edition`, `lang`, `timeout` params
    #   - on the "no edition matching" / "no language matching" / "empty href" paths,
    #     raise InsiderError(<message>) instead of printing + return 1
    #   - on the broad `except Exception as e:` path, raise InsiderError(str(e))
    #     (keep the diagnostic button/link listing in the error message)
    #   - return the URL string on success
    #   - driver.quit() in a finally block
    ...
```

Copy the body verbatim from `download-insider-iso.py:95-214`, applying only the `raise InsiderError` / `return url` changes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_insider.py -v`
Expected: 3 passed (selenium not imported by these tests).

Also verify lazy import: `python -c "import virt_install_windev.insider; print('ok')"` — must succeed with selenium uninstalled in the core env.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/insider.py tests/test_insider.py
git commit -m "refactor: port Insider ISO Selenium helper into the package

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: `iso.py` — `acquire_iso()` with caching + `curl --fail` + resume

**Files:**
- Create: `src/virt_install_windev/iso.py`
- Test: `tests/test_iso.py`

Replaces bash lines `172–244`. Three acquisition paths (provided `--iso`, Insider, eval download). Caches under `cache_dir`; Insider cache filename is version-specific (fix #7). Downloads use `curl --fail -L -C -` (fix #3: fail on 404; `-C -` resumes).

**Interfaces:**
- Produces: `acquire_iso(config: Config, cache_dir: pathlib.Path) -> pathlib.Path`.
- Consumes: `insider.get_insider_download_url` (for the Insider path).

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pathlib

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import iso


def test_provided_iso_returned_directly(tmp_path):
    p = tmp_path / "my.iso"
    p.write_text("")
    cfg = Config(iso_path=str(p))
    assert iso.acquire_iso(cfg, tmp_path) == p


def test_eval_iso_cached_not_redownloaded(monkeypatch, tmp_path):
    cached = tmp_path / "win11-enterprise-eval.iso"
    cached.write_text("data")
    calls = []
    monkeypatch.setattr(iso, "_download", lambda url, dest: calls.append((url, dest)))
    cfg = Config()
    assert iso.acquire_iso(cfg, tmp_path) == cached
    assert calls == []  # no download


def test_insider_cache_filename_is_version_specific(monkeypatch, tmp_path):
    captured = {}
    def fake_get_url(edition, lang, timeout):
        return "https://example.com/win10.iso"
    def fake_download(url, dest):
        pathlib.Path(dest).write_text("x")
        captured["dest"] = dest
    monkeypatch.setattr(iso.insider, "get_insider_download_url", fake_get_url)
    monkeypatch.setattr(iso, "_download", fake_download)
    cfg = Config(insider=True, win_version=WinVersion.WIN10)
    result = iso.acquire_iso(cfg, tmp_path)
    assert result.name == "win10-insider.iso"
    # And Win11 would use a different name:
    cfg11 = Config(insider=True, win_version=WinVersion.WIN11)
    pathlib.Path(tmp_path / "win10-insider.iso").unlink()
    r11 = iso.acquire_iso(cfg11, tmp_path)
    assert r11.name == "win11-insider.iso"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_iso.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `iso.py`**

```python
from __future__ import annotations

import os
import pathlib

from virt_install_windev import insider
from virt_install_windev.config import Config, WinVersion
from virt_install_windev.util import CommandError, log, run

EVAL_URL = "https://go.microsoft.com/fwlink/?linkid=2334167&clcid=0x409&culture=en-us&country=us"

_INSIDER_NAMES = {
    WinVersion.WIN10: "win10-insider.iso",
    WinVersion.WIN11: "win11-insider.iso",
    WinVersion.SERVER2016: "server2016-insider.iso",
    WinVersion.SERVER2022: "server2022-insider.iso",
}


def _download(url: str, dest: pathlib.Path) -> None:
    """Download url to dest with curl --fail -L -C - (fail on 404, resume)."""
    part = dest.with_suffix(dest.suffix + ".part")
    run(["curl", "--fail", "-L", "-C", "-", "-o", str(part), "--progress-bar", url])
    part.replace(dest)


def acquire_iso(config: Config, cache_dir: pathlib.Path) -> pathlib.Path:
    if config.iso_path:
        p = pathlib.Path(config.iso_path)
        if not p.is_file():
            raise FileNotFoundError(f"ISO not found at {p}")
        log(f"Using provided ISO: {p}")
        return p

    if config.insider:
        name = _INSIDER_NAMES[config.win_version]
        dest = cache_dir / name
        if dest.is_file():
            log(f"Insider ISO already cached: {dest}")
            return dest
        log("Launching browser to download Windows Insider Preview ISO...")
        url = insider.get_insider_download_url(
            config.insider_edition, config.insider_lang, config.insider_timeout)
        log(f"Downloading: {url}")
        _download(url, dest)
        log(f"ISO saved to: {dest}")
        return dest

    # Eval download (Win11 default).
    dest = cache_dir / "win11-enterprise-eval.iso"
    if dest.is_file():
        log(f"ISO already cached: {dest}")
        return dest
    log("Downloading Windows 11 Enterprise Evaluation ISO...")
    _download(EVAL_URL, dest)
    log(f"ISO saved to: {dest}")
    return dest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_iso.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/virt_install_windev/iso.py tests/test_iso.py
git commit -m "refactor: add ISO acquisition with cache, --fail, resume, version-specific insider name

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: `answer_iso.py` and `vm.py`

**Files:**
- Create: `src/virt_install_windev/answer_iso.py`
- Create: `src/virt_install_windev/vm.py`
- Test: `tests/test_answer_iso.py`, `tests/test_vm.py`

`answer_iso.build_answer_iso` wraps `genisoimage` (bash lines `1302–1314`). `vm.py` wraps all `virsh`/`virt-install` interaction (bash lines `1381–1498`): `remove_existing_vm`, `create_and_start_vm`, `send_boot_keys`, `wait_for_install` (with the non-fatal restart fix #4), `detach_cdroms`. Tests mock `util.run` to assert exact command construction and the non-fatal-restart behavior.

**Interfaces:**
- Produces:
  - `build_answer_iso(work_dir: pathlib.Path, files: list[pathlib.Path], out_path: pathlib.Path) -> pathlib.Path`
  - `remove_existing_vm(config: Config) -> None` (destroys/undefines only if `--force`; else raises if VM exists)
  - `create_and_start_vm(config: Config, disk_path: pathlib.Path, win_iso: pathlib.Path, unattend_iso: pathlib.Path, install_log: pathlib.Path) -> None`
  - `send_boot_keys(config: Config, install_log: pathlib.Path) -> None`
  - `wait_for_install(config: Config, install_log: pathlib.Path) -> None`
  - `detach_cdroms(config: Config) -> None`
- Consumes: `util.run`, `util.CommandError`, `util.log`.

- [ ] **Step 1: Write the failing `test_answer_iso.py`**

```python
from __future__ import annotations

import pathlib

from virt_install_windev import answer_iso


def test_build_answer_iso_invokes_genisoimage(monkeypatch, tmp_path):
    captured = {}
    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return None
    monkeypatch.setattr(answer_iso, "run", fake_run)
    files = [tmp_path / "a.xml", tmp_path / "b.ps1"]
    for f in files:
        f.write_text("")
    out = tmp_path / "out.iso"
    answer_iso.build_answer_iso(tmp_path, files, out)
    assert captured["cmd"][0] == "genisoimage"
    assert "-quiet" in captured["cmd"]
    assert "-J" in captured["cmd"] and "-r" in captured["cmd"]
    assert str(out) in captured["cmd"]
    for f in files:
        assert str(f) in captured["cmd"]
```

- [ ] **Step 2: Write the failing `test_vm.py`**

```python
from __future__ import annotations

import pathlib

from virt_install_windev.config import Config, WinVersion
from virt_install_windev import vm


def test_create_and_start_vm_command(monkeypatch, tmp_path):
    captured = {}
    def fake_run(cmd, **kw):
        captured.setdefault("cmds", []).append(cmd)
        return None
    monkeypatch.setattr(vm, "run", fake_run)
    cfg = Config(win_version=WinVersion.WIN11)
    vm.create_and_start_vm(cfg, tmp_path / "d.qcow2", tmp_path / "win.iso",
                           tmp_path / "unattend.iso", tmp_path / "install.log")
    cmd = captured["cmds"][0]
    assert cmd[0] == "virt-install"
    assert "--name" in cmd and "windev" in cmd
    assert "--os-variant" in cmd and "win11" in cmd
    assert "--boot" in cmd and "uefi" in cmd
    assert "--vsock" in cmd and "cid.auto=yes" in cmd
    assert "vmcoreinfo=on" in cmd


def test_wait_for_install_nonfatal_restart(monkeypatch, tmp_path):
    """A failing `virsh start` must NOT abort; it logs and breaks (fix #4)."""
    log = pathlib.Path(tmp_path / "install.log")
    log.write_text("INSTALLATION_COMPLETE\n")
    states = iter(["shut off", "running", "shut off"])  # first shut off without marker
    def fake_domstate(cfg):
        try:
            return next(states)
        except StopIteration:
            return "shut off"
    def fake_run(cmd, **kw):
        if cmd[:2] == ["virsh", "start"]:
            raise vm.CommandError(cmd, 1, "libvirt down")
        return None
    monkeypatch.setattr(vm, "domstate", fake_domstate)
    monkeypatch.setattr(vm, "run", fake_run)
    monkeypatch.setattr(vm, "log", lambda *a, **k: None)
    # Should complete without raising despite the virsh start failure.
    vm.wait_for_install(Config(), log)


def test_detach_cdroms_parses_details(monkeypatch):
    cmds = []
    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if "domblklist" in cmd:
            return type("R", (), {"stdout": "file cdrom sda /x\nfile cdrom sdb /y\n"})()
        return None
    monkeypatch.setattr(vm, "run", fake_run)
    vm.detach_cdroms(Config())
    detach = [c for c in cmds if c[:2] == ["virsh", "detach-disk"]]
    assert len(detach) == 2
    assert all("--config" in c for c in detach)
    assert {"sda", "sdb"} == {c[3] for c in detach}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_answer_iso.py tests/test_vm.py -v`
Expected: FAIL — modules not found.

- [ ] **Step 4: Write `answer_iso.py`**

```python
from __future__ import annotations

import pathlib

from virt_install_windev.util import run


def build_answer_iso(work_dir: pathlib.Path, files: list[pathlib.Path],
                     out_path: pathlib.Path) -> pathlib.Path:
    cmd = ["genisoimage", "-quiet", "-o", str(out_path), "-J", "-r"] + [str(f) for f in files]
    run(cmd)
    return out_path
```

- [ ] **Step 5: Write `vm.py`**

Port the exact `virt-install` command from bash lines `1381–1402` (preserve every flag and value, including `--vsock cid.auto=yes` and `--features vmcoreinfo=on`). Port the boot-key subshell (bash lines `1415–1427`), the completion loop (bash lines `1445–1498`, with the non-fatal restart), and the CD-ROM detach (bash lines `1495–1497`). Use `util.run` and `util.log`.

```python
from __future__ import annotations

import pathlib
import time

from virt_install_windev.config import Config, VERSION_PARAMS
from virt_install_windev.util import CommandError, log, run

INSTALL_COMPLETE = "INSTALLATION_COMPLETE"
MAX_BOOTS = 5


def domstate(config: Config) -> str:
    r = run(["virsh", "domstate", config.name], check=False, capture=True)
    return r.stdout.strip()


def remove_existing_vm(config: Config) -> None:
    r = run(["virsh", "dominfo", config.name], check=False, capture=True)
    if r.returncode != 0:
        return  # VM does not exist
    if not config.force:
        raise SystemExit(
            f"VM '{config.name}' already exists. Remove it or use --force.")
    log(f"Removing existing VM '{config.name}'...")
    run(["virsh", "destroy", config.name], check=False)
    run(["virsh", "undefine", config.name, "--nvram", "--tpm"], check=False)
    # caller removes the disk image


def create_and_start_vm(config, disk_path, win_iso, unattend_iso, install_log):
    p = VERSION_PARAMS[config.win_version]
    cmd = [
        "virt-install",
        "--name", config.name,
        "--memory", str(config.ram_mb),
        "--vcpus", str(config.vcpus),
        "--os-variant", p.os_variant,
        "--boot", "uefi,cdrom,hd",
        "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-crb",
        "--disk", f"path={disk_path},format=qcow2,bus=virtio,cache=writeback",
        "--cdrom", str(win_iso),
        "--disk", f"{VIRTIO_ISO_PLACEHOLDER},device=cdrom,bus=sata",  # see note
        "--disk", f"{unattend_iso},device=cdrom,bus=sata",
        "--network", "bridge=virbr0,model=virtio",
        "--graphics", "spice,listen=none",
        "--video", "qxl",
        "--channel", "spicevmc",
        "--channel", "unix,target.type=virtio,target.name=org.qemu.guest_agent.0",
        "--sound", "default",
        "--serial", f"file,path={install_log}",
        "--controller", "type=scsi,model=virtio-scsi",
        "--vsock", "cid.auto=yes",
        "--features", "vmcoreinfo=on",
        "--noautoconsole",
    ]
    run(cmd)
```

**Note:** the virtio-win ISO path comes from `deps.VIRTIO_ISO` (`/usr/share/virtio-win/virtio-win.iso`). Import it: `from virt_install_windev.deps import VIRTIO_ISO` and use `f"--disk", f"{VIRTIO_ISO},device=cdrom,bus=sata"` (two separate list elements). The placeholder above is illustrative — write the real two-element form.

Then `send_boot_keys` (port bash lines 1415–1427 using `time.sleep` and `run(["virsh","send-key",config.name,"KEY_ENTER"], check=False)`), `wait_for_install` (port the loop; on `virsh start` failure catch `CommandError`, log, and `break` — fix #4), and `detach_cdroms`:

```python
def detach_cdroms(config: Config) -> None:
    r = run(["virsh", "domblklist", config.name, "--details"], check=False, capture=True)
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "cdrom":
            run(["virsh", "detach-disk", config.name, parts[2], "--config"], check=False)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_answer_iso.py tests/test_vm.py -v`
Expected: all pass. (The `wait_for_install` non-fatal test confirms fix #4: a `virsh start` failure does not propagate.)

- [ ] **Step 7: Commit**

```bash
git add src/virt_install_windev/answer_iso.py src/virt_install_windev/vm.py tests/test_answer_iso.py tests/test_vm.py
git commit -m "refactor: add answer-ISO build and libvirt VM ops with non-fatal restart

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13: `cli.py` — argparse + orchestration `main()`

**Files:**
- Modify: `src/virt_install_windev/cli.py`
- Test: `tests/test_cli.py`

Wires everything together: parse args → `Config` → `check_dependencies` → resolve `cache_dir` → `remove_existing_vm` → `acquire_iso` → detect version (if not forced) → generate autounattend + setup.ps1 → collect SSH keys → download OpenSSH ZIP (Win10/Server2016, with `--fail`) → build answer ISO → create disk → `create_and_start_vm` → `send_boot_keys` → `wait_for_install` → `detach_cdroms` → print connection help. Mirrors bash lines `157–1534`.

**Interfaces:**
- Produces: `build_parser() -> argparse.ArgumentParser`, `main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from virt_install_windev import cli


def test_help_exits_zero(capsys):
    try:
        cli.main(["--help"])
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "--insider" in out
    assert "--timeout" in out


def test_unknown_option_exits_nonzero(capsys):
    try:
        cli.main(["--bogus"])
    except SystemExit as e:
        assert e.code != 0


def test_version_flags_set_win_version():
    p = cli.build_parser()
    for flag, expected in [("--win10", "10"), ("--server2016", "server2016"),
                           ("--server2022", "server2022")]:
        ns = p.parse_args([flag])
        assert ns.win_version == expected


def test_defaults():
    ns = cli.build_parser().parse_args([])
    assert ns.name == "windev"
    assert ns.user == "user"
    assert ns.password == "pass"
    assert ns.timeout == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL (stub `main` ignores args; `build_parser` missing).

- [ ] **Step 3: Write `cli.py`**

```python
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import tempfile

from virt_install_windev import (
    answer_iso, autounattend, deps, iso, setup_ps1, vm, util,
)
from virt_install_windev.config import Config, WinVersion, detect_win_version


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="virt-install-windev",
        description="Create a fully-unattended Windows dev VM with libvirt/QEMU/KVM.")
    p.add_argument("--name", default="windev")
    p.add_argument("--iso", dest="iso_path", default=None)
    ver = p.add_mutually_exclusive_group()
    ver.add_argument("--win10", dest="win_version", action="store_const",
                     const="10")
    ver.add_argument("--server2016", dest="win_version", action="store_const",
                     const="server2016")
    ver.add_argument("--server2022", dest="win_version", action="store_const",
                     const="server2022")
    p.add_argument("--insider", action="store_true")
    p.add_argument("--edition", default="Release Preview")
    p.add_argument("--lang", default="English (United States)")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--vcpus", type=int, default=4)
    p.add_argument("--ram", type=int, default=8192)
    p.add_argument("--disk", type=int, default=64)
    p.add_argument("--user", default="user")
    p.add_argument("--password", default="pass")
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(win_version=None)
    return p


_VERSION_MAP = {"10": WinVersion.WIN10, "server2016": WinVersion.SERVER2016,
                "server2022": WinVersion.SERVER2022}


def _config_from_args(ns) -> Config:
    win_version = _VERSION_MAP.get(ns.win_version) if ns.win_version else WinVersion.WIN11
    cache = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Config(
        name=ns.name, vcpus=ns.vcpus, ram_mb=ns.ram, disk_gb=ns.disk,
        user_name=ns.user, user_password=ns.password,
        iso_path=ns.iso_path, insider=ns.insider,
        insider_edition=ns.edition, insider_lang=ns.lang,
        insider_timeout=ns.timeout, no_wait=ns.no_wait, force=ns.force,
        cache_dir=os.path.join(cache, "virt-install-windev"),
    )


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    cfg = _config_from_args(ns)

    missing = deps.check_dependencies(cfg)
    if missing:
        for m in missing:
            print(f"Error: {m}", file=__import__("sys").stderr)
        return 1

    cache_dir = pathlib.Path(cfg.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Existing-VM handling (only relevant once we have a name; checks virsh).
    try:
        vm.remove_existing_vm(cfg)
    except SystemExit as e:
        print(str(e), file=__import__("sys").stderr)
        return 1

    win_iso = iso.acquire_iso(cfg, cache_dir)

    # Auto-detect version from the ISO filename if not pinned by a flag.
    if ns.win_version is None and not cfg.insider:
        detected = detect_win_version(pathlib.Path(win_iso).name)
        if detected is not None:
            cfg = _config_from_args(ns)  # rebuild
            cfg.win_version = detected
    # (Insider + no flag defaults to WIN11, matching bash.)

    work_dir = pathlib.Path(tempfile.mkdtemp(prefix="windev-setup.", dir=str(cache_dir)))
    try:
        unattend_xml = autounattend.generate_autounattend(cfg)
        (work_dir / "autounattend.xml").write_text(unattend_xml)
        setup = setup_ps1.generate_setup_ps1(cfg)
        (work_dir / "setup.ps1").write_text(setup)

        files = [work_dir / "autounattend.xml", work_dir / "setup.ps1"]

        # SSH keys
        ssh_keys = work_dir / "authorized_keys"
        if _collect_ssh_keys(ssh_keys):
            files.append(ssh_keys)

        # Win32-OpenSSH for Win10 / Server2016 (curl --fail, fix #3)
        if cfg.win_version in (WinVersion.WIN10, WinVersion.SERVER2016):
            z = work_dir / "OpenSSH-Win64.zip"
            if _download_openssh_zip(z):
                files.append(z)

        unattend_iso = cache_dir / f"{cfg.name}-autounattend.iso"
        answer_iso.build_answer_iso(work_dir, files, unattend_iso)

        disk_path = cache_dir / f"{cfg.name}.qcow2"
        if disk_path.exists() and not cfg.force:
            print(f"Disk image already exists: {disk_path}", file=__import__("sys").stderr)
            return 1
        if disk_path.exists():
            disk_path.unlink()
        util.run(["qemu-img", "create", "-f", "qcow2", str(disk_path), f"{cfg.disk_gb}G"])

        install_log = cache_dir / f"{cfg.name}-install.log"
        install_log.write_text("")

        vm.create_and_start_vm(cfg, disk_path, win_iso, unattend_iso, install_log)
        vm.send_boot_keys(cfg, install_log)

        if not cfg.no_wait:
            vm.wait_for_install(cfg, install_log)
            vm.detach_cdroms(cfg)

        _print_success(cfg, install_log)
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _collect_ssh_keys(dest: pathlib.Path) -> bool:
    home = pathlib.Path.home() / ".ssh"
    pubs = list(home.glob("id_*.pub"))
    if not pubs:
        return False
    dest.write_text("".join(p.read_text() for p in pubs))
    print(f"Bundled {len(pubs)} SSH public key(s)")
    return True


def _download_openssh_zip(dest: pathlib.Path) -> bool:
    url = "https://github.com/PowerShell/Win32-OpenSSH/releases/latest/download/OpenSSH-Win64.zip"
    try:
        util.run(["curl", "--fail", "-sL", "-o", str(dest), url])
    except util.CommandError:
        print("Warning: failed to download Win32-OpenSSH, SSH may not work",
              file=__import__("sys").stderr)
        return False
    return dest.exists() and dest.stat().st_size > 0


def _print_success(cfg, install_log):
    # Port the bash success block (lines 1503-1534): virt-viewer, domifaddr,
    # ssh, xfreerdp, management hints, install log path.
    ...
```

Port `_print_success` verbatim in spirit from bash lines `1503–1534` (use `cfg.user_name`/`cfg.user_password`/`cfg.name`; for server versions print the extra `/usb:auto` line).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/virt_install_windev/cli.py tests/test_cli.py
git commit -m "refactor: wire CLI orchestration (argparse + main flow)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 14: README update, remove bash scripts, manual smoke check

**Files:**
- Modify: `README.md`
- Delete: `virt-install-windev.sh`, `download-insider-iso.py`
- Modify: `virt-install-windev.sh` — already carries the `--generate-only` flag from Task 4; the whole file is deleted here.

- [ ] **Step 1: Update README invocation**

In `README.md`, replace `./virt-install-windev.sh` with `virt-install-windev` throughout (Quick start, Usage examples, Server section, Troubleshooting). Add a short "Install" section:

```bash
pip install .            # core
pip install .[insider]   # adds --insider Selenium support
```

Keep the `sudo dnf install …` external-package line unchanged. Update the Options block to include `--timeout` and the corrected default `--user` (`user`) / `--password` (`pass`) to match the actual code.

- [ ] **Step 2: Delete the bash scripts**

```bash
git rm virt-install-windev.sh download-insider-iso.py
```

- [ ] **Step 3: Verify the package still works end-to-end on the help path**

Run: `pip install -e .[dev] && virt-install-windev --help`
Expected: the help text prints, exit 0.

Run: `pytest -q`
Expected: all green (golden-file tests still pass — they no longer depend on the bash script).

- [ ] **Step 4: Manual smoke check (documented, run if a libvirt host is available)**

If a libvirt/QEMU host is available, run a real eval-ISO install for one version and confirm:
- The serial log shows the same `[SPECIALIZE]` / `[OOBE]` / `INSTALLATION_COMPLETE` markers.
- The VM reaches shut-off after completion and the CD-ROMs are detached (`virsh domblklist <name>` shows no cdroms).
- `virsh start <name>` then `xfreerdp /v:<IP> /u:user /p:pass` logs in.

If no host is available, note this in the commit message and rely on the golden-file equivalence plus the mocked `vm`/`iso` tests.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "refactor: finalize Python rewrite; update README, remove bash scripts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review notes

- **Spec coverage:** packaging (T1), util (T2), config/detection (T3), golden capture (T4), autounattend windowsPE/specialize/oobe (T5–T7), setup.ps1 (T8), deps incl. selenium #6 (T9), insider port + `--timeout` (T10), iso with `--fail`/resume/version-specific cache #3/#7 (T11), answer_iso + vm incl. non-fatal restart #4 (T12), cli orchestration (T13), README + cleanup (T14). All four folded fixes (#3,#4,#6,#7) and the `--timeout` surfacing are covered. USB behavior preserved (no task restores removed keys).
- **Placeholder scan:** the `...` bodies in `insider.get_insider_download_url`, `_print_success`, and the autounattend/setup templates are intentional "copy verbatim from bash lines X–Y" instructions with exact line ranges — not placeholders; the engineer lifts the real content. `VIRTIO_ISO_PLACEHOLDER` in T12 is explicitly called out as illustrative with the real form given.
- **Type consistency:** `Config`, `WinVersion`, `VERSION_PARAMS`, `generate_autounattend`, `generate_setup_ps1`, `check_dependencies`, `acquire_iso`, `build_answer_iso`, `get_insider_download_url`, `InsiderError`, `CommandError`, `run`, `xml_escape` signatures are consistent across tasks. `vm.rdh_firstlogon_for` is the name used in tests (T7) — ensure the function is defined with exactly that name (not `rdsh_firstlogon_for`); the spec prose says "rdsh" but the test uses `rdh_firstlogon_for` — **use `rdsh_firstlogon_for` everywhere and fix the T7 test to match** (see correction below).

**Correction to apply in Task 7:** name the function `rdsh_firstlogon_for` (matches the RDSH role) and update the T7 test references from `rdh_firstlogon_for` to `rdsh_firstlogon_for`. The `{RDSH_FIRSTLOGON}` template token stays.
