"""Kol 2 — QDiabetes'in UAE'ye yeniden kalibrasyonu.

QDiabetes bir Cox modelidir: p(t) = 1 − S0(t)^exp(lp). Recalibration lp'yi (prediktör yapısı ve
göreli ağırlıklar) korur, yalnızca UAE verisinden horizon'daki baseline survival'ı yeniden tahmin eder.

- "baseline": eğim 1 sabit (lp offset), S0(h) Breslow ile → seviye (calibration-in-the-large) düzelir.
- "baseline_slope": önce Cox ile lp eğimi β, sonra β·lp ile Breslow S0(h) → seviye + yayılım düzelir.
Hiçbiri sıralamayı (C-index) değiştirmez — bu Kol 2'nin teşhis değeridir.
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
    """Katman (ör. cinsiyet) başına ayrı recalibration. QDiabetes kadın/erkek için ayrı baseline
    survival kullandığından Kol 2 de cinsiyete göre katmanlı yapılmalıdır; aksi halde katmanlar arası
    sıralama değişir."""
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
