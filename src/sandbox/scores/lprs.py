"""Leicester Practice Risk Score (LPRS) — the Leicester score that needs no waist circumference.

Source: Gray LJ, Davies MJ, Hiles S, Taub NA, Webb DR, Srinivasan BT, Khunti K. Detection of impaired
glucose regulation and/or type 2 diabetes mellitus, using primary care electronic data, in a multiethnic
UK community setting. Diabetologia 2012;55(4):959–966. doi:10.1007/s00125-011-2432-x

Developed for routine primary-care EHR data; waist circumference was left out of the model because it is not
routinely recorded in the EHR. Linear predictor of a logistic model, no intercept → NOT an absolute risk/probability,
a ranking score. Coefficients taken verbatim from the "Automated score for GP databases" slide of the first author's
(L. J. Gray, Leicester Diabetes Centre) "The Leicester Diabetes Risk Scores" presentation (the slide cites the paper):

    Risk Score = 0.0408359 × age + 0.1839942 (if male) + 0.7565977 (if BME) + 0.0820698 × BMI
                 + 0.4770517 (if family history of T2DM) + 0.5498978 (if on antihypertensive medication)

[VERIFICATION PENDING] The coefficients have not yet been checked against the full text of the paper (paywall).

No absolute "high risk" threshold was found: the authors used the score for ranking — the top 10% per practice
were invited (Let's Prevent Diabetes and Walking Away from Diabetes; Gray et al. Diabetologia
2012, doi:10.1007/s00125-012-2725-8) or a threshold was chosen for a target sensitivity (e.g. 80%) (same presentation).
The threshold is therefore `PARAMS["lprs_high_risk_threshold"]`; None → "Pending" [DECISION PENDING — D23].

Coding:
- age: years, continuous. Development population aged 40–75; for patients outside this range the score is an
  extrapolation (no restriction applied, same as LRA 2010).
- BME (Black and minority ethnic): non-white = 1. Same mapping as LRA 2010 (`codelists.LRS_WHITE`).
  Ethnicity not recorded → `lrs_unknown_ethnicity_as_missing` (D12).
- BMI: kg/m², continuous.
- family history: diabetes in a first-degree relative (`phenotype` → `family_history`).
- antihypertensive: Gray 2012 uses an antihypertensive prescription only. Here `phenotype` → `htn_treated_lprs`:
  a hypertension diagnosis OR an antihypertensive drug by default (D36, `lprs_treated_htn = "dx_or_med"`); the
  published definition, drug only, is `lprs_treated_htn = "med"` (sensitivity run).

Note: LPRS is a cross-sectional score developed to detect existing (undiagnosed) IGR/T2D; the incident benchmark
in C3 is reported as off-label use.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import codelists
from ..config import PARAMS

COEF = {
    "age": 0.0408359,            # per year
    "male": 0.1839942,
    "bme": 0.7565977,            # non-white
    "bmi": 0.0820698,            # per kg/m²
    "family_history": 0.4770517,
    "antihypertensive": 0.5498978,
}
DEV_AGE_RANGE = (40, 75)         # development population (informational; no restriction applied)


UNKNOWN_ETHNICITY_AS = {"white": 0.0, "other": 1.0}


def bme_flag(ethnicity: pd.Series, p: dict = PARAMS) -> pd.Series:
    """Non-white = 1.0, white = 0.0; not recorded → NaN (if D12 is on), or the scenario value of
    `lrs_unknown_ethnicity_as` ("white" → 0.0, "other" → 1.0; NB1 §4b) — known values are kept either way."""
    eth = ethnicity.astype("string").str.strip().str.lower()
    unknown = (eth.isna() | eth.isin(codelists.ETHNICITY_UNKNOWN)).fillna(True).astype(bool)
    white = eth.isin(codelists.LRS_WHITE).fillna(False).astype(bool)
    out = pd.Series(np.where(white, 0.0, 1.0), index=ethnicity.index, dtype=float)
    scenario = p.get("lrs_unknown_ethnicity_as")
    if scenario is not None:
        if scenario not in UNKNOWN_ETHNICITY_AS:
            raise ValueError(f"lrs_unknown_ethnicity_as = {scenario!r}; expected None, 'white' or 'other'")
        return out.where(~unknown, UNKNOWN_ETHNICITY_AS[scenario])
    if p["lrs_unknown_ethnicity_as_missing"]:
        out = out.where(~unknown)
    return out


def score(snap: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """phenotype.core_snapshot → LPRS. Missing input → NaN + lrs_missing reason.

    Output columns carry the same names as LRA 2010 (`lrs_*`), so the notebooks are variant-independent.
    The components (lrs_age, lrs_sex, …) are contributions to the score (coefficient × value).
    """
    sex_ok = snap["sex"].isin(["Male", "Female"])
    bmi = pd.to_numeric(snap["bmi"], errors="coerce").astype(float)
    parts = {
        "lrs_age": pd.to_numeric(snap["age"], errors="coerce").astype(float) * COEF["age"],
        "lrs_sex": pd.Series(np.where(snap["sex"] == "Male", COEF["male"], 0.0), index=snap.index,
                             dtype=float).where(sex_ok),
        "lrs_ethnicity": bme_flag(snap["ethnicity"], p) * COEF["bme"],
        "lrs_bmi": bmi * COEF["bmi"],
        "lrs_fh": snap["family_history"].astype(bool).astype(float) * COEF["family_history"],
        "lrs_htn": snap["htn_treated_lprs"].astype(bool).astype(float) * COEF["antihypertensive"],
    }
    x = pd.DataFrame(parts)
    reasons = pd.Series("", index=x.index, dtype=object)
    for col, why in [("lrs_age", "age;"), ("lrs_sex", "sex;"), ("lrs_ethnicity", "ethnicity;"),
                     ("lrs_bmi", "bmi_missing;")]:
        reasons = reasons + np.where(x[col].isna(), why, "")
    x["lrs_missing"] = reasons
    x["lrs_computable"] = reasons == ""
    x["lrs_score"] = x[list(parts)].sum(axis=1, min_count=len(parts)).where(x["lrs_computable"])
    x["lrs_category"] = pd.Series(pd.NA, index=x.index, dtype="string")   # no published categories
    thr = p["lprs_high_risk_threshold"]
    if thr is None:
        x["lrs_high_risk"] = pd.Series(pd.NA, index=x.index, dtype="boolean")
    else:
        x["lrs_high_risk"] = (x["lrs_score"] >= thr).astype("boolean").mask(~x["lrs_computable"])
    x["lrs_outside_dev_age"] = ~pd.to_numeric(snap["age"], errors="coerce").between(*DEV_AGE_RANGE)
    return x
