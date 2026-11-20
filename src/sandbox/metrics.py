"""Performance metrics for censored (time-to-event) data — numpy/pandas only.

Convention: time = follow-up in years, event = primary outcome (bool),
risk = predicted probability (0–1) or a ranking score (for C-index / AUROC).
When evaluating at horizon h, `truncate(time, event, h)` is applied first (administrative censoring).

Chosen methods (documented):
- C-index: Harrell; comparable pair = i with an event and T_j > T_i (tied times are not compared);
  tied risk counts 0.5.
- Time-dependent AUROC(h): cumulative/dynamic, IPCW (Uno 2007; Hung & Chiang 2010) — cases
  T ≤ h with an event, weight 1/G(T−); controls T > h, weight 1/G(h); G = censoring KM.
- Observed risk: 1 − KM(h). O:E = observed / mean predicted.
- Calibration slope: Cox PH (Breslow) of time ~ cloglog(p_h), univariable Newton-Raphson; ideal 1.
- Threshold metrics (sens/spec/PPV/NPV/F1): IPCW-weighted 2×2; alert rate = share above threshold × 1000.
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
    """Returns: (event times, S(t) at those times) — right-continuous step function."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    ts = np.sort(t)
    uniq, d = np.unique(t[e], return_counts=True)
    n_risk = len(t) - np.searchsorted(ts, uniq, side="left")
    surv = np.cumprod(1.0 - d / n_risk)
    return uniq, surv


def step_at(times, surv, t, left: bool = False):
    """S(t) (left=True → S(t−)). Vectorised."""
    t = np.atleast_1d(np.asarray(t, float))
    idx = np.searchsorted(times, t, side="left" if left else "right") - 1
    out = np.where(idx >= 0, surv[np.clip(idx, 0, None)] if len(surv) else 1.0, 1.0)
    return out


def km_risk(time, event, horizon: float) -> float:
    times, surv = kaplan_meier(time, event)
    return float(1.0 - step_at(times, surv, horizon)[0])


def _censoring_weights(time, event, horizon):
    """IPCW: cases 1/G(T−), controls 1/G(h), others 0."""
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
# Discrimination
# --------------------------------------------------------------------------
def c_index(time, event, risk) -> float:
    """Harrell C (Fenwick tree, O(n log n))."""
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

    def query(i):  # number of elements with rank ≤ i
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
        # group [i, j): same time. The tree only holds those with longer times.
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
# Calibration
# --------------------------------------------------------------------------
def cox_1d(time, event, x, max_iter: int = 50, tol: float = 1e-9):
    """Univariable Cox PH (Breslow ties). Returns: (beta, se)."""
    t = np.asarray(time, float)
    e = np.asarray(event, bool)
    x = np.asarray(x, float)
    order = np.argsort(t, kind="mergesort")
    t, e, x = t[order], e[order], x[order]
    first = np.searchsorted(t, t, side="left")      # start of the risk set (T_j ≥ T_i)
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
# Threshold metrics
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
    """Wilson score interval for a binomial proportion (95% by default). n = 0 → (nan, nan)."""
    if n <= 0:
        return float("nan"), float("nan")
    p = k / n
    den = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return float(centre - half), float(centre + half)


def detection_rate(flag) -> dict:
    """Capture rate of a score in a cohort of positive cases only (C1/C2) = sensitivity.

    flag: per patient True (high risk) / False / NA (score could not be computed).
    sens_computable: captured / patients with a computable score (+ Wilson 95% CI).
    sens_all: captured / all patients — not computable counts as "not captured" (screening practice).
      If none is computable (e.g. LRA 2010 with waist circumference not delivered) nan, so it is not
      read as "0% sensitivity".
    With no negative cases, specificity, PPV and AUROC cannot come from here.
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


def detection_sweep(score, thresholds) -> pd.DataFrame:
    """Sensitivity in a positives-only cohort (C1 / C2) at each threshold: score >= t → flagged; NaN = not computable.
    One row per threshold: n, n_computable, n_flagged, sens_computable, ci_low, ci_high (Wilson 95%). Descriptive:
    with no negatives, specificity / PPV / F1 / AUROC cannot come from here (detection_rate)."""
    s = pd.to_numeric(pd.Series(score), errors="coerce")
    rows = []
    for t in thresholds:
        r = detection_rate((s >= t).astype("boolean").mask(s.isna()))
        rows.append({"threshold": t, **{k: r[k] for k in ("n", "n_computable", "n_flagged", "sens_computable",
                                                          "ci_low", "ci_high")}})
    return pd.DataFrame(rows, columns=["threshold", "n", "n_computable", "n_flagged", "sens_computable", "ci_low",
                                       "ci_high"])


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------
def bootstrap_ci(stat_fn, n: int, reps: int, seed: int, alpha: float = 0.05):
    """stat_fn(idx) → float. Percentile CI. Returns: (lower, upper)."""
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
