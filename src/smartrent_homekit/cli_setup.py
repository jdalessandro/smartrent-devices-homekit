"""CLI for the Textual setup wizard and credential cleanup."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console

from smartrent_homekit.setup_tui import run_setup_wizard
from smartrent_homekit.smartrent.store import config_path, get_credentials_env_path

console = Console()


@click.group()
@click.version_option(package_name="smartrent-homekit")
def cli() -> None:
    """Create ``devices.json`` and manage saved SmartRent credentials."""
    logging.basicConfig(level=logging.WARNING)


@cli.command("init")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=Path("devices.json"),
    help="Path to write devices.json",
)
def init_cmd(output: Path) -> None:
    """Full-screen interactive setup (mouse + keyboard)."""
    sys.exit(run_setup_wizard(output))


@cli.command("clear-credentials")
def clear_credentials() -> None:
    """Remove app config and the recorded ``smartrent.env`` file."""
    cred_path = get_credentials_env_path()
    if cred_path is not None and cred_path.is_file():
        try:
            cred_path.unlink()
        except OSError as e:
            console.print(f"[yellow]Could not delete {cred_path}: {e}[/yellow]")

    p = config_path()
    if p.is_file():
        p.unlink()
    console.print("[green]Credential cleanup finished.[/green]")


def main() -> None:
    cli(prog_name="smartrent-homekit-setup")


if __name__ == "__main__":
    main()
