"""Execute the analysis pipeline (body_exec.py) with project-root paths."""

from __future__ import annotations

import io
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from vm_analysis.result_split import (
    duration_excerpt_from_log,
    split_tables_for_tabs,
)

_BODY_PATH = Path(__file__).resolve().parent / "body_exec.py"


def _align_figure_titles(figures: list[str], titles: list[str]) -> list[str]:
    out = list(titles)
    while len(out) < len(figures):
        out.append(f"Chart {len(out) + 1}")
    return out[: len(figures)]


def run_analysis(
    project_root: Path | str,
    *,
    index_nrows: int = 19,
) -> dict[str, Any]:
    """
    Run the full RVTools analysis pipeline.

    Expects ``data/index.xlsx`` and RVTools ``.xlsx`` exports under ``project_root/data/``,
    and pattern files under ``project_root/helper_files/``.
    Writes CSV exports under ``project_root/saved_csv_files/``.

    Returns a dict with keys: success (bool), error (str|None), log (str),
    figures (list of base64 PNG strings), figure_titles (parallel titles from matplotlib),
    tables (risk-focused HTML tables),
    duration (dict with tables + log_excerpt for the duration-estimate tab),
    risk_summary (dict|None): overall score and inputs for the Risk tab.
    discovered_os (dict|None): in_scope / out_of_scope OS lists with vm_count for the Risk tab.
    """
    root = Path(project_root).resolve()
    saved = root / "saved_csv_files"
    helper = root / "helper_files"
    saved.mkdir(parents=True, exist_ok=True)

    code = _BODY_PATH.read_text(encoding="utf-8")
    g: dict[str, Any] = {
        "__name__": "__rvtools_analysis__",
        "__builtins__": __builtins__,
        "ROOT": root,
        "SAVED_DIR": saved,
        "HELPER_DIR": helper,
        "INDEX_NROWS": index_nrows,
    }
    log_buf = io.StringIO()
    try:
        with redirect_stdout(log_buf), redirect_stderr(log_buf):
            exec(compile(code, str(_BODY_PATH), "exec"), g)
    except Exception:
        err = traceback.format_exc()
        raw_log = log_buf.getvalue()
        raw_tables = list(g.get("__tables__") or [])
        risk_tables, duration_tables = split_tables_for_tabs(raw_tables)
        figs = list(g.get("__figures__") or [])
        return {
            "success": False,
            "error": err,
            "log": raw_log,
            "figures": figs,
            "figure_titles": _align_figure_titles(figs, list(g.get("__figure_titles__") or [])),
            "tables": risk_tables,
            "risk_summary": g.get("__risk_summary__"),
            "discovered_os": g.get("__discovered_os__"),
            "duration": {
                "tables": duration_tables,
                "log_excerpt": duration_excerpt_from_log(raw_log),
                "recalc": g.get("__duration_recalc__"),
            },
        }

    raw_log = log_buf.getvalue()
    raw_tables = list(g.get("__tables__") or [])
    risk_tables, duration_tables = split_tables_for_tabs(raw_tables)
    figs = list(g.get("__figures__") or [])
    return {
        "success": True,
        "error": None,
        "log": raw_log,
        "figures": figs,
        "figure_titles": _align_figure_titles(figs, list(g.get("__figure_titles__") or [])),
        "tables": risk_tables,
        "risk_summary": g.get("__risk_summary__"),
        "discovered_os": g.get("__discovered_os__"),
        "duration": {
            "tables": duration_tables,
            "log_excerpt": duration_excerpt_from_log(raw_log),
            "recalc": g.get("__duration_recalc__"),
        },
    }
