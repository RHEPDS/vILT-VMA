"""Split analysis outputs for UI tabs (risk vs duration estimate)."""

from __future__ import annotations

import re


def duration_excerpt_from_log(log: str) -> str:
    """Lines from stdout that mention migration duration / global totals (prints, not display())."""
    if not log:
        return ""
    lines_out: list[str] = []
    for line in log.splitlines():
        low = line.lower()
        if any(
            phrase in low
            for phrase in (
                "global total migration",
                "global total days",
                "global total weeks",
                "migration summary for vcenter",
                "migration summary",
                "total migration time",
                "total days",
                "total weeks",
                "days per fte",
                "formatted_mig",
                "disk_classification",
                "environment_summary",
                "post-migration",
                "migration time (minutes)",
                "total time (minutes)",
            )
        ):
            lines_out.append(line)
        elif re.search(r"\b\d+[,.]?\d*\s*(h|hours?|days?|weeks?)\b", low) and any(
            x in low for x in ("migration", "total", "global", "fte", "disk")
        ):
            lines_out.append(line)
        elif "✅" in line and any(x in low for x in ("global", "migration", "total", "day", "week")):
            lines_out.append(line)
    return "\n".join(lines_out) if lines_out else ""


def _html_looks_like_duration(html: str) -> bool:
    h = html.lower()
    # Pandas to_html column names / content
    if "migration" in h and any(
        x in h for x in ("time", "minute", "day", "week", "fte", "disk")
    ):
        return True
    if any(
        x in h.replace(" ", "")
        for x in ("total_days", "total_weeks", "total_time", "migrationtime", "days_per")
    ):
        return True
    if "environment" in h and ("vm_count" in h or "total_disk" in h):
        return True
    if "complexity" in h and "os support" in h and "migration" in h:
        return True
    return False


def split_tables_for_tabs(
    tables: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Returns (risk_tables, duration_tables).
    Tables that look like migration duration / environment / disk classification go to duration.
    """
    risk: list[tuple[str, str]] = []
    duration: list[tuple[str, str]] = []
    for item in tables:
        _, html = item
        if _html_looks_like_duration(html):
            duration.append(item)
        else:
            risk.append(item)
    return risk, duration
