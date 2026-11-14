"""QDiabetes-2018 A ve Leicester skoru testleri.

Referans değerler: CRAN 'QDiabetes' R paketi README örnekleri (QDR2018A, tds=0 varsayılan).
LPRS (Gray et al., Diabetologia 2012;55:959–966): katsayılardan elle hesaplanmış vakalar
(0.0408359·yaş + 0.1839942·erkek + 0.7565977·BME + 0.0820698·BMI + 0.4770517·FH + 0.5498978·antiHT).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sandbox.config import PARAMS  # noqa: E402
from sandbox.scores import lprs, lrs, qdiabetes2018a as qd  # noqa: E402


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
             bmi=31, htn_lrs=True, htn_med=True)
    d.update(kw)
    return pd.DataFrame([d])


P2010 = dict(PARAMS, lrs_variant="assessment_2010")
P2012 = dict(PARAMS, lrs_variant="practice_2012")


class TestLPRS(unittest.TestCase):
    """Leicester Practice Risk Score — elle hesaplanmış referanslar (6 ondalık)."""

    def test_reference_full(self):
        # 0.0408359·62 = 2.5318258; 0.0820698·31 = 2.5441638
        # 2.5318258 + 0.1839942 + 0.7565977 + 2.5441638 + 0.4770517 + 0.5498978 = 7.0435310
        r = lrs.score(_snap(), p=P2012).iloc[0]
        self.assertAlmostEqual(r["lrs_score"], 7.0435310, places=6)
        self.assertEqual(r["lrs_variant"], "practice_2012")
        self.assertTrue(r["lrs_computable"])

    def test_reference_minimum_inputs(self):
        # kadın, 40, beyaz, FH yok, BMI 22, ilaç yok: 0.0408359·40 + 0.0820698·22 = 1.633436 + 1.8055356
        r = lrs.score(_snap(sex="Female", age=40, ethnicity="Western", family_history=False, bmi=22,
                            htn_lrs=False, htn_med=False), p=P2012).iloc[0]
        self.assertAlmostEqual(r["lrs_score"], 3.4389716, places=6)

    def test_reference_mixed(self):
        # kadın, 55, Hint (BME), FH yok, BMI 27.5, antihipertansif:
        # 2.2459745 + 0.7565977 + 2.2569195 + 0.5498978 = 5.8093895
        r = lrs.score(_snap(sex="Female", age=55, ethnicity="Indian", family_history=False, bmi=27.5,
                            htn_med=True), p=P2012).iloc[0]
        self.assertAlmostEqual(r["lrs_score"], 5.8093895, places=6)
        self.assertAlmostEqual(r["lrs_ethnicity"], 0.7565977, places=7)

    def test_waist_not_required(self):
        r = lrs.score(_snap(waist_cm=np.nan), p=P2012).iloc[0]
        self.assertTrue(r["lrs_computable"])
        self.assertAlmostEqual(r["lrs_score"], 7.0435310, places=6)

    def test_htn_diagnosis_alone_not_an_input(self):
        # LPRS yalnız antihipertansif ilacı kullanır; HT tanısı (htn_lrs) tek başına katkı vermez
        r = lrs.score(_snap(htn_lrs=True, htn_med=False), p=P2012).iloc[0]
        self.assertAlmostEqual(r["lrs_score"], 7.0435310 - 0.5498978, places=6)

    def test_missing_inputs(self):
        r = lrs.score(_snap(bmi=np.nan), p=P2012).iloc[0]
        self.assertTrue(np.isnan(r["lrs_score"]))
        self.assertIn("bmi_missing", r["lrs_missing"])
        r = lrs.score(_snap(ethnicity="Not recorded"), p=P2012).iloc[0]
        self.assertFalse(r["lrs_computable"])
        self.assertIn("ethnicity", r["lrs_missing"])
        r = lrs.score(_snap(sex="Unknown"), p=P2012).iloc[0]
        self.assertIn("sex", r["lrs_missing"])

    def test_threshold_pending_and_set(self):
        snaps = pd.concat([_snap(), _snap(sex="Female", age=40, ethnicity="Western", family_history=False,
                                          bmi=22, htn_med=False)], ignore_index=True)
        pending = lrs.score(snaps, p=dict(P2012, lprs_high_risk_threshold=None))
        self.assertTrue(pending["lrs_high_risk"].isna().all())
        flagged = lrs.score(snaps, p=dict(P2012, lprs_high_risk_threshold=6.5))
        self.assertEqual(list(flagged["lrs_high_risk"]), [True, False])

    def test_dev_age_flag(self):
        r = lrs.score(pd.concat([_snap(age=30), _snap(age=40), _snap(age=75), _snap(age=76)],
                                ignore_index=True), p=P2012)
        self.assertEqual(list(r["lrs_outside_dev_age"]), [True, False, False, True])


class TestLeicesterVariant(unittest.TestCase):
    def test_default_is_practice_2012(self):
        # [KARAR: 2026-11-14] K-LRS (b): varsayılan bel çevresiz LPRS
        self.assertEqual(PARAMS["lrs_variant"], "practice_2012")
        self.assertFalse(lrs.needs_waist(PARAMS))
        self.assertIsNone(lrs.threshold(PARAMS))
        self.assertEqual(lrs.score(_snap()).iloc[0]["lrs_variant"], "practice_2012")

    def test_assessment_2010_selectable(self):
        self.assertTrue(lrs.needs_waist(P2010))
        self.assertEqual(lrs.threshold(P2010), 16)
        r = lrs.score(_snap(), p=P2010).iloc[0]
        self.assertEqual(r["lrs_score"], 37)
        self.assertEqual(r["lrs_variant"], "assessment_2010")

    def test_unknown_variant(self):
        with self.assertRaises(ValueError):
            lrs.score(_snap(), p=dict(PARAMS, lrs_variant="waist_zero"))


class TestLRS(unittest.TestCase):
    """LRA 2010 (bel çevresi zorunlu) — lrs_variant = "assessment_2010"."""

    def test_full_example(self):
        # yaş 60–69: 9, erkek: 1, beyaz değil: 6, FH: 5, bel 100–109.9: 6, BMI 30–34.9: 5, HT: 5 → 37
        r = lrs.score_assessment_2010(_snap()).iloc[0]
        self.assertEqual(r["lrs_score"], 37)
        self.assertEqual(r["lrs_category"], "high")
        self.assertTrue(r["lrs_high_risk"])

    def test_minimum_and_bands(self):
        r = lrs.score_assessment_2010(_snap(sex="Female", age=40, ethnicity="Western", family_history=False,
                                           waist_cm=80, bmi=22, htn_lrs=False)).iloc[0]
        self.assertEqual(r["lrs_score"], 0)
        self.assertEqual(r["lrs_category"], "low")
        self.assertEqual(lrs.score_assessment_2010(_snap(age=50)).iloc[0]["lrs_age"], 5)
        self.assertEqual(lrs.score_assessment_2010(_snap(age=70)).iloc[0]["lrs_age"], 13)
        self.assertEqual(lrs.score_assessment_2010(_snap(waist_cm=90)).iloc[0]["lrs_waist"], 4)
        self.assertEqual(lrs.score_assessment_2010(_snap(bmi=35)).iloc[0]["lrs_bmi"], 8)

    def test_missing_waist_is_nan(self):
        r = lrs.score_assessment_2010(_snap(waist_cm=np.nan)).iloc[0]
        self.assertTrue(np.isnan(r["lrs_score"]))
        self.assertIn("waist_missing", r["lrs_missing"])

    def test_max_47(self):
        r = lrs.score_assessment_2010(_snap(age=80, waist_cm=120, bmi=40)).iloc[0]
        self.assertEqual(r["lrs_score"], lrs.MAX_SCORE)


if __name__ == "__main__":
    unittest.main()
