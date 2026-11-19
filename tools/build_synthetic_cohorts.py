"""Builds the canonical C1 / C2 / C3 cohorts from the synthetic test data.

Usage:   python tools/build_synthetic_cohorts.py
Input:   data/synthetic/raw/*.csv
Output:  data/canonical/synthetic/{c1,c2,c3}/*.csv  + build_report.json

Goal: test the whole pipeline before real data arrive by emulating the three cohorts
NABIDH will deliver in the enclave. The selection rules are the same as the
specifications sent to NABIDH (Interim Data Assessment, Cohort Spec v2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sandbox import cohorts  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, PARAMS, RAW_DIR  # noqa: E402
from sandbox.io import schema  # noqa: E402
from sandbox.io.adapters import synthetic  # noqa: E402


def main() -> None:
    run = Run("build_synthetic_cohorts", source="synthetic")
    run.add_inputs([RAW_DIR["synthetic"]])

    full = synthetic.load(RAW_DIR["synthetic"])
    run.log("raw synthetic loaded", n_patients=full.n_patients,
            rows={k: len(v) for k, v in full.tables.items()})

    sel = cohorts.build_c1_c2(full, PARAMS)
    run.log("C1/C2 selected", **sel["report"])
    # NABIDH delivers C3 per the v2 specification (no washout); the outcome washout (D1) is an analysis
    # decision and is applied in NB0 / NB2. When emulating the delivery, washout = 0.
    c3 = cohorts.build_c3(full, dict(PARAMS, outcome_washout_days=0))
    run.log("C3 built (delivery emulation, washout 0)", **c3["funnel"])

    out_base = CANONICAL_DIR
    for name, ids in [("c1", sel["c1_ids"]), ("c2", sel["c2_ids"]), ("c3", list(c3["cohort"].index))]:
        ds = cohorts.subset(full, ids, name)
        d = schema.write_dataset(ds, out_base)
        for f in sorted(d.glob("*.csv")):
            run.register_output(f, f"canonical {name} {f.stem}")
        run.log(f"{name} written", path=str(d.relative_to(out_base.parent.parent)), n_patients=ds.n_patients)

    report = {"c1_c2": sel["report"], "c3_funnel": c3["funnel"], "params": PARAMS,
              "note": "SYNTHETIC — NOT REAL PATIENT DATA"}
    rp = CANONICAL_DIR / "synthetic" / "build_report.json"
    rp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    run.register_output(rp, "synthetic cohort build report")
    run.finish()
    print(json.dumps(report["c1_c2"], indent=2))
    print(json.dumps(report["c3_funnel"], indent=2))
    print("run:", run.run_id)


if __name__ == "__main__":
    main()
