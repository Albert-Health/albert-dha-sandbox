"""QDiabetes-2018 A ve LRS testleri.

Referans değerler: CRAN 'QDiabetes' R paketi README örnekleri (QDR2018A, tds=0 varsayılan).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sandbox.scores import lrs, qdiabetes2018a as qd  # noqa: E402


def qd_risk(sex, age, bmi, years=10, **kw):
    d = dict(sex=sex, age=age, bmi=bmi, ethn_qd="WhiteNA", smoke_cat=0, townsend=0.0,
             **{k: False for k in qd.BINARY})
    d.update(kw)
    df = pd.DataFrame([d])
    return 100 * qd.risk(qd.linear_predictor(df), df["sex"], years).iloc[0]


class TestQDiabetesReference(unittest.TestCase):
    """±0.01 yüzde puan."""

    def test_male_45_bmi35(self):
        self.assertAlmostEqual(qd_risk("Male", 45, 35), 9.88593, delta=0.01)

    def test_female_bmi35_ages(self):
        expected = [1.085179, 2.921454, 5.893499, 9.082108, 10.713717, 9.567516]
        for age, exp in zip(range(25, 76, 10), expected):
            with self.subTest(age=age):
                self.assertAlmostEqual(qd_risk("Female", age, 35), exp, delta=0.01)


class TestQDiabetesBehaviour(unittest.TestCase):
    def test_directions(self):
        base_f = qd_risk("Female", 50, 30)
        base_m = qd_risk("Male", 50, 30)
        for flag in ["fhdm", "htn", "cvd", "ster", "apsy", "stat", "learn", "psy"]:
            with self.subTest(flag=flag):
                self.assertGreater(qd_risk("Female", 50, 30, **{flag: True}), base_f)
                self.assertGreater(qd_risk("Male", 50, 30, **{flag: True}), base_m)
        self.assertGreater(qd_risk("Female", 50, 30, gdm=True), base_f)
        self.assertGreater(qd_risk("Female", 50, 30, pcos=True), base_f)
        self.assertGreater(qd_risk("Male", 50, 30, ethn_qd="Bangladeshi"), base_m)
        self.assertGreater(qd_risk("Male", 50, 30, smoke_cat=4), qd_risk("Male", 50, 30, smoke_cat=1))

    def test_bmi_clamped_and_age_range(self):
        self.assertAlmostEqual(qd_risk("Male", 50, 45), qd_risk("Male", 50, 40), places=10)
        self.assertAlmostEqual(qd_risk("Male", 50, 15), qd_risk("Male", 50, 20), places=10)
        self.assertTrue(np.isnan(qd_risk("Male", 24, 30)))
        self.assertTrue(np.isnan(qd_risk("Male", 85, 30)))

    def test_horizon_scaling(self):
        r10, r5 = qd_risk("Male", 50, 30, 10), qd_risk("Male", 50, 30, 5)
        self.assertLess(r5, r10)
        s = (1 - r10 / 100) ** 0.5            # S(5) = S(10)^(5/10) power varsayımı
        self.assertAlmostEqual(r5, 100 * (1 - s), places=8)


def _snap(**kw):
    d = dict(sex="Male", age=62, ethnicity="Emirati", family_history=True, waist_cm=104,
             bmi=31, htn_lrs=True)
    d.update(kw)
    return pd.DataFrame([d])


class TestLRS(unittest.TestCase):
    def test_full_example(self):
        # yaş 60–69: 9, erkek: 1, beyaz değil: 6, FH: 5, bel 100–109.9: 6, BMI 30–34.9: 5, HT: 5 → 37
        r = lrs.score(_snap()).iloc[0]
        self.assertEqual(r["lrs_score"], 37)
        self.assertEqual(r["lrs_category"], "high")
        self.assertTrue(r["lrs_high_risk"])

    def test_minimum_and_bands(self):
        r = lrs.score(_snap(sex="Female", age=40, ethnicity="Western", family_history=False,
                            waist_cm=80, bmi=22, htn_lrs=False)).iloc[0]
        self.assertEqual(r["lrs_score"], 0)
        self.assertEqual(r["lrs_category"], "low")
        self.assertEqual(lrs.score(_snap(age=50)).iloc[0]["lrs_age"], 5)
        self.assertEqual(lrs.score(_snap(age=70)).iloc[0]["lrs_age"], 13)
        self.assertEqual(lrs.score(_snap(waist_cm=90)).iloc[0]["lrs_waist"], 4)
        self.assertEqual(lrs.score(_snap(bmi=35)).iloc[0]["lrs_bmi"], 8)

    def test_missing_waist_is_nan(self):
        r = lrs.score(_snap(waist_cm=np.nan)).iloc[0]
        self.assertTrue(np.isnan(r["lrs_score"]))
        self.assertIn("waist_missing", r["lrs_missing"])

    def test_max_47(self):
        r = lrs.score(_snap(age=80, waist_cm=120, bmi=40)).iloc[0]
        self.assertEqual(r["lrs_score"], lrs.MAX_SCORE)


if __name__ == "__main__":
    unittest.main()
