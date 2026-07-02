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
