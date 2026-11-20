"""Breakdowns from the medical team's C1 / C2 checklist (2026-11-20) that no other table gives: how treated
hypertension is derived, the QDiabetes smoking level per patient, and vital values left out as implausible; and the
NB0 / NB1 tables printed in the enclave COPY block (demographics with the share outside the QDiabetes age range,
facility representation, the C1–C2 selection effect, category shares).

Counts are unsuppressed here; the notebooks apply `sdc` (or the `suppressed_*` function of the table) before saving.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import sdc
from .config import PARAMS
from .io.schema import Dataset
from .phenotype import VITAL_PLAUSIBLE_RANGE
from .scores import qdiabetes2018a as qd

# --------------------------------------------------------------------------
# Treated hypertension
# --------------------------------------------------------------------------
# (htn_dx, htn_med) → category. Diagnosis: codelists.DX["hypertension"] (full history); medication:
# codelists.ATC["antihypertensive"] (within the snapshot window) — phenotype.core_snapshot.
HTN_CATEGORIES = {"diagnosis only": (True, False), "medication only": (False, True),
                  "diagnosis and medication": (True, True), "neither": (False, False)}
# Snapshot column each score reads as hypertension, and the categories that column is True for.
# QDiabetes: htn_treated_qd = diagnosis AND medication; LPRS (scores/lprs.py): htn_med = medication;
# LRA 2010 (scores/lrs.py): htn_lrs = diagnosis OR medication. tests/test_breakdowns.py checks both against the code.
HTN_SCORE_COLUMN = {"QDiabetes": "htn_treated_qd", "LPRS": "htn_med", "LRA 2010": "htn_lrs"}
HTN_COUNTED_BY = {"QDiabetes": {"diagnosis and medication"},
                  "LPRS": {"medication only", "diagnosis and medication"},
                  "LRA 2010": {"diagnosis only", "medication only", "diagnosis and medication"}}


def htn_derivation(snap: pd.DataFrame, group_col: str | None = "status") -> pd.DataFrame:
    """Patients per treated-hypertension category, overall ("all") and per `group_col` value.

    Columns: group, htn_category, n, n_group, pct (of n_group), counted_as_treated_by (scores that count the category
    as hypertension; "none" for neither).
    """
    groups = [("all", snap)]
    if group_col and group_col in snap.columns:
        groups += list(snap.groupby(group_col))
    rows = []
    for grp, g in groups:
        dx, med = g["htn_dx"].astype(bool), g["htn_med"].astype(bool)
        for cat, (want_dx, want_med) in HTN_CATEGORIES.items():
            n = int(((dx == want_dx) & (med == want_med)).sum())
            rows.append({"group": grp, "htn_category": cat, "n": n, "n_group": len(g),
                         "pct": round(100 * n / len(g), 1) if len(g) else None,
                         "counted_as_treated_by": ", ".join(s for s, cats in HTN_COUNTED_BY.items() if cat in cats)
                         or "none"})
    return pd.DataFrame(rows, columns=["group", "htn_category", "n", "n_group", "pct", "counted_as_treated_by"])


# --------------------------------------------------------------------------
# Smoking level
# --------------------------------------------------------------------------
QD_SMOKING_LEVELS = {0: "non", 1: "ex", 2: "light", 3: "moderate", 4: "heavy"}   # QDiabetes smoke_cat 0–4
SMOKING_LEVEL_ORDER = [*QD_SMOKING_LEVELS.values(), "missing"]


def smoking_levels(snap: pd.DataFrame, observations: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """QDiabetes smoking level per patient — the smoke_cat the score uses (qd.prepare_inputs: "current" without
    intensity → `qd_smoking_current_category`, D7; missing → non only if `qd_missing_smoking_as_non`, D8) — by
    what the patient's status was recorded as (canonical value, or why it is missing).

    Columns: qd_smoking_level, recorded_as, n, n_cohort, pct (of n_cohort), n_from_diagnosis_code (status from a
    smoking diagnosis code, e.g. Z87.891 ex-smoker). Every level appears (n = 0 if no patient has it).
    """
    cat = qd.prepare_inputs(snap, p)["smoke_cat"].astype(float)
    level = cat.map({float(k): v for k, v in QD_SMOKING_LEVELS.items()}).fillna("missing")

    cur = QD_SMOKING_LEVELS.get(p["qd_smoking_current_category"], str(p["qd_smoking_current_category"]))
    raw = snap["smoking_raw"].astype("string").str.strip().str.lower()
    known = raw.notna().to_numpy(dtype=bool)
    current = raw.eq("current").fillna(False).to_numpy(dtype=bool)
    sm_obs = observations["concept"].eq("smoking_status").fillna(False).astype(bool)
    has_rows = snap.index.isin(set(observations.loc[sm_obs, "patient_id"]))
    conflict = snap["smoking_undated_conflict"].fillna(False).to_numpy(dtype=bool)
    rec = pd.Series("no smoking record", index=snap.index, dtype=object)
    rec[has_rows] = "records present, none usable (unknown / unmapped, e.g. other)"
    rec[conflict] = "undated records disagree (D28)"
    rec[known] = raw.to_numpy(dtype=object)[known]
    rec[known & current] = f"current, intensity not recorded (D7 → {cur})"

    df = pd.DataFrame({"qd_smoking_level": level, "recorded_as": rec,
                       "dx": snap["smoking_source"].eq("diagnosis_code").fillna(False).astype(bool)})
    out = (df.groupby(["qd_smoking_level", "recorded_as"]).agg(n=("dx", "size"), n_from_diagnosis_code=("dx", "sum"))
           .reset_index())
    absent = [lv for lv in SMOKING_LEVEL_ORDER if lv not in set(out["qd_smoking_level"])]
    if absent:
        out = pd.concat([out, pd.DataFrame({"qd_smoking_level": absent, "recorded_as": "-", "n": 0,
                                            "n_from_diagnosis_code": 0})], ignore_index=True)
    out["n"] = out["n"].astype(int)
    out["n_from_diagnosis_code"] = out["n_from_diagnosis_code"].astype(int)
    out["n_cohort"] = len(snap)
    out["pct"] = (100 * out["n"] / len(snap)).round(1) if len(snap) else None
    order = {lv: i for i, lv in enumerate(SMOKING_LEVEL_ORDER)}
    out = (out.assign(_o=out["qd_smoking_level"].map(order))
           .sort_values(["_o", "n", "recorded_as"], ascending=[True, False, True]))
    cols = ["qd_smoking_level", "recorded_as", "n", "n_cohort", "pct", "n_from_diagnosis_code"]
    return out[cols].reset_index(drop=True)


# --------------------------------------------------------------------------
# Vital plausibility
# --------------------------------------------------------------------------
def vital_plausibility(ds: Dataset) -> pd.DataFrame:
    """Vital rows that phenotype.core_snapshot does not use: outside phenotype.VITAL_PLAUSIBLE_RANGE or not a number.

    Every observation row of the vital (full history, no reference date or window). Placeholder "0" / "-" values are
    already dropped and counted at ingest. BMI computed from height and weight goes through the same BMI range in
    core_snapshot; that is not counted here.

    Columns: variable, plausible_range, rows, rows_out_of_range, rows_below (of which below the range),
    rows_non_numeric, patients, patients_out_of_range (≥ 1 row outside the range), patients_without_plausible_value
    (rows present, none inside the range → the variable is missing for that patient).
    """
    obs = ds["observations"]
    rows = []
    for concept, (lo, hi) in VITAL_PLAUSIBLE_RANGE.items():
        o = obs[obs["concept"].eq(concept).fillna(False).astype(bool)]
        v = pd.to_numeric(o["value"], errors="coerce").astype(float)
        below, above = v < lo, v > hi
        pid = o["patient_id"]
        n_pts = pid.nunique()
        rows.append({"variable": concept, "plausible_range": f"{lo:g}–{hi:g}", "rows": len(o),
                     "rows_out_of_range": int((below | above).sum()), "rows_below": int(below.sum()),
                     "rows_non_numeric": int(v.isna().sum()), "patients": n_pts,
                     "patients_out_of_range": pid[below | above].nunique(),
                     "patients_without_plausible_value": n_pts - pid[v.between(lo, hi)].nunique()})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Category shares (NB1 smoking source, score missing reasons)
# --------------------------------------------------------------------------
def category_shares(values: pd.Series, column: str, n_cohort: int | None = None) -> pd.DataFrame:
    """Patients per value (most common first). Columns: `column`, n, n_cohort (default len(values)), pct (% of
    n_cohort). Before saving: suppressed_shares — the rate goes with a count < 10 and with n_cohort − n < 10."""
    n_cohort = len(values) if n_cohort is None else n_cohort
    vc = values.value_counts()
    return pd.DataFrame({column: list(vc.index), "n": [int(v) for v in vc], "n_cohort": n_cohort,
                         "pct": [round(100 * v / n_cohort, 1) if n_cohort else None for v in vc]},
                        columns=[column, "n", "n_cohort", "pct"])


def suppressed_shares(df: pd.DataFrame, threshold: int | None = None) -> pd.DataFrame:
    """category_shares() rows as they leave the enclave: pct hidden where n or (n_cohort − n) is < 10, n < 10 → "<10";
    n_cohort dropped (the cohort N is printed elsewhere)."""
    return sdc.suppress_count_rate_pairs(df, "n_cohort", [("n", "pct")], threshold).drop(columns="n_cohort")


def smoking_source(snap: pd.DataFrame) -> pd.DataFrame:
    """Where each patient's smoking status came from (phenotype.core_snapshot `smoking_source`: structured record /
    diagnosis code / undated records, D28); conflicting undated records → "missing (undated conflict)"."""
    src = snap["smoking_source"].astype(object).where(snap["smoking_source"].notna(), "missing")
    src = src.where(~snap["smoking_undated_conflict"].fillna(False).astype(bool), "missing (undated conflict)")
    return category_shares(src, "smoking_source")


# --------------------------------------------------------------------------
# Demographics and facility (NB0 §2–3)
# --------------------------------------------------------------------------
def demographics(patients: pd.DataFrame, end) -> dict:
    """Age at `end` (the data end) and sex of one cohort. The age range is QDiabetes's (qd.AGE_RANGE: 25 ≤ age < 85;
    outside → not computable): age_outside_25_84 = a known age outside it; a missing age counts in age_missing_n only.

    Keys: n, age_missing_n, age_known_n, age_median, age_iqr, age_25_84_n / _pct, age_outside_25_84_n / _pct,
    male_n / male_pct (% of n). Before saving: suppressed_demographics."""
    n = len(patients)
    age = ((end - patients["date_of_birth"]).dt.days / 365.25).dropna()
    lo, hi = qd.AGE_RANGE
    inside = int(((age >= lo) & (age < hi)).sum())
    male = int(patients["sex"].eq("Male").fillna(False).astype(bool).sum())

    def pct(k):
        return round(100 * k / n, 1) if n else None

    return {"n": n, "age_missing_n": n - len(age), "age_known_n": len(age),
            "age_median": round(float(age.median()), 1) if len(age) else None,
            "age_iqr": f"{age.quantile(.25):.0f}–{age.quantile(.75):.0f}" if len(age) else None,
            "age_outside_25_84_n": len(age) - inside, "age_outside_25_84_pct": pct(len(age) - inside),
            "age_25_84_n": inside, "age_25_84_pct": pct(inside), "male_n": male, "male_pct": pct(male)}


def suppressed_demographics(demo: pd.DataFrame, threshold: int | None = None) -> pd.DataFrame:
    """demographics() rows as they leave the enclave: each % hidden where its count or (n − count) is < 10, counts
    < 10 → "<10", median / IQR hidden over < 10 known ages; the helper counts (known ages, in range, male) dropped."""
    out = sdc.suppress_small_group_stats(demo, "age_known_n", ["age_median", "age_iqr"], threshold)
    out = sdc.suppress_count_rate_pairs(out, "n", [("age_outside_25_84_n", "age_outside_25_84_pct"),
                                                   ("age_25_84_n", "age_25_84_pct"), ("male_n", "male_pct")], threshold)
    out = sdc.suppress_small_counts(out, ["age_missing_n"], threshold)
    return out.drop(columns=["age_known_n", "age_25_84_n", "male_n"])


UNKNOWN_FACILITY = {"", "unknown"}       # facility_id values counted as missing (case-insensitive)


def facility_representation(patients: pd.DataFrame) -> dict:
    """facility_id of one cohort (the NABIDH adapter does not map a facility yet → all missing; DHA question).

    Keys: n_facilities (distinct known ids), top_facility_share_pct (% of patients with a facility),
    facility_missing_pct (% of all patients), and the counts behind them for suppressed_facility: n,
    facility_known_n, top_facility_n."""
    f = patients["facility_id"].astype("string").str.strip()
    f = f.mask(f.str.lower().isin(UNKNOWN_FACILITY).fillna(False).astype(bool))
    known = f.dropna()
    vc = known.value_counts()
    n, k = len(f), len(known)
    top = int(vc.iloc[0]) if len(vc) else 0
    return {"n_facilities": int(known.nunique()),
            "top_facility_share_pct": round(100 * top / k, 1) if k else None,
            "facility_missing_pct": round(100 * (n - k) / n, 1) if n else None,
            "n": n, "facility_known_n": k, "top_facility_n": top}


def suppressed_facility(fac: pd.DataFrame, threshold: int | None = None) -> pd.DataFrame:
    """facility_representation() rows as they leave the enclave: the top-facility share hidden where the top facility
    has < 10 patients or the others together < 10; the missing share where missing or known is < 10. No counts kept."""
    out = sdc.suppress_rates(fac, "top_facility_n", ["facility_known_n"], ["top_facility_share_pct"], threshold)
    out = sdc.suppress_rates(out.assign(_missing=out["n"] - out["facility_known_n"]), "_missing", ["n"],
                             ["facility_missing_pct"], threshold)
    return out.drop(columns=["n", "facility_known_n", "top_facility_n", "_missing"])


# --------------------------------------------------------------------------
# C1–C2 selection effect (NB1 §2)
# --------------------------------------------------------------------------
SMD_IMBALANCE = 0.1      # |SMD| above this is flagged as meaningful imbalance


def smd(a: pd.Series, b: pd.Series, binary: bool) -> float:
    """Standardised mean difference a − b over the non-missing values (binary: pooled p(1 − p))."""
    a, b = a.dropna().astype(float), b.dropna().astype(float)
    if binary:
        p1, p2 = a.mean(), b.mean()
        den = np.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
        return float((p1 - p2) / den) if den else 0.0
    den = np.sqrt((a.var() + b.var()) / 2)
    return float((a.mean() - b.mean()) / den) if den else 0.0


def selection_effect(f1: pd.DataFrame, f2: pd.DataFrame) -> pd.DataFrame:
    """C1 vs C2 per feature (same columns in f1 / f2). c1 / c2 = mean over patients with a value (binary: the share,
    0–1), smd, imbalance (|smd| > SMD_IMBALANCE). c1_n / c2_n = patients with a value; c1_k / c2_k (binary) =
    patients with the feature. Before saving: suppressed_selection_effect."""
    rows = []
    for col in f1.columns:
        a, b = f1[col], f2[col]
        binary = pd.api.types.is_bool_dtype(a) and pd.api.types.is_bool_dtype(b)
        row = {"variable": col, "type": "binary" if binary else "continuous",
               "c1": round(a.astype(float).mean(), 3), "c2": round(b.astype(float).mean(), 3),
               "smd": round(smd(a, b, binary), 3), "c1_n": int(a.notna().sum()), "c2_n": int(b.notna().sum())}
        row["c1_k"] = int(a.dropna().astype(bool).sum()) if binary else None
        row["c2_k"] = int(b.dropna().astype(bool).sum()) if binary else None
        rows.append(row)
    out = pd.DataFrame(rows, columns=["variable", "type", "c1", "c2", "smd", "c1_n", "c2_n", "c1_k", "c2_k"])
    out.insert(5, "imbalance", out["smd"].abs() > SMD_IMBALANCE)
    return out


def suppressed_selection_effect(sel: pd.DataFrame, threshold: int | None = None) -> pd.DataFrame:
    """selection_effect() as it leaves the enclave. A binary share is hidden where its count or (n − count) is < 10,
    a continuous mean where fewer than 10 patients have a value; the SMD of such a row too (with the other cohort's
    share it gives the hidden one back). The imbalance flag stays (|SMD| > 0.1 only). c1_n / c2_n < 10 → "<10"."""
    t = threshold or PARAMS["small_cell_threshold"]
    out = sel.copy()

    def small(s: pd.Series) -> pd.Series:
        return s.notna() & (s > 0) & (s < t)

    hidden = pd.Series(False, index=out.index)
    for c in ("c1", "c2"):
        k, n = pd.to_numeric(out[f"{c}_k"], errors="coerce"), pd.to_numeric(out[f"{c}_n"], errors="coerce")
        h = small(k) | small(n - k) | small(n)
        out[c] = out[c].astype(object)
        out.loc[h, c] = f"suppressed (<{t})"
        hidden |= h
    out["smd"] = out["smd"].astype(object)
    out.loc[hidden, "smd"] = f"suppressed (<{t})"
    return sdc.suppress_small_counts(out, ["c1_n", "c2_n"], t).drop(columns=["c1_k", "c2_k"])
