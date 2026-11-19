"""kpi.build: NB1 (C1 / C2, Phase 1) values reach the KPI rows; hand-made kpi_values dicts."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from sandbox import kpi  # noqa: E402

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
        self.assertEqual(r["actual"], "C1 62.5% (N=125/200); C2 40.0% (N=<10/20)")   # 8 → "<10"
        self.assertEqual((r["met"], r["source"]), ("Reported", "NB1 (C1/C2)"))
        self.assertIn("Score computable: C1 100.0%; C2 55.0%", r["notes"])
        r = row(t, "Joint Completeness - LRS")
        self.assertEqual(r["actual"], "C1 90.0% (N=180/200); C2 85.0% (N=17/20)")
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

    def test_nb1_and_nb2_together(self):
        t = kpi.build({}, nb1(), nb2(), {}, AUDIT)
        r = row(t, "Joint Completeness - QDiabetes")
        self.assertEqual(r["actual"], "C1 62.5% (N=125/200); C2 40.0% (N=<10/20); C3 48.0% (N=480/1000)")
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


if __name__ == "__main__":
    unittest.main()
