"""Sansürlü (time-to-event) veri için performans metrikleri — yalnızca numpy/pandas.

Konvansiyon: time = yıl cinsinden takip süresi, event = birincil outcome (bool),
risk = tahmin edilen olasılık (0–1) veya sıralama skoru (C-index / AUROC için).
Horizon h'de değerlendirirken önce `truncate(time, event, h)` uygulanır (idari sansür).

Seçilen yöntemler (belgelendi):
- C-index: Harrell; karşılaştırılabilir çift = olaylı i ve T_j > T_i (eşit zamanlar karşılaştırılmaz);
  risk eşitliği 0.5.
- Zaman-bağımlı AUROC(h): cumulative/dynamic, IPCW (Uno 2007; Hung & Chiang 2010) — vakalar
  T ≤ h ve olay, ağırlık 1/G(T−); kontroller T > h, ağırlık 1/G(h); G = sansür KM'si.
- Gözlenen risk: 1 − KM(h). O:E = gözlenen / ortalama tahmin.
- Kalibrasyon eğimi: Cox PH (Breslow) ile time ~ cloglog(p_h) tek değişkenli Newton-Raphson; ideal 1.
- Eşik metrikleri (sens/spec/PPV/NPV/F1): IPCW ağırlıklı 2×2; alert rate = eşik üstü oranı × 1000.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def truncate(time, event, horizon: float):
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    return np.minimum(t, horizon), e & (t <= horizon)


# --------------------------------------------------------------------------
# Kaplan–Meier
# --------------------------------------------------------------------------
def kaplan_meier(time, event):
    """Dönüş: (olay zamanları, o zamanlardaki S(t)) — sağdan sürekli basamak fonksiyonu."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    ts = np.sort(t)
    uniq, d = np.unique(t[e], return_counts=True)
    n_risk = len(t) - np.searchsorted(ts, uniq, side="left")
    surv = np.cumprod(1.0 - d / n_risk)
    return uniq, surv


def step_at(times, surv, t, left: bool = False):
    """S(t) (left=True → S(t−)). Vektörize."""
    t = np.atleast_1d(np.asarray(t, float))
    idx = np.searchsorted(times, t, side="left" if left else "right") - 1
    out = np.where(idx >= 0, surv[np.clip(idx, 0, None)] if len(surv) else 1.0, 1.0)
    return out


def km_risk(time, event, horizon: float) -> float:
    times, surv = kaplan_meier(time, event)
    return float(1.0 - step_at(times, surv, horizon)[0])


def _censoring_weights(time, event, horizon):
    """IPCW: vakalar 1/G(T−), kontroller 1/G(h), diğerleri 0."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    gt, gs = kaplan_meier(t, ~e)
    case = e & (t <= horizon)
    ctrl = t > horizon
    w = np.zeros(len(t))
    g_case = step_at(gt, gs, t[case], left=True)
    w[case] = 1.0 / np.clip(g_case, 1e-12, None)
    g_h = step_at(gt, gs, horizon)[0]
    w[ctrl] = 1.0 / max(g_h, 1e-12)
    return case, ctrl, w


# --------------------------------------------------------------------------
# Ayrım gücü
# --------------------------------------------------------------------------
def c_index(time, event, risk) -> float:
    """Harrell C (Fenwick ağacı, O(n log n))."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    r = np.asarray(risk, float)
    ok = ~(np.isnan(t) | np.isnan(r))
    t, e, r = t[ok], e[ok], r[ok]
    if e.sum() == 0:
        return float("nan")
    ranks = np.unique(r, return_inverse=True)[1] + 1
    m = ranks.max()
    tree = [0] * (m + 1)

    def add(i):
        while i <= m:
            tree[i] += 1
            i += i & -i

    def query(i):  # # eleman rank ≤ i
        s = 0
        while i > 0:
            s += tree[i]
            i -= i & -i
        return s

    order = np.argsort(-t, kind="mergesort")
    ts, es, rs = t[order], e[order], ranks[order]
    conc = ties = total = 0.0
    inserted = 0
    i = 0
    n = len(ts)
    while i < n:
        j = i
        while j < n and ts[j] == ts[i]:
            j += 1
        # grup [i, j): aynı zaman. Ağaçta yalnızca daha uzun zamanlılar var.
        for k in range(i, j):
            if es[k] and inserted:
                less = query(int(rs[k]) - 1)
                eq = query(int(rs[k])) - less
                conc += less
                ties += eq
                total += inserted
        for k in range(i, j):
            add(int(rs[k]))
            inserted += 1
        i = j
    return float((conc + 0.5 * ties) / total) if total else float("nan")


def time_dependent_auc(time, event, risk, horizon: float) -> float:
    t = np.asarray(time, float)
    r = np.asarray(risk, float)
    ok = ~(np.isnan(t) | np.isnan(r))
    t, e, r = t[ok], np.asarray(event, bool)[ok], r[ok]
    case, ctrl, w = _censoring_weights(t, e, horizon)
    if case.sum() == 0 or ctrl.sum() == 0:
        return float("nan")
    rc = np.sort(r[ctrl])
    less = np.searchsorted(rc, r[case], side="left")
    eq = np.searchsorted(rc, r[case], side="right") - less
    frac = (less + 0.5 * eq) / len(rc)
    return float(np.sum(w[case] * frac) / np.sum(w[case]))


# --------------------------------------------------------------------------
# Kalibrasyon
# --------------------------------------------------------------------------
def cox_1d(time, event, x, max_iter: int = 50, tol: float = 1e-9):
    """Tek değişkenli Cox PH (Breslow bağları). Dönüş: (beta, se)."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    x = np.asarray(x, float)
    order = np.argsort(t, kind="mergesort")
    t, e, x = t[order], e[order], x[order]
    first = np.searchsorted(t, t, side="left")      # risk seti başlangıcı (T_j ≥ T_i)
    ev = np.where(e)[0]
    beta = 0.0
    se = float("nan")
    for _ in range(max_iter):
        ex = np.exp(np.clip(beta * x, -700, 700))
        s0 = np.cumsum((ex)[::-1])[::-1]
        s1 = np.cumsum((x * ex)[::-1])[::-1]
        s2 = np.cumsum((x * x * ex)[::-1])[::-1]
        f = first[ev]
        m1 = s1[f] / s0[f]
        grad = np.sum(x[ev] - m1)
        info = np.sum(s2[f] / s0[f] - m1 ** 2)
        if info <= 0:
            break
        step = grad / info
        beta += step
        se = 1.0 / np.sqrt(info)
        if abs(step) < tol:
            break
    return float(beta), float(se)


def cloglog(p):
    p = np.clip(np.asarray(p, float), 1e-12, 1 - 1e-12)
    return np.log(-np.log(1.0 - p))


def calibration_slope(time, event, p_h, horizon: float) -> float:
    tt, ee = truncate(time, event, horizon)
    return cox_1d(tt, ee, cloglog(p_h))[0]


def observed_expected(time, event, p_h, horizon: float) -> dict:
    obs = km_risk(time, event, horizon)
    exp_ = float(np.nanmean(p_h))
    return {"observed_risk": obs, "expected_risk": exp_, "oe_ratio": obs / exp_ if exp_ > 0 else float("nan")}


def calibration_table(time, event, p_h, horizon: float, groups: int = 10) -> pd.DataFrame:
    df = pd.DataFrame({"t": time, "e": event, "p": p_h}).dropna()
    df["g"] = pd.qcut(df["p"].rank(method="first"), groups, labels=False)
    rows = []
    for g, d in df.groupby("g"):
        rows.append({"group": int(g) + 1, "n": len(d), "events_by_h": int((d["e"] & (d["t"] <= horizon)).sum()),
                     "mean_predicted": d["p"].mean(), "observed_km": km_risk(d["t"], d["e"], horizon)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Eşik metrikleri
# --------------------------------------------------------------------------
def threshold_metrics(time, event, score, threshold: float, horizon: float) -> dict:
    t = np.asarray(time, float)
    s = np.asarray(score, float)
    ok = ~(np.isnan(t) | np.isnan(s))
    t, e, s = t[ok], np.asarray(event, bool)[ok], s[ok]
    case, ctrl, w = _censoring_weights(t, e, horizon)
    pos = s >= threshold
    tp = np.sum(w[case & pos]); fn = np.sum(w[case & ~pos])
    fp = np.sum(w[ctrl & pos]); tn = np.sum(w[ctrl & ~pos])
    sens = tp / (tp + fn) if tp + fn else np.nan
    spec = tn / (tn + fp) if tn + fp else np.nan
    ppv = tp / (tp + fp) if tp + fp else np.nan
    npv = tn / (tn + fn) if tn + fn else np.nan
    f1 = 2 * ppv * sens / (ppv + sens) if (ppv + sens) else np.nan
    return {"threshold": threshold, "sensitivity": sens, "specificity": spec, "ppv": ppv, "npv": npv,
            "f1": f1, "precision": ppv, "recall": sens, "alert_rate_per_1000": 1000 * pos.mean(),
            "n": int(len(t))}


def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """Binom oranı için Wilson skor aralığı (varsayılan %95). n = 0 → (nan, nan)."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return float(centre - half), float(centre + half)


def detection_rate(flag) -> dict:
    """Yalnızca pozitif vakadan oluşan kohortta (C1/C2) skorun yakalama oranı = duyarlılık.

    flag: hasta başı True (yüksek risk) / False / NA (skor hesaplanamadı).
    sens_computable: yakalanan / skoru hesaplanabilen (+ Wilson %95 GA).
    sens_all: yakalanan / tüm hastalar — hesaplanamayan "yakalanmadı" sayılır (tarama pratiği).
      Hiç hesaplanabilen yoksa (ör. bel çevresi teslim edilmediği için LRS) nan: "%0 duyarlılık"
      okunmasın.
    Negatif vaka olmadığı için özgüllük, PPV, AUROC buradan çıkmaz.
    """
    f = pd.Series(flag, dtype="boolean")
    n = int(len(f))
    n_comp = int(f.notna().sum())
    k = int(f.fillna(False).sum())
    lo, hi = wilson_ci(k, n_comp)
    return {"n": n, "n_computable": n_comp, "n_flagged": k,
            "sens_computable": k / n_comp if n_comp else float("nan"),
            "ci_low": lo, "ci_high": hi,
            "sens_all": k / n if n_comp else float("nan")}


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------
def bootstrap_ci(stat_fn, n: int, reps: int, seed: int, alpha: float = 0.05):
    """stat_fn(idx) → float. Yüzdelik CI. Dönüş: (alt, üst)."""
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        idx = rng.integers(0, n, n)
        v = stat_fn(idx)
        if v == v:
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    lo, hi = np.percentile(vals, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)
