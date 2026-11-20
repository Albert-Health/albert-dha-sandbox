"""Completeness report (C1 / C2 checklist): measure type per variable, the family-history record row, meets_90,
joint core-7 (without ethnicity) next to core-8, small-cell suppression and the KPI note. Hand-made cases
(tests/fixtures.py tiny_dataset)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd  # noqa: E402

import fixtures  # noqa: E402
from sandbox import codelists, kpi, phenotype, sdc  # noqa: E402
from sandbox.config import PARAMS  # noqa: E402

AUDIT = {"runs": 1, "closed": 1, "pct": 100.0, "open": []}


def snapshot(p=PARAMS):
    """All 11 tiny_dataset patients at 2024-12-31. P01's nationality removed: P01 has the other 7 core variables
    (never smoker, BMI 29.1) but no ethnicity → core-7 yes, core-8 no. P08 has all 8. Only P02 has a family-history
    record (Z83.3). Nobody has a CVD diagnosis."""
    ds = fixtures.tiny_dataset()
    pts = ds.tables["patients"]
    pts.loc[pts["patient_id"] == "P01", "nationality"] = None
    ref = pd.Series(pd.Timestamp("2024-12-31"), index=pts["patient_id"].tolist())
    return phenotype.core_snapshot(ds, ref, None, dict(p))


class TestCompletenessByVariable(unittest.TestCase):
    def setUp(self):
        self.s = snapshot()
        self.t = pd.DataFrame(phenotype.completeness_by_variable(self.s, PARAMS)).set_index("variable")

    def test_rows_and_order(self):
        want = list(codelists.CORE_VARIABLES)
        want.insert(want.index("family_history") + 1, "family_history_recorded")
        self.assertEqual(list(self.t.index), want)
        self.assertTrue((self.t["n"] == 11).all())

    def test_present_absent_is_not_a_fill_rate(self):
        self.assertEqual(int(self.s["cvd"].sum()), 0)                       # no CVD diagnosis at all …
        for v in ("cvd", "hypertension", "family_history"):                 # … still 100%: no record = absent
            r = self.t.loc[v]
            self.assertEqual((r["measure"], r["complete_pct"], r["complete_n"]), ("present_absent", 100.0, 11))
            self.assertEqual(r["meets_90"], "-")                             # not measured (not None: no NaN in the CSV)
            self.assertIn("100% by definition, not a fill rate", r["note"])

    def test_family_history_recorded_row(self):
        r = self.t.loc["family_history_recorded"]
        self.assertEqual((r["measure"], r["complete_n"], r["complete_pct"]), ("recorded", 1, 9.1))   # P02 Z83.3
        self.assertIs(r["meets_90"], False)
        self.assertIn("Z83.3", r["note"])

    def test_recorded_rows_and_meets_90(self):
        self.assertEqual(self.t.loc["sex", "measure"], "recorded")
        self.assertIs(self.t.loc["sex", "meets_90"], True)                  # 11 / 11
        r = self.t.loc["ethnicity"]
        self.assertEqual((r["measure"], r["complete_n"], r["complete_pct"]), ("recorded", 9, 81.8))   # P01, P07
        self.assertIs(r["meets_90"], False)
        self.assertEqual(self.t.loc["family_history_recorded", "note"], phenotype.FH_RECORDED_NOTE)
        self.assertEqual(self.t.loc["sex", "note"], "a value in the record")

    def test_family_history_recorded_when_record_required(self):
        p = dict(PARAMS, c1_require_fh_record=True)                         # D17: no record = missing
        t = pd.DataFrame(phenotype.completeness_by_variable(snapshot(p), p)).set_index("variable")
        r = t.loc["family_history"]
        self.assertEqual((r["measure"], r["complete_n"], r["meets_90"]), ("recorded", 1, False))
        self.assertEqual(phenotype.completeness_measure("cvd", p), "present_absent")

    def test_waist_only_for_lra_2010(self):
        self.assertNotIn("waist (LRS)", self.t.index)
        p = dict(PARAMS, lrs_variant="assessment_2010")
        t = pd.DataFrame(phenotype.completeness_by_variable(snapshot(p), p)).set_index("variable")
        self.assertEqual((t.loc["waist (LRS)", "measure"], t.loc["waist (LRS)", "complete_n"]), ("recorded", 0))


class TestJointCompleteness(unittest.TestCase):
    def test_core7_without_ethnicity(self):
        s = snapshot()
        cols = [f"ok_{v}" for v in phenotype.CORE7_VARIABLES]
        self.assertNotIn("ok_ethnicity", cols)
        self.assertEqual(len(cols), 7)
        self.assertTrue(s["ok_core7"].equals(s[cols].all(axis=1)))
        self.assertTrue(s.loc["P01", "ok_core7"] and not s.loc["P01", "ok_core8"])   # only ethnicity missing
        self.assertTrue(s.loc["P08", "ok_core8"])
        self.assertFalse((s["ok_core8"] & ~s["ok_core7"]).any())             # core-8 = core-7 + ethnicity
        j = phenotype.joint_completeness(s)
        self.assertEqual({k: j[k] for k in ("n", "joint_core7_n", "joint_core8_n")},
                         {"n": 11, "joint_core7_n": 2, "joint_core8_n": 1})
        self.assertEqual((j["joint_core7_pct"], j["joint_core8_pct"]), (18.2, 9.1))

    def test_small_cells_suppressed(self):
        j = pd.DataFrame([{"cohort": "c1", **phenotype.joint_completeness(snapshot())}])
        out = sdc.suppress_count_rate_pairs(j, "n", [(f"joint_{k}_n", f"joint_{k}_pct") for k in ("core7", "core8")])
        self.assertEqual(out.loc[0, "joint_core7_n"], "<10")
        self.assertEqual(out.loc[0, "joint_core7_pct"], "suppressed (<10)")  # 18.2% of 11 would give the count
        self.assertEqual(out.loc[0, "n"], 11)

    def test_rate_suppressed_when_few_missing(self):
        df = pd.DataFrame({"n": [100, 100, 100, 5], "k": [95, 50, 0, 5], "pct": [95.0, 50.0, 0.0, 100.0]})
        out = sdc.suppress_count_rate_pairs(df, "n", [("k", "pct")])
        self.assertEqual(out["pct"].tolist(), ["suppressed (<10)", 50.0, 0.0, "suppressed (<10)"])   # 5 missing; 5 of 5
        self.assertEqual(out["k"].tolist(), [95, 50, 0, "<10"])
        self.assertEqual(out["n"].tolist(), [100, 100, 100, "<10"])


def nb0():
    """NB0 kpi_values: ethnicity 0% in both cohorts; without it C1's weakest is smoking 92%; C2 joint core-7 8 / 20."""
    return {"data_completeness_min_core8_pct": {"c1": 0.0, "c2": 0.0},
            "data_completeness_weakest": {"c1": "ethnicity", "c2": "ethnicity"},
            "data_completeness_without_ethnicity": {
                "c1": {"variable": "smoking", "pct": 92.0, "complete_n": 920, "n": 1000},
                "c2": {"variable": "smoking", "pct": 14.5, "complete_n": 372, "n": 2564}},
            "joint_core7": {"c1": {"pct": 90.0, "core7_n": 900, "n": 1000},
                            "c2": {"pct": 40.0, "core7_n": 8, "n": 20}},
            "completeness_present_absent": ["family_history", "cvd", "hypertension"],
            "framework_match": True, "framework_missing_groups": []}


class TestKpiCompletenessNote(unittest.TestCase):
    def test_note_and_unchanged_value(self):
        r = kpi.build(nb0(), {}, {}, {}, AUDIT).set_index("kpi").loc["Data Completeness for Required Variables"]
        self.assertEqual((r["actual"], r["met"]), ("C1 0.0%; C2 0.0%", "Not Met"))   # min over the 8, as before
        self.assertIn("Weakest variable: C1 ethnicity 0.0%; C2 ethnicity 0.0%", r["notes"])
        self.assertIn("Without ethnicity (weakest of the other 7): C1 smoking 92.0%; C2 smoking 14.5%", r["notes"])
        self.assertIn("Joint core-7 (all but ethnicity): C1 90.0% (N=900/1000); C2 suppressed (<10) (N=<10/20)",
                      r["notes"])
        self.assertIn("Present / absent, 100% by definition (not a fill rate): family_history, cvd, hypertension",
                      r["notes"])

    def test_note_from_an_older_nb0_run(self):
        old = {k: v for k, v in nb0().items() if k in ("data_completeness_min_core8_pct", "data_completeness_weakest",
                                                       "framework_match", "framework_missing_groups")}
        r = kpi.build(old, {}, {}, {}, AUDIT).set_index("kpi").loc["Data Completeness for Required Variables"]
        self.assertEqual(r["notes"], "Weakest variable: C1 ethnicity 0.0%; C2 ethnicity 0.0%")


if __name__ == "__main__":
    unittest.main()
