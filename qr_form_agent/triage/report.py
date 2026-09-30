"""Triage reporting and table formatting for CLI and Web UI.

Enforces Requirement 1:
Outputs a structured summary table showing which URLs are fillable forms,
landing pages, login walls, closed postings, or dead endpoints.
"""

from typing import Any, Dict, List
from rich.console import Console
from rich.table import Table

from qr_form_agent.triage.models import TriageResult, TriageStatus


def generate_triage_table(results: List[TriageResult]) -> Table:
    """Generates a styled Rich Table from a list of TriageResults."""
    table = Table(
        title="[bold magenta]QR Form Agent -- Pipeline Triage Report[/bold magenta]",
        caption="Triage complete. Form jobs are staged for automated pre-filling.",
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("#", style="dim", width=4)
    table.add_column("Company / Role", style="bold cyan", min_width=20)
    table.add_column("Status", justify="center", width=14)
    table.add_column("Actionable", justify="center", width=12)
    table.add_column("Target URL", style="dim", max_width=35, overflow="ellipsis")
    table.add_column("Reason / Details", style="italic")

    status_styles = {
        TriageStatus.FORM: "[bold green]FORM[/bold green]",
        TriageStatus.LANDING_PAGE: "[bold yellow]LANDING_PAGE[/bold yellow]",
        TriageStatus.LOGIN_WALL: "[bold magenta]LOGIN_WALL[/bold magenta]",
        TriageStatus.CLOSED: "[bold red]CLOSED[/bold red]",
        TriageStatus.DEAD: "[bold red]DEAD[/bold red]",
    }

    for idx, r in enumerate(results, start=1):
        status_disp = status_styles.get(r.status, str(r.status.value))
        actionable_disp = "[bold green]YES[/bold green]" if r.actionable else "[dim red]NO[/dim red]"

        comp_role = []
        if r.company:
            comp_role.append(r.company)
        if r.role:
            comp_role.append(f"({r.role})")
        comp_disp = " ".join(comp_role) if comp_role else "[dim]Unknown[/dim]"

        table.add_row(
            str(idx),
            comp_disp,
            status_disp,
            actionable_disp,
            r.url,
            r.reason,
        )

    return table


def summarize_triage(results: List[TriageResult]) -> Dict[str, Any]:
    """Computes summary statistics across triage outcomes."""
    counts = {s.value: 0 for s in TriageStatus}
    actionable_count = 0

    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
        if r.actionable:
            actionable_count += 1

    total = len(results)
    summary_text = (
        f"Discovered {total} QRs: "
        f"{counts[TriageStatus.FORM.value]} FORM, "
        f"{counts[TriageStatus.LANDING_PAGE.value]} LANDING_PAGE, "
        f"{counts[TriageStatus.LOGIN_WALL.value]} LOGIN_WALL, "
        f"{counts[TriageStatus.CLOSED.value]} CLOSED, "
        f"{counts[TriageStatus.DEAD.value]} DEAD. "
        f"{actionable_count} of {total} are fillable or accessible."
    )

    return {
        "total": total,
        "actionable": actionable_count,
        "counts": counts,
        "summary_text": summary_text,
    }
