"""Reminder formatting for upcoming deadlines and opening notices.

Enforces Requirement 12:
Displays opening reminders (e.g. "Horizon opens in December") and approaching deadlines.
"""

from typing import Dict, List
from rich.table import Table
from qr_form_agent.core.db import JobRecord


def generate_reminders_table(jobs: List[JobRecord]) -> Table:
    """Creates a Rich Table displaying upcoming deadlines and opening notices."""
    table = Table(
        title="[bold yellow]Upcoming Deadlines & Opening Reminders[/bold yellow]",
        caption="Review deadlines and mark calendar alerts.",
        header_style="bold yellow",
    )

    table.add_column("Company", style="bold cyan")
    table.add_column("Role", style="magenta")
    table.add_column("Notice / Type", justify="center")
    table.add_column("Date / Period", style="bold green")
    table.add_column("Status", justify="center")
    table.add_column("Notes", style="italic")

    found_any = False
    for j in jobs:
        if j.deadline or j.opening_date or j.notes:
            notice_type = "OPENING" if j.opening_date else ("DEADLINE" if j.deadline else "NOTICE")
            date_val = j.opening_date or j.deadline or "TBD"
            table.add_row(
                j.company or "[dim]Unknown[/dim]",
                j.role or "[dim]Unknown[/dim]",
                f"[bold yellow]{notice_type}[/bold yellow]",
                date_val,
                j.status.value,
                j.notes or "",
            )
            found_any = True

    if not found_any:
        table.add_row("No active reminders", "-", "-", "-", "-", "Scan board images to extract notices")

    return table
