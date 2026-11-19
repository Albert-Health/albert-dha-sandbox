"""Evidence package builder (KPI: Evidence Package Completeness — Critical).

Collects the manifests and outputs of the latest successful NB0 / NB1 / NB2 / KPI runs,
the docs/evidence_package templates and the code fingerprint into one folder; produces a file hash list
and a section checklist.

Usage:   python tools/build_evidence_package.py
Output:  outputs/evidence_package_<UTC>/  (index.md, files_sha256.csv, checklist.json, ...)

To count as "Complete": all four runs must exist AND no unfilled {{...}} field may remain
in the templates (filled templates go under docs/evidence_package/filled/).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sandbox import kpi  # noqa: E402
from sandbox.audit import Run, sha256_file  # noqa: E402
from sandbox.config import OUTPUT_DIR, REPO_ROOT  # noqa: E402

SECTIONS = {
    "data_quality_report": ["nb00_data_profile", "nb01_c1_c2_feasibility"],
    "cohort_derivation": ["nb02_c3_benchmark"],
    "validation_report": ["nb02_c3_benchmark", "kpi_report"],
    "model_card": ["nb02_c3_benchmark"],
}
TEMPLATES = REPO_ROOT / "docs" / "evidence_package"


def main() -> None:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = OUTPUT_DIR / f"evidence_package_{ts}"
    out.mkdir(parents=True)
    source = os.environ.get("SANDBOX_SOURCE", "synthetic")
    run = Run("evidence_package", source=source)

    runs = {name: kpi.latest_run(name, source) for name in
            ["nb00_data_profile", "nb01_c1_c2_feasibility", "nb02_c3_benchmark", "kpi_report"]}
    for name, d in runs.items():
        if d is not None:
            shutil.copytree(d, out / "runs" / d.name)
    shutil.copytree(REPO_ROOT / "src", out / "code" / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO_ROOT / "notebooks", out / "code" / "notebooks",
                    ignore=shutil.ignore_patterns("*.ipynb", ".ipynb_checkpoints"))
    for f in ["requirements.txt", "README.md"]:
        shutil.copy2(REPO_ROOT / f, out / "code" / f)
    audit_log = OUTPUT_DIR / "audit" / "audit_log.jsonl"
    if audit_log.exists():
        shutil.copy2(audit_log, out / "audit_log.jsonl")

    checklist = {"path": str(out.relative_to(REPO_ROOT)), "sections": {}}
    filled_dir = TEMPLATES / "filled"
    (out / "documents").mkdir()
    for section, needed in SECTIONS.items():
        filled = filled_dir / f"{section}.md"
        src = filled if filled.exists() else TEMPLATES / f"{section}.md"
        shutil.copy2(src, out / "documents" / f"{section}.md")
        text = src.read_text(encoding="utf-8")
        placeholders = sorted(set(re.findall(r"\{\{(\w+)\}\}", text)))
        missing_runs = [n for n in needed if runs.get(n) is None]
        checklist["sections"][section] = {"document": "filled" if filled.exists() else "template",
                                          "unfilled_placeholders": placeholders, "missing_runs": missing_runs,
                                          "complete": filled.exists() and not placeholders and not missing_runs}
    checklist["total_sections"] = len(SECTIONS)
    checklist["complete_sections"] = sum(s["complete"] for s in checklist["sections"].values())
    checklist["complete"] = checklist["complete_sections"] == checklist["total_sections"]
    checklist["runs"] = {k: (v.name if v else None) for k, v in runs.items()}
    (out / "checklist.json").write_text(json.dumps(checklist, indent=2, ensure_ascii=False), encoding="utf-8")

    files = sorted(p for p in out.rglob("*") if p.is_file())
    lines = ["path,bytes,sha256"] + [f"{p.relative_to(out)},{p.stat().st_size},{sha256_file(p)}" for p in files]
    (out / "files_sha256.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    index = [f"# Evidence package {ts}", "", f"- Sections: {checklist['complete_sections']}/{checklist['total_sections']} complete",
             f"- Files: {len(files)} (hash list: files_sha256.csv)", "", "| Section | Document | Missing fields | Missing runs |",
             "|---|---|---|---|"]
    for s, v in checklist["sections"].items():
        index.append(f"| {s} | {v['document']} | {len(v['unfilled_placeholders'])} | {', '.join(v['missing_runs']) or '—'} |")
    index += ["", "Runs: " + ", ".join(f"{k}={v}" for k, v in checklist["runs"].items())]
    (out / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    for f in ["index.md", "checklist.json", "files_sha256.csv"]:
        run.register_output(out / f, f"evidence package {f}")
    run.log("evidence package built", path=checklist["path"], complete=checklist["complete"])
    run.finish()
    print((out / "index.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
