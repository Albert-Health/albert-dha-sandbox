"""KPI report — latest successful NB0 / NB1 / NB2 runs + audit log + evidence package.

Usage:   python tools/kpi_report.py
Output:  outputs/<run_id>/kpi/kpi_table.csv, kpi_report.md, graduation.json
Can be attached directly to the biweekly DFF report.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sandbox import kpi  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import OUTPUT_DIR  # noqa: E402


def main() -> None:
    audit = kpi.audit_completeness()          # before this run
    source = os.environ.get("SANDBOX_SOURCE", "synthetic")
    run = Run("kpi_report", source=source)
    runs = {"nb00": kpi.latest_run("nb00_data_profile", source), "nb01": kpi.latest_run("nb01_c1_c2_feasibility", source),
            "nb02": kpi.latest_run("nb02_c3_benchmark", source)}
    if not any(runs.values()):
        print(f"WARNING: no successful NB0 / NB1 / NB2 run for SANDBOX_SOURCE={source!r} → KPIs stay empty. "
              f"Run the notebooks first with the same SANDBOX_SOURCE ('nabidh' in the enclave; IntelliJ: 2e / 3e / 4e, "
              f"then 5e).\n")
    ev_dirs = sorted(OUTPUT_DIR.glob("evidence_package_*/checklist.json"))
    evidence = json.loads(ev_dirs[-1].read_text(encoding="utf-8")) if ev_dirs else {}
    for name, d in runs.items():
        if d is not None:
            run.add_inputs([d / name / "kpi_values.json"] if (d / name / "kpi_values.json").exists() else [])
    table = kpi.build(kpi._load(runs["nb00"], "nb00/kpi_values.json"),
                      kpi._load(runs["nb01"], "nb01/kpi_values.json"),
                      kpi._load(runs["nb02"], "nb02/kpi_values.json"), evidence, audit)
    grad = kpi.graduation(table)
    meta = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "runs": {k: (v.name if v else None) for k, v in runs.items()}}
    run.save_table(table, "kpi/kpi_table.csv", "KPI table (Target vs Actual)")
    md = run.path("kpi/kpi_report.md")
    md.write_text(kpi.to_markdown(table, grad, meta), encoding="utf-8")
    run.register_output(md, "KPI summary for the biweekly report")
    run.save_json({**grad, **meta, "audit": audit}, "kpi/graduation.json", "Graduation pre-assessment")
    run.finish()
    print(md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
