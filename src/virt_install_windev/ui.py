from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from virt_install_windev.util import format_bytes

if TYPE_CHECKING:
    from virt_install_windev.config import Config

console = Console(stderr=True)

_DISK_PROGRESS = "__disk_progress__"


def log(msg: str = "") -> None:
    console.print(msg)


def warn(what: str, hint: str) -> None:
    console.print(f"[yellow]Warning:[/yellow] {what}")
    console.print(f"  Fix: {hint}")


def error(what: str, hint: str | None = None) -> None:
    console.print(f"[red]Error:[/red] {what}")
    if hint:
        console.print(f"  Fix: {hint}")


def print_vm_info(config: Config) -> None:
    from virt_install_windev.config import VERSION_PARAMS

    tbl = Table(show_header=False, box=None, padding=(0, 1))
    tbl.add_column(style="bold")
    tbl.add_column()
    tbl.add_row("Windows", config.win_version.value)
    tbl.add_row("vCPUs", str(config.vcpus))
    tbl.add_row("RAM", f"{config.ram_mb} MiB")
    tbl.add_row("Disk", f"{config.disk_gb} GiB")
    tbl.add_row("User", config.user_name)

    virtio_iso = config.virtio_iso.resolve()
    params = VERSION_PARAMS[config.win_version]
    drivers = ["NetKVM", "viostor", "vioscsi", "qxldod",
               "Balloon", "vioserial", "viorng"]
    tbl.add_row("VirtIO ISO", str(virtio_iso))
    tbl.add_row("VirtIO drivers",
                f"{', '.join(drivers)} ({params.virtio_driver_dir}/amd64)")

    console.print()
    console.print(Panel(tbl, title=f"Creating VM [bold]'{config.name}'[/bold]",
                        border_style="blue", expand=False))
    console.print()


class StepTracker:

    def __init__(
        self,
        steps: list[tuple[str, str]],
        disk_total: int | None = None,
    ) -> None:
        self._steps = steps
        self._disk_total = disk_total
        self._done: set[str] = set()
        self._disk_written: int | None = None
        self._warnings: list[str] = []
        self._live: Live | None = None

    def start(self) -> None:
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            transient=False,
        )
        self._live.start()

    def update(
        self,
        done: set[str],
        disk_written: int | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self._done = done
        self._disk_written = disk_written
        if warnings is not None:
            self._warnings = warnings
        if self._live:
            self._live.update(self._render())

    def finish(self) -> None:
        if self._live:
            self._live.update(self._render())
            self._live.stop()
            self._live = None

    def _render(self) -> Panel:
        tbl = Table(show_header=False, box=None, padding=(0, 1),
                    show_edge=False)
        tbl.add_column(width=2, justify="right")
        tbl.add_column()

        for w in self._warnings:
            tbl.add_row("", Text(w, style="yellow"))

        found_active = False
        for marker, label in self._steps:
            is_done = marker in self._done
            if is_done:
                tbl.add_row("[green]✔[/green]", f"[green]{label}[/green]")
            elif not found_active:
                found_active = True
                if marker == _DISK_PROGRESS and self._disk_written is not None:
                    suffix = self._format_disk()
                    tbl.add_row("[cyan]●[/cyan]",
                                f"[bold]{label}[/bold]  {suffix}")
                else:
                    tbl.add_row("[cyan]●[/cyan]", f"[bold]{label}[/bold]")
            else:
                tbl.add_row("[dim]○[/dim]", f"[dim]{label}[/dim]")

        return Panel(tbl, border_style="blue", expand=False)

    def _format_disk(self) -> str:
        written = format_bytes(self._disk_written or 0)
        if self._disk_total:
            total = format_bytes(self._disk_total)
            return f"[dim]({written} / ~{total})[/dim]"
        if self._disk_written:
            return f"[dim]({written} written)[/dim]"
        return ""


def print_success(config: Config) -> None:
    parts: list[str] = []
    parts.append("[bold]Connect:[/bold]")
    parts.append(f"  [cyan]virt-viewer --attach {config.name}[/cyan]")
    parts.append(f"  [dim](or: virsh domdisplay {config.name})[/dim]")
    parts.append("")

    parts.append("[bold]Get VM IP:[/bold]  [dim](requires guest agent)[/dim]")
    parts.append(f"  [cyan]virsh domifaddr {config.name} --source agent[/cyan]")
    parts.append("")

    parts.append("[bold]SSH:[/bold]")
    parts.append(f"  [cyan]ssh {config.user_name}@<IP>[/cyan]")
    parts.append("")

    parts.append("[bold]RDP:[/bold]")
    rdp = (f"xfreerdp /v:<IP> /u:{config.user_name} "
           f"/p:{config.user_password} /dynamic-resolution")
    parts.append(f"  [cyan]{rdp}[/cyan]")
    if config.win_version.value.startswith("server"):
        parts.append("")
        parts.append("[bold]RDP with USB redirection:[/bold]")
        parts.append(f"  [cyan]{rdp} /usb:auto[/cyan]")
    parts.append("")

    if config.kd:
        import os
        kd_sock = os.path.join(config.cache_dir, f"{config.name}-kd.sock")
        parts.append("[bold]Kernel debugging:[/bold]")
        parts.append(f"  [cyan]socat {kd_sock} -[/cyan]")
        parts.append(f"  [dim]or: windbg -k com:pipe,baud=115200,port={kd_sock}[/dim]")
        parts.append("")

    parts.append("[bold]Management:[/bold]")
    parts.append(f"  [cyan]virsh start {config.name}[/cyan]")
    parts.append(f"  [cyan]virsh shutdown {config.name}[/cyan]")
    parts.append(
        f"  [cyan]virsh snapshot-revert {config.name} fresh-install[/cyan]"
        "  [dim]# rollback[/dim]"
    )
    parts.append(
        f"  [cyan]virsh destroy {config.name}[/cyan]"
        "        [dim]# force stop[/dim]"
    )
    parts.append(
        f"  [cyan]virsh undefine {config.name} --nvram --tpm[/cyan]"
        "  [dim]# remove[/dim]"
    )

    body = "\n".join(parts)
    console.print()
    console.print(Panel(
        body,
        title=f"[green]✔[/green] VM [bold]'{config.name}'[/bold] created successfully",
        border_style="green",
        expand=False,
    ))
    console.print()
