"""kpi.build: NB1 (C1 / C2, Phase 1) values reach the KPI rows; hand-made kpi_values dicts.
kpi.find_run / kpi_report.py: a run with a parameter override (SANDBOX_PARAMS, e.g. the VM's 2026-11-20 08:18 UTC NB1
run with an example 5.6% threshold) is exploration, not a decision — the KPI table takes the run without one."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd  # noqa: E402

import kpi_report  # noqa: E402
from sandbox import audit, kpi  # noqa: E402
from sandbox.config import PARAMS  # noqa: E402
from test_enclave import temp_outputs  # noqa: E402

EXPLORE = {"qd_risk_threshold_pct": 5.6, "ethnicity_source": "ethnicity"}     # the VM exploration run

AUDIT = {"runs": 2, "closed": 2, "pct": 100.0, "open": []}


def nb1(detection=None):
    """C1 200 patients (125 with all 8 core variables), C2 20 patients (8 with all 8 → '<10')."""
    return {
        "joint_core8_pct": {"c1": 62.5, "c2": 40.0}, "joint_lrs_pct": {"c1": 90.0, "c2": 85.0},
        "joint_n": {"c1": {"n": 200, "core8_n": 125, "lrs_n": 180}, "c2": {"n": 20, "core8_n": 8, "lrs_n": 17}},
        "qd_computable_pct": {"c1": 100.0, "c2": 55.0}, "lrs_computable_pct": {"c1": 96.5, "c2": 90.0},
        "lrs_variant": "practice_2012", "lrs_label": "LPRS", "lrs_threshold": None,
        "selection_effect_max_abs_smd": 0.234, "selection_effect_imbalanced_vars": ["age", "bmi"],
        "c1_detection_pct": detection or {"data_end|lrs": None, "data_end|qdiabetes": None,
                                          "first_evidence|lrs": None, "first_evidence|qdiabetes": None},
    }


def nb2():
    return {"joint_completeness_qdiabetes_pct": 48.0, "joint_completeness_qdiabetes_n": 480,
            "joint_completeness_lrs_pct": 70.0, "joint_completeness_lrs_n": 700, "c3_eligible_n": 1000,
            "qd_variant": "reduced", "lrs_label": "LPRS", "lrs_variant": "practice_2012", "horizon_years": 5,
            "qd_threshold": {}, "lrs_threshold": {}}


def row(t, k):
    return t.set_index("kpi").loc[k]


class TestKpiNb1(unittest.TestCase):
    def test_joint_completeness_from_nb1(self):
        t = kpi.build({}, nb1(), {}, {}, AUDIT)
        r = row(t, "Joint Completeness - QDiabetes")
        # 8 → "<10", and the rate with it (40% × 20 would give the 8 back)
        self.assertEqual(r["actual"], "C1 62.5% (N=125/200); C2 suppressed (<10) (N=<10/20)")
        self.assertEqual((r["met"], r["source"]), ("Reported", "NB1 (C1/C2)"))
        self.assertIn("Score computable: C1 100.0%; C2 55.0%", r["notes"])
        r = row(t, "Joint Completeness - LRS")
        self.assertEqual(r["actual"], "C1 90.0% (N=180/200); C2 suppressed (<10) (N=17/20)")   # 20 − 17 < 10
        self.assertIn("Variant: LPRS [K-LRS] — no waist circumference needed", r["notes"])
        self.assertIn("Score computable: C1 96.5%; C2 90.0%", r["notes"])

    def test_no_threshold_keeps_sensitivity_pending(self):
        t = kpi.build({}, nb1(), {}, {}, AUDIT)
        r = row(t, "Sensitivity (Recall, positive class)")
        self.assertTrue(pd.isna(r["actual"]))          # None (NaN on pandas 3)
        self.assertEqual(r["met"], "Pending")
        self.assertIn("threshold not pre-specified", r["notes"])
        self.assertIn("[decision pending]", r["notes"])
        self.assertIn("C1–C2 selection effect: max |SMD| 0.234; |SMD| > 0.1: age, bmi", r["notes"])
        self.assertEqual(row(t, "Specificity")["notes"], "Phase 2 (C3): C1/C2 hold known positives only")

    def test_detection_rate_reported(self):
        det = {"data_end|qdiabetes": 72.1, "first_evidence|qdiabetes": 65.0, "data_end|lrs": None,
               "first_evidence|lrs": 40.5}
        t = kpi.build({}, nb1(det), {}, {}, AUDIT)
        r = row(t, "Sensitivity (Recall, positive class)")
        self.assertEqual(r["actual"], "C1 QDiabetes: data_end 72.1%, first_evidence 65.0%; LPRS: first_evidence 40.5%")
        self.assertEqual((r["met"], r["source"]), ("Reported", "NB1 (C1 known positives)"))  # not judged vs ≥ 70%
        self.assertEqual(kpi.graduation(t)["non_critical_evaluable"], 0)

    def test_detection_rate_with_small_counts_suppressed(self):
        """c1_detection_counts (NB1 from 2026-11-20): a rate whose flagged or (computable − flagged) is < 10 is not
        printed; without the counts (older NB1 runs) the rate is shown as before."""
        det = {"data_end|qdiabetes": 72.1, "first_evidence|qdiabetes": 3.5, "data_end|lrs": 97.0,
               "first_evidence|lrs": None}
        counts = {"data_end|qdiabetes": {"n_flagged": 101, "n_computable": 140},
                  "first_evidence|qdiabetes": {"n_flagged": 5, "n_computable": 140},
                  "data_end|lrs": {"n_flagged": 194, "n_computable": 200}}
        t = kpi.build({}, {**nb1(det), "c1_detection_counts": counts}, {}, {}, AUDIT)
        self.assertEqual(row(t, "Sensitivity (Recall, positive class)")["actual"],
                         "C1 QDiabetes: data_end 72.1%, first_evidence suppressed (<10); LPRS: data_end suppressed (<10)")

    def test_data_completeness_value_suppressed(self):
        """The Data Completeness actual (minimum over the 8) and the weakest-variable note: 99.5% of 1000 = 5 missing."""
        nb0 = {"data_completeness_min_core8_pct": {"c1": 99.5, "c2": 71.0},
               "data_completeness_min_core8": {"c1": {"variable": "bmi", "pct": 99.5, "complete_n": 995, "n": 1000},
                                               "c2": {"variable": "bmi", "pct": 71.0, "complete_n": 710, "n": 1000}},
               "data_completeness_weakest": {"c1": "bmi", "c2": "bmi"},
               "framework_match": True, "framework_missing_groups": []}
        r = row(kpi.build(nb0, {}, {}, {}, AUDIT), "Data Completeness for Required Variables")
        self.assertEqual(r["actual"], "C1 suppressed (<10); C2 71.0%")
        self.assertEqual(r["met"], "Not Met")                                    # judged on the value itself
        self.assertIn("Weakest variable: C1 bmi suppressed (<10); C2 bmi 71.0%", r["notes"])
        self.assertNotIn("99.5", r["actual"] + r["notes"])
        old = {k: v for k, v in nb0.items() if k != "data_completeness_min_core8"}   # NB0 run before the counts
        self.assertEqual(row(kpi.build(old, {}, {}, {}, AUDIT), "Data Completeness for Required Variables")["actual"],
                         "C1 99.5%; C2 71.0%")

    def test_nb1_and_nb2_together(self):
        t = kpi.build({}, nb1(), nb2(), {}, AUDIT)
        r = row(t, "Joint Completeness - QDiabetes")
        self.assertEqual(r["actual"],
                         "C1 62.5% (N=125/200); C2 suppressed (<10) (N=<10/20); C3 48.0% (N=480/1000)")
        self.assertEqual(r["source"], "NB1 (C1/C2) + NB2 (C3 base)")
        self.assertIn("Definition: 8 core variables (reduced)", r["notes"])
        self.assertEqual(row(t, "Specificity")["source"], "NB2")                # NB2 row, not the Phase 2 note
        r = row(t, "Sensitivity (Recall, positive class)")
        self.assertEqual((r["met"], r["source"]), ("Pending", "NB2"))
        self.assertIn("C1–C2 selection effect", r["notes"])

    def test_markdown_dash_for_empty_actual(self):
        t = kpi.build({}, nb1(), {}, {}, AUDIT)
        md = kpi.to_markdown(t, kpi.graduation(t), {})
        self.assertNotIn("| nan |", md)
        self.assertIn("| Applicant | — | Pending |", md)

    def test_without_nb1(self):
        t = kpi.build({}, {}, {}, {}, AUDIT)
        self.assertTrue(pd.isna(row(t, "Joint Completeness - QDiabetes")["actual"]))
        self.assertEqual(row(t, "Sensitivity (Recall, positive class)")["source"], "")


def make_run(out: Path, name: str, ts: str, override: dict | None = None, values: dict | None = None,
             source: str = "nabidh", legacy: bool = False, status: str = "success") -> Path:
    """A finished run folder (manifest + <nbXX>/kpi_values.json). legacy: a manifest from before params_override
    was recorded (only the merged PARAMS snapshot)."""
    d = out / f"{ts}_{name}_abc{len(list(out.glob('*'))):03d}"
    d.mkdir(parents=True)
    params = {**PARAMS, **(override or {})}
    rec = {"run_id": d.name, "name": name, "source": source, "status": status,
           "started_utc": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[9:11]}:{ts[11:13]}:{ts[13:15]}+00:00",
           "params": params, "outputs": []}
    if not legacy:
        rec["params_override"] = audit.params_override(params)
    (d / "run_manifest.json").write_text(json.dumps(rec), encoding="utf-8")
    if values is not None:
        key = name[:4]                                                     # nb01_c1_c2_feasibility → nb01
        (d / key).mkdir()
        (d / key / "kpi_values.json").write_text(json.dumps(values), encoding="utf-8")
    return d


class TestFindRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_override_run_skipped_for_the_one_without(self):
        plain = make_run(self.out, "nb01_c1_c2_feasibility", "20261119T124500Z")
        explore = make_run(self.out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE)       # newer
        make_run(self.out, "nb01_c1_c2_feasibility", "20261120T090000Z", status="failed")
        self.assertEqual(kpi.find_run("nb01_c1_c2_feasibility", "nabidh", self.out), (plain, [explore]))
        self.assertEqual(kpi.latest_run("nb01_c1_c2_feasibility", "nabidh", self.out), plain)
        self.assertEqual(kpi.latest_run("nb01_c1_c2_feasibility", "nabidh", self.out, allow_overrides=True), explore)
        self.assertEqual(kpi.manifest_override(explore), EXPLORE)
        self.assertIsNone(kpi.manifest_override(plain))

    def test_only_override_runs(self):
        a = make_run(self.out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE)
        b = make_run(self.out, "nb01_c1_c2_feasibility", "20261120T091800Z", {"qd_risk_threshold_pct": 7.0})
        self.assertEqual(kpi.find_run("nb01_c1_c2_feasibility", "nabidh", self.out), (None, [b, a]))

    def test_legacy_manifest_compared_with_config(self):
        explore = make_run(self.out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE, legacy=True)
        self.assertEqual(kpi.find_run("nb01_c1_c2_feasibility", "nabidh", self.out), (None, [explore]))
        plain = make_run(self.out, "nb01_c1_c2_feasibility", "20261119T124500Z", legacy=True)
        self.assertEqual(kpi.latest_run("nb01_c1_c2_feasibility", "nabidh", self.out), plain)

    def test_same_value_as_config_is_not_an_override(self):
        self.assertIsNone(audit.params_override({**PARAMS, "horizon_years": float(PARAMS["horizon_years"])}))
        self.assertEqual(audit.params_override({**PARAMS, "typo_key": 1}), {"typo_key": 1})

    def test_pending_note_when_only_override_runs(self):
        t = kpi.build({}, {}, {}, {}, AUDIT, override_only={"nb01": "20261120T081800Z_nb01_c1_c2_feasibility_abc"})
        for k in ("Joint Completeness - QDiabetes", "Joint Completeness - LRS", "Sensitivity (Recall, positive class)"):
            r = row(t, k)
            self.assertEqual(r["met"], "Pending", k)
            self.assertTrue(pd.isna(r["actual"]), k)
            self.assertIn("Only runs with parameter overrides found for NB1 "
                          "(20261120T081800Z_nb01_c1_c2_feasibility_abc)", r["notes"])
        self.assertNotIn("parameter overrides", row(t, "Specificity")["notes"])          # NB2 row
        self.assertNotIn("parameter overrides", row(t, "Data Completeness for Required Variables")["notes"])
        t = kpi.build({}, nb1(), {}, {}, AUDIT, override_only={"nb02": "x_nb02"})
        r = row(t, "Sensitivity (Recall, positive class)")             # Pending for the threshold, NB2 override-only
        self.assertIn("threshold not pre-specified", r["notes"])
        self.assertIn("Only runs with parameter overrides found for NB2 (x_nb02)", r["notes"])
        self.assertNotIn("parameter overrides", row(t, "Joint Completeness - QDiabetes")["notes"])   # Reported


class TestKpiReportSkipsOverrides(unittest.TestCase):
    """tools/kpi_report.py end to end on run folders in a temporary outputs/."""

    def report(self, out: Path, *argv: str) -> tuple[pd.DataFrame, dict, dict, str]:
        buf = io.StringIO()
        with mock.patch.object(kpi, "OUTPUT_DIR", out), mock.patch.object(kpi_report, "OUTPUT_DIR", out), \
                mock.patch.object(kpi, "audit_completeness", lambda running=(): AUDIT), \
                mock.patch.dict(os.environ, {"SANDBOX_SOURCE": "nabidh"}), contextlib.redirect_stdout(buf):
            self.assertEqual(kpi_report.main(list(argv)), 0)
        d = sorted(out.glob("*_kpi_report_*"))[-1]
        manifest = json.loads((d / "run_manifest.json").read_text(encoding="utf-8"))
        grad = json.loads((d / "kpi" / "graduation.json").read_text(encoding="utf-8"))
        return pd.read_csv(d / "kpi" / "kpi_table.csv"), grad, manifest, buf.getvalue()

    def test_uses_the_run_without_override(self):
        with temp_outputs() as out:
            plain = make_run(out, "nb01_c1_c2_feasibility", "20261119T124500Z", values=nb1())
            explore = make_run(out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE,
                               values={**nb1(), "joint_core8_pct": {"c1": 99.0, "c2": 99.0}})
            t, grad, manifest, text = self.report(out)
        self.assertEqual(row(t, "Joint Completeness - QDiabetes")["actual"],
                         "C1 62.5% (N=125/200); C2 suppressed (<10) (N=<10/20)")   # not the 99.0% exploration run
        self.assertEqual(grad["runs"]["nb01"], plain.name)
        self.assertEqual(grad["skipped_override_runs"], {"nb01": [explore.name]})
        self.assertIsNone(manifest["params_override"])
        self.assertIsNone(manifest["override_inputs"])
        self.assertIn(f"Not used (parameter overrides, SANDBOX_PARAMS): nb01={explore.name}", text)   # kpi_report.md

    def test_only_override_runs_stay_pending(self):
        with temp_outputs() as out:
            explore = make_run(out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE, values=nb1())
            t, grad, _, text = self.report(out)
        r = row(t, "Joint Completeness - QDiabetes")
        self.assertEqual(r["met"], "Pending")
        self.assertTrue(pd.isna(r["actual"]))
        self.assertIn(f"Only runs with parameter overrides found for NB1 ({explore.name})", r["notes"])
        self.assertIsNone(grad["runs"]["nb01"])
        self.assertIn("no run with the configured parameters: its KPI rows stay Pending", text)

    def test_allow_overrides_is_marked_and_not_used_by_the_evidence_package(self):
        with temp_outputs() as out:
            explore = make_run(out, "nb01_c1_c2_feasibility", "20261120T081800Z", EXPLORE,
                               values={**nb1(), "joint_core8_pct": {"c1": 99.0, "c2": 99.0}})
            t, grad, manifest, text = self.report(out, "--allow-overrides")
            evidence_kpi = kpi.latest_run("kpi_report", "nabidh", out)
        self.assertTrue(row(t, "Joint Completeness - QDiabetes")["actual"].startswith("C1 99.0%"))
        self.assertEqual(manifest["override_inputs"], {"nb01": {"run": explore.name, "params_override": EXPLORE}})
        self.assertIn("EXPLORATORY (--allow-overrides), not for the DFF report", text)
        self.assertIsNone(evidence_kpi)                           # build_evidence_package skips this KPI report


class TestRunManifest(unittest.TestCase):
    def test_override_recorded(self):
        with temp_outputs() as out, mock.patch.dict(os.environ, {"SANDBOX_PARAMS": json.dumps(EXPLORE),
                                                                 "SANDBOX_BOOTSTRAP_REPS": "100"}):
            r = audit.Run("nb01_c1_c2_feasibility", params={**PARAMS, **EXPLORE}, source="nabidh")
            rec = json.loads(r.finish().read_text(encoding="utf-8"))
            plain = json.loads(audit.Run("kpi_report", source="nabidh").finish().read_text(encoding="utf-8"))
            log = [json.loads(x) for x in (out / "audit" / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rec["params_override"], EXPLORE)
        self.assertEqual(rec["env_overrides"], {"SANDBOX_PARAMS": json.dumps(EXPLORE), "SANDBOX_BOOTSTRAP_REPS": "100"})
        self.assertIsNone(plain["params_override"])                          # env set, but this run used PARAMS
        start = next(e for e in log if e["event"] == "run_start" and e["run_id"] == rec["run_id"])
        self.assertEqual(start["params_override"], EXPLORE)                  # in the append-only log too


if __name__ == "__main__":
    unittest.main()
