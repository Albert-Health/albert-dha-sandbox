"""Metrik ve recalibration testleri — kaba kuvvet referanslar ve simülasyon."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from sandbox import metrics, recalibration  # noqa: E402


def brute_c(t, e, r):
    num = den = 0.0
    for i in range(len(t)):
        if not e[i]:
            continue
        for j in range(len(t)):
            if t[j] > t[i]:
                den += 1
                num += 1.0 if r[i] > r[j] else 0.5 if r[i] == r[j] else 0.0
    return num / den


def simulate(n=4000, beta=0.8, lam=0.05, cens=0.08, seed=1):
    """Cox: h(t|x) = lam·exp(beta·x), üstel; bağımsız üstel sansür."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    t_ev = rng.exponential(1 / (lam * np.exp(beta * x)))
    t_c = rng.exponential(1 / cens, n)
    t = np.minimum(t_ev, t_c)
    e = t_ev <= t_c
    return t, e, x


class TestKM(unittest.TestCase):
    def test_hand_example(self):
        t = np.array([1, 2, 2, 3, 4, 5.0])
        e = np.array([1, 1, 0, 1, 0, 1], bool)
        times, s = metrics.kaplan_meier(t, e)
        # 6 risk, 1 olay → 5/6; t=2: 5 risk, 1 olay → 5/6·4/5; t=3: 3 risk → ·2/3; t=5: 1 risk → 0
        np.testing.assert_allclose(s, [5 / 6, 2 / 3, 4 / 9, 0.0])
        self.assertAlmostEqual(metrics.km_risk(t, e, 2.5), 1 - 2 / 3)


class TestDiscrimination(unittest.TestCase):
    def test_c_index_matches_brute_force(self):
        rng = np.random.default_rng(3)
        t = np.round(rng.exponential(5, 300), 1)          # zaman bağları dahil
        e = rng.random(300) < 0.6
        r = np.round(rng.normal(size=300) - 0.2 * t, 1)   # risk bağları dahil
        self.assertAlmostEqual(metrics.c_index(t, e, r), brute_c(t, e, r), places=12)

    def test_c_index_perfect_and_random(self):
        t, e, x = simulate(2000)
        self.assertAlmostEqual(metrics.c_index(t, np.ones_like(e), -t), 1.0)
        self.assertAlmostEqual(metrics.c_index(t, e, np.random.default_rng(0).normal(size=len(t))), 0.5, delta=0.03)

    def test_auc_uncensored_matches_mann_whitney(self):
        rng = np.random.default_rng(5)
        t = rng.exponential(5, 500)
        r = rng.normal(size=500) - 0.1 * t
        h = 4.0
        auc = metrics.time_dependent_auc(t, np.ones(500, bool), r, h)
        cases, ctrls = r[t <= h], r[t > h]
        mw = np.mean([(c > k) + 0.5 * (c == k) for c in cases for k in ctrls])
        self.assertAlmostEqual(auc, mw, places=12)

    def test_auc_ipcw_consistent_under_censoring(self):
        t, e, x = simulate(20000, cens=0.0001, seed=7)
        full = metrics.time_dependent_auc(t, e, x, 5)
        t2, e2, x2 = simulate(20000, cens=0.1, seed=7)
        self.assertAlmostEqual(metrics.time_dependent_auc(t2, e2, x2, 5), full, delta=0.02)


class TestCalibration(unittest.TestCase):
    def test_cox_recovers_beta(self):
        t, e, x = simulate(8000, beta=0.8)
        b, se = metrics.cox_1d(t, e, x)
        self.assertAlmostEqual(b, 0.8, delta=4 * se)

    def test_true_model_is_calibrated(self):
        beta, lam, h = 0.8, 0.05, 5.0
        t, e, x = simulate(20000, beta=beta, lam=lam)
        p = 1 - np.exp(-lam * h * np.exp(beta * x))
        oe = metrics.observed_expected(t, e, p, h)["oe_ratio"]
        self.assertAlmostEqual(oe, 1.0, delta=0.05)
        self.assertAlmostEqual(metrics.calibration_slope(t, e, p, h), 1.0, delta=0.08)

    def test_threshold_metrics_uncensored(self):
        t = np.array([1, 2, 6, 7, 8.0]); e = np.ones(5, bool); s = np.array([0.9, 0.2, 0.8, 0.1, 0.1])
        m = metrics.threshold_metrics(t, e, s, 0.5, horizon=5)
        # vakalar (t≤5): 0.9 pos, 0.2 neg → sens 0.5; kontroller: 0.8 pos, 0.1, 0.1 neg → spec 2/3
        self.assertAlmostEqual(m["sensitivity"], 0.5)
        self.assertAlmostEqual(m["specificity"], 2 / 3)
        self.assertAlmostEqual(m["ppv"], 0.5)
        self.assertAlmostEqual(m["alert_rate_per_1000"], 400)


class TestRecalibration(unittest.TestCase):
    def test_baseline_recalibration_fixes_level(self):
        beta, lam, h = 0.8, 0.05, 5.0
        t, e, x = simulate(20000, beta=beta, lam=lam)
        lp = beta * x
        wrong = 1 - np.exp(-3 * lam * h * np.exp(lp))         # 3× fazla tahmin
        self.assertLess(metrics.observed_expected(t, e, wrong, h)["oe_ratio"], 0.6)
        m = recalibration.fit(t, e, lp, h, "baseline")
        self.assertAlmostEqual(m["s0_h"], np.exp(-lam * h), delta=0.01)
        p = recalibration.predict(m, lp)
        self.assertAlmostEqual(metrics.observed_expected(t, e, p, h)["oe_ratio"], 1.0, delta=0.05)
        # sıralama değişmez
        self.assertAlmostEqual(metrics.c_index(t, e, p), metrics.c_index(t, e, wrong), places=12)

    def test_slope_recalibration(self):
        t, e, x = simulate(20000, beta=0.8)
        m = recalibration.fit(t, e, 2.0 * x, 5.0, "baseline_slope")   # lp 2× abartılı
        self.assertAlmostEqual(m["beta"], 0.4, delta=0.05)


class TestBootstrap(unittest.TestCase):
    def test_ci_contains_estimate(self):
        t, e, x = simulate(1500)
        est = metrics.c_index(t, e, x)
        lo, hi = metrics.bootstrap_ci(lambda i: metrics.c_index(t[i], e[i], x[i]), len(t), 50, 1)
        self.assertLess(lo, est)
        self.assertGreater(hi, est)


if __name__ == "__main__":
    unittest.main()
