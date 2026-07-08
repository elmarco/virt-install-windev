from __future__ import annotations

import subprocess


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


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return f"{n} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
