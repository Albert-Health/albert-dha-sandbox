"""Arm 2 — recalibration of QDiabetes to the UAE.

QDiabetes is a Cox model: p(t) = 1 − S0(t)^exp(lp). Recalibration keeps lp (predictor structure and
relative weights) and only re-estimates the baseline survival at the horizon from UAE data.

- "baseline": slope fixed at 1 (lp offset), S0(h) via Breslow → fixes the level (calibration-in-the-large).
- "baseline_slope": first the lp slope β via Cox, then Breslow S0(h) with β·lp → fixes level + spread.
Neither changes the ranking (C-index) — that is Arm 2's diagnostic value.
"""
from __future__ import annotations

import numpy as np

from . import metrics


def breslow_baseline_survival(time, event, lp, horizon: float) -> float:
    """S0(h) = exp(−H0(h)), H0(h) = Σ_{u≤h} d_u / Σ_{T_j≥u} exp(lp_j)."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    ex = np.exp(np.asarray(lp, float))
    order = np.argsort(t, kind="mergesort")
    t, e, ex = t[order], e[order], ex[order]
    risk_sum = np.cumsum(ex[::-1])[::-1]
    uniq, d = np.unique(t[e & (t <= horizon)], return_counts=True)
    first = np.searchsorted(t, uniq, side="left")
    h0 = np.sum(d / risk_sum[first])
    return float(np.exp(-h0))


def fit(time, event, lp, horizon: float, method: str = "baseline") -> dict:
    lp = np.asarray(lp, float)
    tt, ee = metrics.truncate(time, event, horizon)
    beta = 1.0
    if method == "baseline_slope":
        beta, _ = metrics.cox_1d(tt, ee, lp)
    elif method != "baseline":
        raise ValueError(method)
    s0 = breslow_baseline_survival(tt, ee, beta * lp, horizon)
    return {"method": method, "horizon": horizon, "beta": float(beta), "s0_h": s0}


def predict(model: dict, lp) -> np.ndarray:
    lp = np.asarray(lp, float)
    return 1.0 - model["s0_h"] ** np.exp(model["beta"] * lp)


def fit_stratified(time, event, lp, strata, horizon: float, method: str = "baseline") -> dict:
    """Separate recalibration per stratum (e.g. sex). QDiabetes uses separate baseline survival for
    women/men, so Arm 2 must also be stratified by sex; otherwise the ranking across strata
    changes."""
    t, e, lp, s = (np.asarray(a) for a in (time, event, lp, strata))
    return {str(k): fit(t[s == k], e[s == k].astype(bool), lp[s == k].astype(float), horizon, method)
            for k in np.unique(s)}


def predict_stratified(models: dict, lp, strata) -> np.ndarray:
    lp, s = np.asarray(lp, float), np.asarray(strata).astype(str)
    out = np.full(len(lp), np.nan)
    for k, m in models.items():
        idx = s == k
        out[idx] = predict(m, lp[idx])
    return out
