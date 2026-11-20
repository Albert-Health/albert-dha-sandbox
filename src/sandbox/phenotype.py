"""Glycaemic measurements, diabetes/prediabetes evidence and the state of the 8 core variables
at a given reference date.

Lab values are used only for the outcome / eligibility definition; never as model inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import codelists
from .config import PARAMS
from .io.schema import Dataset
from .scores import lrs

# Priority when several pieces of evidence fall on the same day (smaller = first)
EVIDENCE_PRIORITY = {"lab_hba1c": 0, "lab_fpg": 1, "lab_ogtt": 2, "lab_random_glucose": 3,
                     "diagnosis": 4, "medication": 5}


# --------------------------------------------------------------------------
# Glycaemic measurements
# --------------------------------------------------------------------------
def glycaemic_events(ds: Dataset, p: dict = PARAMS) -> pd.DataFrame:
    """Glycaemic labs, unit-normalised, ADA-classified.

    Returns: patient_id, date, kind (hba1c/fpg/ogtt_2h/random_glucose), value, status (normal/pre/dm/na)
    """
    labs = ds["labs"]
    kind = labs["loinc"].map(codelists.LOINC_LAB)
    g = labs.assign(kind=kind).dropna(subset=["kind", "value", "date"]).copy()
    unit = g["unit"].astype("string").str.lower().fillna("")

    # HbA1c IFCC (mmol/mol) → NGSP %
    ifcc = (g["kind"] == "hba1c_ifcc") | ((g["kind"] == "hba1c") & unit.str.contains("mmol/mol"))
    g.loc[ifcc, "value"] = g.loc[ifcc, "value"] / 10.929 + 2.15
    g.loc[ifcc, "kind"] = "hba1c"
    # Glucose mmol/L → mg/dL
    gl = g["kind"].isin(["fpg", "ogtt_2h", "random_glucose"]) & unit.str.contains("mmol/l")
    g.loc[gl, "value"] = g.loc[gl, "value"] * 18.016

    v = g["value"]
    k = g["kind"]
    status = np.select(
        [
            (k == "hba1c") & (v >= p["hba1c_dm"]),
            (k == "hba1c") & (v >= p["hba1c_pre_low"]),
            (k == "hba1c"),
            (k == "fpg") & (v >= p["fpg_dm"]),
            (k == "fpg") & (v >= p["fpg_pre_low"]),
            (k == "fpg"),
            (k == "ogtt_2h") & (v >= p["ogtt_dm"]),
            (k == "ogtt_2h") & (v >= p["ogtt_pre_low"]),
            (k == "ogtt_2h"),
            (k == "random_glucose") & (v >= p["random_glucose_dm"]),
        ],
        ["dm", "pre", "normal", "dm", "pre", "normal", "dm", "pre", "normal", "dm"],
        default="na",  # random glucose < 200 → not evidence of normal
    )
    g["status"] = status
    return g[["patient_id", "date", "kind", "value", "unit", "status"]].reset_index(drop=True)


def dm_evidence(ds: Dataset, glyc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Diabetes / prediabetes / T1D evidence (long format).

    Returns: patient_id, date, status (t2d/pre/t1d), evidence
    """
    glyc = glycaemic_events(ds) if glyc is None else glyc
    parts = []

    lab = glyc[glyc["status"].isin(["dm", "pre"])].copy()
    lab["evidence"] = "lab_" + lab["kind"].replace({"ogtt_2h": "ogtt"})
    lab["status"] = lab["status"].replace({"dm": "t2d"})
    parts.append(lab[["patient_id", "date", "status", "evidence"]])

    cond = ds["conditions"]
    for group, status in [("t2d", "t2d"), ("prediabetes", "pre"), ("t1d", "t1d")]:
        m = cond[codelists.match_dx(cond, group)]
        parts.append(m[["patient_id", "date"]].assign(status=status, evidence="diagnosis"))

    meds = ds["medications"]
    a10 = meds[codelists.match_atc(meds, "antidiabetic")]
    parts.append(a10[["patient_id", "date"]].assign(status="t2d", evidence="medication"))

    ev = pd.concat(parts, ignore_index=True).dropna(subset=["date"])
    return ev.sort_values(["patient_id", "date"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Core variables (snapshot)
# --------------------------------------------------------------------------
_MISSING_ETH = {"", "not recorded", "unknown", "not stated", "na", "n/a", "none", "other - not stated"}
# FamilyHistory values that count as "record present" (unknown / unmapped do not count)
FH_RECORDED_VALUES = {"positive", "negative", "positive_non_first_degree"}
# PARAMS["qd_treated_htn"] (D36): diagnosis OR drug, or the QDiabetes-2018 definition diagnosis AND drug
QD_TREATED_HTN_RULES = ("dx_or_med", "dx_and_med")
# PARAMS["lprs_treated_htn"] (D36): diagnosis OR drug, or the LPRS (Gray 2012) definition drug only
LPRS_TREATED_HTN_RULES = ("dx_or_med", "med")
# Plausible range of each vital (inclusive). core_snapshot leaves out values outside it (BMI from height / weight
# too); breakdowns.vital_plausibility counts them (NB0 nb00/vital_plausibility.csv). Data-quality bounds, not a
# study parameter.
VITAL_PLAUSIBLE_RANGE = {"bmi": (12, 80), "height_cm": (120, 230), "weight_kg": (25, 350), "waist_cm": (40, 250)}


def _plausible(num: pd.DataFrame, concept: str) -> pd.DataFrame:
    """Rows of one vital whose numeric value `v` is inside VITAL_PLAUSIBLE_RANGE."""
    return num[(num["concept"] == concept) & num["v"].between(*VITAL_PLAUSIBLE_RANGE[concept])]


def ethnicity_recorded(raw: pd.Series) -> pd.Series:
    """True where an ethnicity / nationality value is recorded (not empty, "not recorded", "unknown" …)."""
    txt = raw.astype("string").str.strip().str.lower()
    missing = txt.isin(_MISSING_ETH).fillna(True).astype(bool)
    return txt.notna().astype(bool) & ~missing


def _z68_to_bmi(code: pd.Series) -> pd.Series:
    """Convert a Z68.xx band to an approximate BMI (band midpoint). Fallback source only."""
    c = codelists.norm_icd(code)
    out = pd.Series(np.nan, index=code.index)
    out[c == "Z681"] = 19.0
    for decade in (2, 3):
        for d in range(10):
            out[c == f"Z68{decade}{d}"] = decade * 10 + d + 0.5
    for code_, val in {"Z6841": 42.5, "Z6842": 47.5, "Z6843": 52.5, "Z6844": 57.5, "Z6845": 70.0}.items():
        out[c == code_] = val
    return out


def _window(df: pd.DataFrame, ref: pd.Series, lookback_days: int | None) -> pd.DataFrame:
    """Filter df rows to the patient's reference-date window: (ref - lookback, ref]."""
    d = df.merge(ref.rename("ref_date"), left_on="patient_id", right_index=True, how="inner")
    keep = d["date"] <= d["ref_date"]
    if lookback_days is not None:
        keep &= d["date"] > d["ref_date"] - pd.Timedelta(days=lookback_days)
    return d[keep]


def _latest(df: pd.DataFrame, value_col: str = "value") -> pd.Series:
    if df.empty:
        return pd.Series(dtype=object)
    return df.sort_values("date").groupby("patient_id")[value_col].last()


def core_snapshot(ds: Dataset, ref: pd.Series, lookback_days: int | None,
                  p: dict = PARAMS) -> pd.DataFrame:
    """The 8 core variables at the reference date for each patient (+ waist, + extra QDiabetes flags).

    ref: index = patient_id, value = reference date (Timestamp).
    lookback_days: window for measured values (BMI, waist, medication); None = full history.
    Diagnosis flags (CVD, HTN diagnosis, FH etc.) always look at the full history.
    """
    ref = ref.dropna()
    out = pd.DataFrame(index=ref.index.rename("patient_id"))
    pts = ds["patients"].drop_duplicates("patient_id").set_index("patient_id")

    # Demographics
    out["sex"] = pts["sex"].reindex(out.index)
    dob = pts["date_of_birth"].reindex(out.index)
    out["age"] = (ref - dob).dt.days / 365.25
    # Ethnic group: from the PARAMS["ethnicity_source"] column (nationality or NABIDH ethnicity)
    src = p.get("ethnicity_source", PARAMS["ethnicity_source"])
    eth = pts[codelists.ETHNICITY_SOURCE_COLUMN[src]].reindex(out.index)
    eth = eth.where(ethnicity_recorded(eth))
    out["ethnicity_source_value"] = eth
    out["ethnicity"] = codelists.ethnic_group(eth, src)

    # Observations (within the window)
    obs_all = ds["observations"]
    obs_win = _window(obs_all, ref, lookback_days)
    num = obs_win.assign(v=pd.to_numeric(obs_win["value"], errors="coerce"))

    bmi_direct = _latest(_plausible(num, "bmi"), "v")
    w = _latest(_plausible(num, "weight_kg"), "v")
    # Height is stable in adults: latest value from the full history
    obs_hist = _window(obs_all, ref, None)
    numh = obs_hist.assign(v=pd.to_numeric(obs_hist["value"], errors="coerce"))
    h = _latest(_plausible(numh, "height_cm"), "v")
    bmi_hw = (w / (h.reindex(w.index) / 100) ** 2).dropna()
    bmi_hw = bmi_hw[bmi_hw.between(*VITAL_PLAUSIBLE_RANGE["bmi"])]

    cond_win = _window(ds["conditions"], ref, lookback_days)
    z68 = cond_win[codelists.match_dx(cond_win, "bmi_code")]
    bmi_z68 = _latest(z68.assign(v=_z68_to_bmi(z68["code"])).dropna(subset=["v"]), "v")

    out["bmi"] = bmi_direct.reindex(out.index)
    out["bmi_source"] = np.where(out["bmi"].notna(), "direct", None)
    fill = out["bmi"].isna() & out.index.isin(bmi_hw.index)
    out.loc[fill, "bmi"] = bmi_hw.reindex(out.index)[fill]
    out.loc[fill, "bmi_source"] = "height_weight"
    fill = out["bmi"].isna() & out.index.isin(bmi_z68.index)
    out.loc[fill, "bmi"] = bmi_z68.reindex(out.index)[fill]
    out.loc[fill, "bmi_source"] = "z68_band"

    out["waist_cm"] = _latest(_plausible(num, "waist_cm"), "v").reindex(out.index)

    # Smoking: latest status (full history, up to ref) — structured field first, then diagnosis code.
    # Only recognised values (never/ex/current/light/moderate/heavy …) count; "unknown" or values
    # the adapter could not map do not overwrite an earlier informative record.
    sm = obs_hist[obs_hist["concept"] == "smoking_status"]
    sm = sm.assign(v=sm["value"].astype("string").str.strip().str.lower())
    sm = sm[sm["v"].isin(list(codelists.SMOKING_TEXT_TO_CAT)).fillna(False).astype(bool)]
    sm_raw = _latest(sm, "v")
    out["smoking_raw"] = sm_raw.reindex(out.index)
    out["smoking_source"] = np.where(out["smoking_raw"].notna(), "structured", None)
    cond_hist = _window(ds["conditions"], ref, None)
    sm_dx = []
    for grp, label in [("smoking_current", "current"), ("smoking_ex", "ex"), ("smoking_never", "never")]:
        m = cond_hist[codelists.match_dx(cond_hist, grp)]
        sm_dx.append(m[["patient_id", "date"]].assign(value=label))
    sm_dx = pd.concat(sm_dx, ignore_index=True)
    sm_dx_latest = _latest(sm_dx).reindex(out.index)
    fill = out["smoking_raw"].isna() & sm_dx_latest.notna()
    out.loc[fill, "smoking_raw"] = sm_dx_latest[fill]
    out.loc[fill, "smoking_source"] = "diagnosis_code"
    # D28: undated structured records, only if they all agree (QDiabetes category; "current" → D7 default)
    out["smoking_undated_conflict"] = False
    if p.get("smoking_undated_if_consistent", PARAMS["smoking_undated_if_consistent"]):
        und = obs_all[(obs_all["concept"] == "smoking_status") & obs_all["date"].isna()
                      & obs_all["patient_id"].isin(out.index)]
        und = und.assign(v=und["value"].astype("string").str.strip().str.lower())
        und = und[und["v"].isin(list(codelists.SMOKING_TEXT_TO_CAT)).fillna(False).astype(bool)]
        cur = p.get("qd_smoking_current_category", PARAMS["qd_smoking_current_category"])
        und = und.assign(cat=und["v"].map(lambda x: cur if codelists.SMOKING_TEXT_TO_CAT[x] is None
                                          else codelists.SMOKING_TEXT_TO_CAT[x]))
        n_cat = und.groupby("patient_id")["cat"].nunique()
        value = und.groupby("patient_id")["v"].first()
        need = out["smoking_raw"].isna()
        ok = need & out.index.isin(n_cat.index[n_cat == 1])
        out.loc[ok, "smoking_raw"] = value.reindex(out.index)[ok]
        out.loc[ok, "smoking_source"] = "undated_consistent"
        out.loc[need & out.index.isin(n_cat.index[n_cat > 1]), "smoking_undated_conflict"] = True
    out["smoking_cat"] = out["smoking_raw"].map(codelists.SMOKING_TEXT_TO_CAT)

    # Diagnosis flags (full history, ref included)
    for grp, col in [("family_history_dm", "family_history"), ("cvd", "cvd"), ("hypertension", "htn_dx"),
                     ("gdm", "gdm"), ("pcos", "pcos"), ("learning_disability", "learn"),
                     ("schizophrenia_bipolar", "psy")]:
        ids = set(cond_hist.loc[codelists.match_dx(cond_hist, grp), "patient_id"])
        out[col] = out.index.isin(ids)

    # Family history: Z83.3 diagnosis OR a FamilyHistory record (adapter → observations concept
    # family_history_dm; value positive / negative / positive_non_first_degree / unknown).
    # Positive = diabetes in a first-degree relative (QDiabetes and LRS definition). Recorded = positive or negative.
    # family_history_any_date (D27): present / absent; the record date is not used (undated records also count).
    fh_any_date = p.get("family_history_any_date", PARAMS["family_history_any_date"])
    if fh_any_date:
        conds = ds["conditions"]
        out["family_history"] = out.index.isin(set(conds.loc[codelists.match_dx(conds, "family_history_dm"),
                                                             "patient_id"]))
    fh_src = obs_all if fh_any_date else obs_hist
    fh = fh_src[fh_src["concept"] == "family_history_dm"]
    fh_val = fh["value"].astype("string").str.strip().str.lower()
    fh_pos = set(fh.loc[fh_val.eq("positive").fillna(False).astype(bool), "patient_id"])
    fh_rec = set(fh.loc[fh_val.isin(list(FH_RECORDED_VALUES)).fillna(False).astype(bool), "patient_id"])
    dx_fh = out["family_history"]
    out["family_history"] = dx_fh | out.index.isin(fh_pos)
    out["family_history_recorded"] = dx_fh | out.index.isin(fh_rec)

    # Medication flags (within the window)
    med_win = _window(ds["medications"], ref, lookback_days)
    for grp, col in [("antihypertensive", "htn_med"), ("statin", "statin"),
                     ("corticosteroid", "corticosteroid"), ("atypical_antipsychotic", "apsy")]:
        ids = set(med_win.loc[codelists.match_atc(med_win, grp), "patient_id"])
        out[col] = out.index.isin(ids)

    htn_rule = p.get("qd_treated_htn", PARAMS["qd_treated_htn"])  # QDiabetes (D36): dx_or_med | dx_and_med
    if htn_rule not in QD_TREATED_HTN_RULES:
        raise ValueError(f"qd_treated_htn = {htn_rule!r}; expected one of {', '.join(QD_TREATED_HTN_RULES)}")
    out["htn_treated_qd"] = (out["htn_dx"] | out["htn_med"]) if htn_rule == "dx_or_med" else (out["htn_dx"] & out["htn_med"])
    out["htn_lrs"] = out["htn_dx"] | out["htn_med"]             # LRA 2010: diagnosis OR medication
    lprs_rule = p.get("lprs_treated_htn", PARAMS["lprs_treated_htn"])   # LPRS (D36): dx_or_med | med (Gray 2012)
    if lprs_rule not in LPRS_TREATED_HTN_RULES:
        raise ValueError(f"lprs_treated_htn = {lprs_rule!r}; expected one of {', '.join(LPRS_TREATED_HTN_RULES)}")
    out["htn_treated_lprs"] = (out["htn_dx"] | out["htn_med"]) if lprs_rule == "dx_or_med" else out["htn_med"]

    # Completeness flags (C1 definition + KPIs)
    out["ok_sex"] = out["sex"].isin(["Male", "Female"])
    out["ok_age"] = out["age"].notna()
    out["ok_ethnicity"] = out["ethnicity"].notna()
    out["ok_bmi"] = out["bmi_source"].isin(["direct", "height_weight"])   # a Z68 band does not count as complete
    out["ok_smoking"] = out["smoking_raw"].notna()
    out["ok_family_history"] = out["family_history_recorded"] if p["c1_require_fh_record"] else True
    out["ok_cvd"] = True            # present/absent in the EHR
    out["ok_hypertension"] = True   # diagnosis and medication are separate fields; present/absent
    ok_cols = [f"ok_{v}" for v in codelists.CORE_VARIABLES]
    out["ok_core8"] = out[ok_cols].all(axis=1)
    out["ok_core7"] = out[[f"ok_{v}" for v in CORE7_VARIABLES]].all(axis=1)    # all but ethnicity (D6)
    # Joint completeness for the Leicester score: waist circumference is needed only for the LRA 2010 variant (K-LRS)
    out["ok_lrs"] = out[["ok_sex", "ok_age", "ok_ethnicity", "ok_bmi", "ok_family_history",
                         "ok_hypertension"]].all(axis=1)
    if lrs.needs_waist(p):
        out["ok_lrs"] &= out["waist_cm"].notna()
    out["ref_date"] = ref
    return out


# --------------------------------------------------------------------------
# Completeness report (C1 / C2 checklist; NB0 and NB1 tables)
# --------------------------------------------------------------------------
# Core-7 = the 8 core variables without ethnicity (no nationality column in NABIDH, EthnicGroup mostly empty — D6);
# core-8 = core-7 + ethnicity.
CORE7_VARIABLES = [v for v in codelists.CORE_VARIABLES if v != "ethnicity"]
COMPLETENESS_TARGET_PCT = 90    # KPI "Data Completeness for Required Variables" target (kpi.KPI_ROWS ">= 90%")
# measure — what "complete" means for a variable:
#   recorded        a value is in the record (sex, age, ethnicity, BMI, smoking; family history only with
#                   c1_require_fh_record, D17)
#   present_absent  a yes / no flag from diagnoses / medication: no record = absent, so every patient has it —
#                   100% by definition, not a fill rate (the KPI minimum still counts it as 100%)
RECORDED_NOTE = "a value in the record"
PRESENT_ABSENT_NOTE = "no record = absent: 100% by definition, not a fill rate"
NOT_MEASURED = "-"     # meets_90 of a present_absent row ("" or "n/a" would read back as NaN from the CSV)
FH_RECORDED_NOTE = "FamilyHistory record (positive / negative / other relative) or Z83.3"


def completeness_measure(variable: str, p: dict = PARAMS) -> str:
    """'recorded' or 'present_absent' (see above) for a core variable."""
    if variable in ("cvd", "hypertension"):
        return "present_absent"
    if variable == "family_history" and not p.get("c1_require_fh_record", PARAMS["c1_require_fh_record"]):
        return "present_absent"
    return "recorded"


def completeness_by_variable(s: pd.DataFrame, p: dict = PARAMS) -> list[dict]:
    """Per-variable completeness of one patient group (core_snapshot rows): the 8 core variables, the family-history
    record (`family_history_recorded`, after family_history) and waist circumference for LRA 2010 only.
    meets_90: complete_pct ≥ COMPLETENESS_TARGET_PCT for recorded values; NOT_MEASURED for present_absent."""
    items = []
    for v in codelists.CORE_VARIABLES:
        measure = completeness_measure(v, p)
        items.append((v, s[f"ok_{v}"], measure, PRESENT_ABSENT_NOTE if measure == "present_absent" else RECORDED_NOTE))
        if v == "family_history":
            items.append(("family_history_recorded", s["family_history_recorded"], "recorded", FH_RECORDED_NOTE))
    if lrs.needs_waist(p):
        items.append(("waist (LRS)", s["waist_cm"].notna(), "recorded", f"{RECORDED_NOTE} (LRA 2010 only)"))
    n, rows = len(s), []
    for v, ok, measure, note in items:
        k = int(ok.astype(bool).sum())
        pct = round(100 * k / n, 1) if n else np.nan
        rows.append({"variable": v, "measure": measure, "n": n, "complete_n": k, "complete_pct": pct,
                     "meets_90": NOT_MEASURED if measure == "present_absent" else None if not n
                     else bool(pct >= COMPLETENESS_TARGET_PCT),
                     "note": note})
    return rows


def joint_completeness(s: pd.DataFrame) -> dict:
    """Joint completeness of one patient group: core-7 (all but ethnicity), core-8 (core-7 + ethnicity) and the
    active Leicester variant's inputs (ok_lrs); N and % each."""
    n = len(s)
    out = {"n": n}
    for name in ("core7", "core8", "lrs"):
        k = int(s[f"ok_{name}"].astype(bool).sum())
        out[f"joint_{name}_n"] = k
        out[f"joint_{name}_pct"] = round(100 * k / n, 1) if n else np.nan
    return out
