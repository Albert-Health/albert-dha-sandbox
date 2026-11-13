"""Kohort kuralları için birim testleri (stdlib unittest — enclave'de pytest gerekmez).

Çalıştırma:  python -m unittest discover -s tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pandas as pd  # noqa: E402

from fixtures import tiny_dataset  # noqa: E402
from sandbox import cohorts, phenotype, sdc  # noqa: E402
from sandbox.io import schema  # noqa: E402


class TestC3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = tiny_dataset()
        cls.res = cohorts.build_c3(cls.ds)
        cls.c3 = cls.res["cohort"]

    def test_membership(self):
        self.assertEqual(sorted(self.c3.index), ["P01", "P02", "P07"])

    def test_index_dates(self):
        self.assertEqual(self.c3.loc["P01", "index_date"], pd.Timestamp("2019-03-01"))
        self.assertEqual(self.c3.loc["P02", "baseline_lab_type"], "fpg")

    def test_incident_lab(self):
        r = self.c3.loc["P01"]
        self.assertTrue(r["incident_diabetes"])
        self.assertEqual(r["incident_evidence"], "lab_hba1c")
        self.assertEqual(r["incident_date"], pd.Timestamp("2021-05-01"))

    def test_censoring_at_last_glycaemic(self):
        r = self.c3.loc["P02"]
        self.assertFalse(r["incident_diabetes"])
        self.assertEqual(r["followup_end"], pd.Timestamp("2022-02-01"))

    def test_medication_only_is_sensitivity(self):
        r = self.c3.loc["P07"]
        self.assertFalse(r["incident_diabetes"])
        self.assertTrue(r["incident_diabetes_incl_med"])

    def test_bmi_from_height_weight(self):
        r = self.c3.loc["P02"]
        self.assertEqual(r["bmi_source"], "height_weight")
        self.assertAlmostEqual(r["bmi"], 64 / 1.6 ** 2, places=3)

    def test_family_history_flag(self):
        self.assertTrue(self.c3.loc["P02", "family_history"])
        self.assertFalse(self.c3.loc["P01", "family_history"])

    def test_funnel_monotonic(self):
        f = self.res["funnel"]
        seq = [f["with_normal_hba1c_or_fpg"], f["after_t1d_exclusion"],
               f["after_prevalent_dm_pre_exclusion"], f["after_age_25_84"],
               f["after_followup_measurement"], f["c3_final"]]
        self.assertEqual(seq, sorted(seq, reverse=True))


class TestPositivePool(unittest.TestCase):
    def test_pool(self):
        ds = tiny_dataset()
        pool = cohorts.positive_pool(ds)
        self.assertIn("P08", pool.index)
        self.assertEqual(pool.loc["P08", "status"], "T2DM")
        self.assertEqual(pool.loc["P09", "status"], "Prediabetes")
        self.assertNotIn("P05", pool.index)          # T1D hariç
        self.assertNotIn("P07", pool.index)          # yalnızca A10 → statü tanımlamaz

    def test_c1_completeness(self):
        sel = cohorts.build_c1_c2(tiny_dataset())
        self.assertIn("P08", sel["c1_ids"])          # 8 değişken tam
        self.assertNotIn("P09", sel["c1_ids"])       # sigara yok
        self.assertIn("P09", sel["c2_ids"])


class TestSchema(unittest.TestCase):
    def test_roundtrip_and_validate(self):
        ds = tiny_dataset()
        ds.source, ds.cohort = "test", "c3"
        with tempfile.TemporaryDirectory() as tmp:
            schema.write_dataset(ds, Path(tmp))
            back = schema.read_dataset(Path(tmp), "test", "c3")
        self.assertEqual(len(back["labs"]), len(ds["labs"]))
        rep = schema.validate(back)
        self.assertFalse((rep["severity"] == "ERROR").any(), rep[rep["severity"] == "ERROR"])

    def test_ifcc_conversion(self):
        ds = tiny_dataset()
        extra = schema.coerce(pd.DataFrame([("P01", "4548-4", "HbA1c", 48, "mmol/mol", "2020-01-01")],
                                           columns=["patient_id", "loinc", "test_name", "value", "unit", "date"]), "labs")
        ds.tables["labs"] = pd.concat([ds["labs"], extra], ignore_index=True)
        g = phenotype.glycaemic_events(ds)
        v = g[(g["patient_id"] == "P01") & (g["date"] == "2020-01-01")]["value"].iloc[0]
        self.assertAlmostEqual(v, 48 / 10.929 + 2.15, places=3)


class TestSDC(unittest.TestCase):
    def test_suppress(self):
        df = pd.DataFrame({"n": [0, 3, 10, 250]})
        out = sdc.suppress_small_counts(df, ["n"], threshold=10)
        self.assertEqual(list(out["n"]), [0, "<10", 10, 250])


if __name__ == "__main__":
    unittest.main()
