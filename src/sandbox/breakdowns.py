"""Breakdowns from the medical team's C1 / C2 checklist (2026-11-20) that no other table gives: how treated
hypertension is derived, the QDiabetes smoking level per patient, and vital values left out as implausible.

Counts are unsuppressed here; the notebooks apply `sdc` before saving.
"""
from __future__ import annotations

import pandas as pd

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
