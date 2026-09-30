"""Dry-run reporting generator for trust-building audit trails.

Enforces Requirement 15:
Lists every field the agent would fill and every field it refused (with exact reasons),
and confirms submit primitives neutralized without mutating external networks.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from rich.table import Table

from qr_form_agent.mapping.tier1_rules import MappedField


class DryRunFieldReport(BaseModel):
    field_id: str
    name_or_label: str
    action: str  # "FILL" or "REFUSE"
    value: Optional[str] = None
    source: str
    confidence: float
    reason: str


class DryRunReport(BaseModel):
    job_id: str
    url: str
    company: Optional[str] = None
    role: Optional[str] = None
    fields_to_fill: List[DryRunFieldReport] = Field(default_factory=list)
    fields_refused: List[DryRunFieldReport] = Field(default_factory=list)
    submit_buttons_neutralized: int = 0
    route_guard_active: bool = True
    overall_confidence: float = 0.0

    def to_rich_table(self) -> Table:
        """Renders the dry-run report as a rich terminal table."""
        table = Table(
            title=f"[bold cyan]DRY-RUN PRE-FILL AUDIT REPORT -- {self.company or 'Job'} ({self.role or 'Role'})[/bold cyan]",
            caption=f"Zero mutations performed. {len(self.fields_to_fill)} fields fillable, {len(self.fields_refused)} refused.",
            header_style="bold cyan",
        )

        table.add_column("Action", justify="center", width=10)
        table.add_column("Field Label / Name", style="bold white", min_width=20)
        table.add_column("Value to Populate", style="italic yellow", max_width=30, overflow="ellipsis")
        table.add_column("Source", style="cyan", width=22)
        table.add_column("Conf.", justify="center", width=8)
        table.add_column("Reason / Safety Rationale", style="dim")

        # 1. Fillable fields
        for f in self.fields_to_fill:
            table.add_row(
                "[bold green]WILL FILL[/bold green]",
                f.name_or_label,
                str(f.value or ""),
                f.source,
                f"{f.confidence:.2f}",
                f.reason,
            )

        # 2. Refused fields
        for f in self.fields_refused:
            table.add_row(
                "[bold red]REFUSED[/bold red]",
                f.name_or_label,
                "[dim]None[/dim]",
                f.source,
                f"{f.confidence:.2f}",
                f.reason,
            )

        return table


def build_dry_run_report(
    job_id: str,
    url: str,
    mapped_fields: List[MappedField],
    company: Optional[str] = None,
    role: Optional[str] = None,
    blocked_submits_count: int = 0,
) -> DryRunReport:
    """Constructs a structured dry-run report from mapping output."""
    to_fill: List[DryRunFieldReport] = []
    refused: List[DryRunFieldReport] = []

    confidences: List[float] = []

    for m in mapped_fields:
        if m.value is not None and not m.flagged_for_review:
            to_fill.append(
                DryRunFieldReport(
                    field_id=m.field_id,
                    name_or_label=m.field_id,
                    action="FILL",
                    value=str(m.value),
                    source=m.profile_key or "verified_profile",
                    confidence=m.confidence,
                    reason=m.reason or "High confidence profile match",
                )
            )
            confidences.append(m.confidence)
        else:
            reason = "Denylisted security field" if "denylist" in (m.reason or "").lower() else (
                "Unmapped or low confidence" if m.value is None else "Flagged for manual review"
            )
            refused.append(
                DryRunFieldReport(
                    field_id=m.field_id,
                    name_or_label=m.field_id,
                    action="REFUSE",
                    value=None,
                    source=m.profile_key or "unmapped",
                    confidence=m.confidence,
                    reason=f"{reason} ({m.reason or ''})",
                )
            )

    avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0

    return DryRunReport(
        job_id=job_id,
        url=url,
        company=company,
        role=role,
        fields_to_fill=to_fill,
        fields_refused=refused,
        submit_buttons_neutralized=blocked_submits_count,
        route_guard_active=True,
        overall_confidence=round(avg_conf, 2),
    )
