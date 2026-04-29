"""CLI: python -m vm_analysis [--root PATH] [--nrows N]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import run_analysis


def main() -> int:
    p = argparse.ArgumentParser(description="Run RVTools VM analysis without Jupyter.")
    p.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root (contains data/, helper_files/). Default: current directory.",
    )
    p.add_argument(
        "--nrows",
        type=int,
        default=19,
        help="Rows to read from index.xlsx (header + data rows). Default: 19.",
    )
    args = p.parse_args()
    r = run_analysis(args.root, index_nrows=args.nrows)
    print(r["log"], end="")
    if not r["success"]:
        print(r["error"], file=sys.stderr)
        return 1
    print(f"\n[OK] Generated {len(r['figures'])} chart(s), {len(r['tables'])} table(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
