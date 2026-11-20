"""KPI report — latest successful NB0 / NB1 / NB2 runs + audit log + evidence package.

Usage:   python tools/kpi_report.py [--allow-overrides]
Output:  outputs/<run_id>/kpi/kpi_table.csv, kpi_report.md, graduation.json
Can be attached directly to the biweekly DFF report.

Runs with a parameter override (SANDBOX_PARAMS, e.g. an example threshold) are exploration, not a decision: they
are left out and named in the report; a notebook with only such runs leaves its KPI rows Pending ("Only runs with
parameter overrides found"). --allow-overrides takes the latest run whatever its parameters — an exploratory KPI
table, marked as such in the report and the manifest (`override_inputs`), never used by the evidence package.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sandbox import kpi  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import OUTPUT_DIR  # noqa: E402

INPUTS = {"nb00": "nb00_data_profile", "nb01": "nb01_c1_c2_feasibility", "nb02": "nb02_c3_benchmark"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KPI table from the latest NB0 / NB1 / NB2 runs")
    ap.add_argument("--allow-overrides", action="store_true",
                    help="also use runs with parameter overrides (SANDBOX_PARAMS): exploratory, not for the DFF report")
    a = ap.parse_args(argv)
    parent = [r for r in os.environ.get("SANDBOX_PARENT_RUN", "").split(",") if r]   # enclave run, still open
    audit = kpi.audit_completeness(running=parent)          # before this run
    source = os.environ.get("SANDBOX_SOURCE", "synthetic")
    run = Run("kpi_report", source=source)
    found = {k: kpi.find_run(prefix, source, allow_overrides=a.allow_overrides) for k, prefix in INPUTS.items()}
    runs = {k: d for k, (d, _) in found.items()}
    skipped = {k: [d.name for d in s] for k, (_, s) in found.items() if s}
    override_only = {k: s[0] for k, s in skipped.items() if runs[k] is None}
    override_inputs = {k: {"run": d.name, "params_override": kpi.manifest_override(d)}
                       for k, d in runs.items() if kpi.manifest_override(d)}
    if not any(runs.values()):
        print(f"WARNING: no successful NB0 / NB1 / NB2 run for SANDBOX_SOURCE={source!r}"
              + (" with the configured parameters" if override_only else "") + " → KPIs stay empty. "
              f"Run the notebooks first with the same SANDBOX_SOURCE ('nabidh' in the enclave; IntelliJ: 2e / 3e / 4e, "
              f"then 5e).\n")
    for k, names in skipped.items():
        print(f"NOTE: {k}: {len(names)} newer run(s) with parameter overrides (SANDBOX_PARAMS) not used, latest "
              f"{names[0]}" + (" — no run with the configured parameters: its KPI rows stay Pending" if k in override_only
                               else f"; using {runs[k].name}"))
    if override_inputs:
        print("WARNING: --allow-overrides: KPI inputs with parameter overrides (exploratory, not for the DFF report): "
              + "; ".join(f"{k}={v['run']} {json.dumps(v['params_override'], ensure_ascii=False)}"
                          for k, v in override_inputs.items()))
    if skipped or override_inputs:
        print()
    run.record["override_inputs"] = override_inputs or None     # kpi.find_run skips this report (evidence package)
    run.log("KPI inputs", runs={k: (v.name if v else None) for k, v in runs.items()},
            skipped_override_runs=skipped, allow_overrides=a.allow_overrides, override_inputs=override_inputs)
    ev_dirs = sorted(OUTPUT_DIR.glob("evidence_package_*/checklist.json"))
    evidence = json.loads(ev_dirs[-1].read_text(encoding="utf-8")) if ev_dirs else {}
    for name, d in runs.items():
        if d is not None:
            run.add_inputs([d / name / "kpi_values.json"] if (d / name / "kpi_values.json").exists() else [])
    table = kpi.build(kpi._load(runs["nb00"], "nb00/kpi_values.json"),
                      kpi._load(runs["nb01"], "nb01/kpi_values.json"),
                      kpi._load(runs["nb02"], "nb02/kpi_values.json"), evidence, audit, override_only=override_only)
    grad = kpi.graduation(table)
    meta = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "source": source,
            "runs": {k: (v.name if v else None) for k, v in runs.items()},
            "allow_overrides": a.allow_overrides, "skipped_override_runs": skipped, "override_inputs": override_inputs}
    run.save_table(table, "kpi/kpi_table.csv", "KPI table (Target vs Actual)")
    md = run.path("kpi/kpi_report.md")
    md.write_text(kpi.to_markdown(table, grad, meta), encoding="utf-8")
    run.register_output(md, "KPI summary for the biweekly report")
    run.save_json({**grad, **meta, "audit": audit}, "kpi/graduation.json", "Graduation pre-assessment")
    run.finish()
    print(md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
