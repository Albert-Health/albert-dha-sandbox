"""QDiabetes-2018 Model A (the variant that needs no laboratory values).

Coefficient source: CRAN 'QDiabetes' R package v1.0-2, R/QDR2018A.R (B. Feakes; R port of the
QDiabetes-2018 open-source code by ClinRisk Ltd. / University of Oxford, qdiabetes.org).
Licence: original code LGPL-3, R port AGPL-3. Coefficients taken from the source on 2026-11-13 and
verified against the package README example outputs (tests/test_scores.py).

Important notes
- The source code only contains the 10-year baseline survival (female 0.986227273941040,
  male 0.978732228279114). For other horizons PARAMS["qd_baseline_time_scaling"]="power":
  S0(t) = S0(10)^(t/10) (constant baseline hazard assumption). [DECISION PENDING] — Arm 2 recalibration
  does not depend on this assumption, since it re-estimates the baseline at the horizon from UAE data.
- Age outside 25–84 → NaN (source: error). BMI is clipped to 20–40 (source: clips with a warning).
- Lab values are not inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import codelists
from ..config import PARAMS

SURVIVOR_10Y = {"Female": 0.986227273941040, "Male": 0.978732228279114}
AGE_RANGE = (25, 85)        # valid: 25 <= age < 85 (outside → NaN; NB0 demographics reports the share outside)

COEF = {
    "Female": {
        "ethn": {"WhiteNA": 0.0, "Indian": 1.0695857881565456, "Pakistani": 1.3430172097414006,
                 "Bangladeshi": 1.8029022579794518, "OtherAsian": 1.127465451770802,
                 "BlackCaribbean": 0.42146314902399101, "BlackAfrican": 0.2850919645908353,
                 "Chinese": 0.88151087975891995, "Other": 0.36605733431684873},
        "smoke": [0.0, 0.065601690175059055, 0.28450988673698374, 0.3567664381700702, 0.53595171106787753],
        "age_1": 4.3400852699139278, "age_2": -0.0048771702696158879,
        "bmi_1": 2.9320361259524925, "bmi_2": -0.04740020587484349,
        "town": 0.037340569618049151,
        "apsy": 0.55267646110984381, "ster": 0.26792233680674599, "cvd": 0.17797229054586691,
        "gdm": 1.5248871531467574, "learn": 0.27835143587172717, "psy": 0.26180852109179059,
        "pcos": 0.34061739882066661, "stat": 0.65907287732808217, "htn": 0.43947582858137119,
        "fhdm": 0.53133594565587339,
        "age1_apsy": -0.80315183983163951, "age1_learn": -0.86415960028820571, "age1_stat": -1.9757776696583935,
        "age1_bmi1": 0.65531387575629452, "age1_bmi2": -0.036209657201630177, "age1_fhdm": -0.26411714505588962,
        "age2_apsy": 0.00046840411810210498, "age2_learn": 0.00067249688089533602, "age2_stat": 0.0023750534194347966,
        "age2_bmi1": -0.0044719662445263054, "age2_bmi2": 0.0001185479967753342, "age2_fhdm": 0.00041610258289047683,
        "centre": {"age_1": 2.123332023620606, "age_2": 91.644744873046875,
                   "bmi_1": 2.571253299713135, "bmi_2": 16.999439239501953, "town": 0.391116052865982},
    },
    "Male": {
        "ethn": {"WhiteNA": 0.0, "Indian": 1.1000230829124793, "Pakistani": 1.290384012614721,
                 "Bangladeshi": 1.6740908848727458, "OtherAsian": 1.1400446789147816,
                 "BlackCaribbean": 0.46824681690655806, "BlackAfrican": 0.69905649963015448,
                 "Chinese": 0.68943657127111568, "Other": 0.41722228467738209},
        "smoke": [0.0, 0.16387409105485573, 0.31851449113958979, 0.32207266567783432, 0.45052437163409531],
        "age_1": 4.4642324388691348, "age_2": -0.0040750108019255568,
        "bmi_1": 0.95129027867120675, "bmi_2": -0.14352488277885475,
        "town": 0.025918182067678725,
        "apsy": 0.42101092346005436, "ster": 0.22183580932925384, "cvd": 0.20269605756290021,
        "gdm": 0.0, "learn": 0.23315321407986961, "psy": 0.22770449520517727,
        "pcos": 0.0, "stat": 0.58490075431141342, "htn": 0.33379392183501078,
        "fhdm": 0.64799284899369536,
        "age1_apsy": -0.94637722268534152, "age1_learn": -0.93842375526499833, "age1_stat": -1.7479070653003299,
        "age1_bmi1": 0.45147599241879766, "age1_bmi2": -0.10795481262776381, "age1_fhdm": -0.60118530429301198,
        "age2_apsy": -0.0000519927442172335, "age2_learn": 0.00071026438559688141, "age2_stat": 0.0013508364599531669,
        "age2_bmi1": -0.0011797722394560309, "age2_bmi2": 0.00021471509139319291, "age2_fhdm": 0.00049141855940878034,
        "centre": {"age_1": 1.496392488479614, "age_2": 89.048171997070313,
                   "bmi_1": 6.817805767059326, "bmi_2": 17.801923751831055, "town": 0.515986680984497},
    },
}

BINARY = ["fhdm", "cvd", "htn", "ster", "apsy", "stat", "psy", "learn", "gdm", "pcos"]
OUT_OF_SCOPE = ["ster", "apsy", "stat", "psy", "learn", "gdm", "pcos"]   # not requested in the revised MVP


def _transforms(sex: str, age: np.ndarray, bmi: np.ndarray):
    dage, dbmi = age / 10.0, bmi / 10.0
    c = COEF[sex]["centre"]
    if sex == "Female":
        a1, a2 = dage ** 0.5, dage ** 3
        b1, b2 = dbmi, dbmi ** 3
    else:
        a1, a2 = np.log(dage), dage ** 3
        b1, b2 = dbmi ** 2, dbmi ** 3
    return a1 - c["age_1"], a2 - c["age_2"], b1 - c["bmi_1"], b2 - c["bmi_2"]


def linear_predictor(df: pd.DataFrame) -> pd.Series:
    """Score (log-hazard, centred). Input columns: sex, age, bmi, ethn_qd, smoke_cat (0–4),
    townsend and the BINARY flags (bool/0-1). Invalid row → NaN."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for sex in ("Female", "Male"):
        m = (df["sex"] == sex).to_numpy()
        if not m.any():
            continue
        d = df.loc[m]
        cf = COEF[sex]
        age = d["age"].astype(float).to_numpy()
        bmi = np.clip(d["bmi"].astype(float).to_numpy(), 20.0, 40.0)
        a1, a2, b1, b2 = _transforms(sex, age, bmi)
        s = d["ethn_qd"].map(cf["ethn"]).astype(float).to_numpy()
        sm = d["smoke_cat"].astype(float).to_numpy()
        s = s + np.where(np.isnan(sm), np.nan, np.take(cf["smoke"], np.nan_to_num(sm).astype(int)))
        s = s + cf["age_1"] * a1 + cf["age_2"] * a2 + cf["bmi_1"] * b1 + cf["bmi_2"] * b2
        s = s + cf["town"] * (d["townsend"].astype(float).to_numpy() - cf["centre"]["town"])
        f = {k: d[k].astype(float).to_numpy() for k in BINARY}
        for k in BINARY:
            s = s + cf[k] * f[k]
        for k in ("apsy", "learn", "stat", "fhdm"):
            s = s + cf[f"age1_{k}"] * a1 * f[k] + cf[f"age2_{k}"] * a2 * f[k]
        s = s + cf["age1_bmi1"] * a1 * b1 + cf["age1_bmi2"] * a1 * b2
        s = s + cf["age2_bmi1"] * a2 * b1 + cf["age2_bmi2"] * a2 * b2
        valid = (age >= AGE_RANGE[0]) & (age < AGE_RANGE[1]) & ~np.isnan(bmi)
        out.loc[m] = np.where(valid, s, np.nan)
    return out


def baseline_survival(sex: pd.Series, years: float, p: dict = PARAMS) -> pd.Series:
    s10 = sex.map(SURVIVOR_10Y).astype(float)
    if years == 10:
        return s10
    if p["qd_baseline_time_scaling"] != "power":
        raise ValueError("Unknown qd_baseline_time_scaling")
    return s10 ** (years / 10.0)


def risk(lp: pd.Series, sex: pd.Series, years: float = 10, p: dict = PARAMS) -> pd.Series:
    """Probability (0–1): 1 − S0(t)^exp(lp)."""
    return 1.0 - baseline_survival(sex, years, p) ** np.exp(lp)


def prepare_inputs(snap: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """Convert phenotype.core_snapshot output into QDiabetes inputs.

    Extra columns: qd_variant ('reduced_8core' | 'full'), qd_computable (bool), qd_missing (reason).
    """
    x = pd.DataFrame(index=snap.index)
    x["sex"] = snap["sex"]
    x["age"] = snap["age"]
    x["bmi"] = snap["bmi"]
    x["ethn_qd"] = codelists.map_ethnicity_qdiabetes(snap["ethnicity"])
    sm = snap["smoking_cat"].astype("float")
    # dtype=bool: in pandas 2 boolean becomes an object array and ~ turns it into the integers -1/-2
    current = snap["smoking_raw"].astype("string").str.lower().eq("current").fillna(False).to_numpy(dtype=bool)
    sm = sm.where(~current, p["qd_smoking_current_category"])
    if p["qd_missing_smoking_as_non"]:
        sm = sm.fillna(0)
    x["smoke_cat"] = sm
    x["townsend"] = p["qd_townsend"]
    x["fhdm"] = snap["family_history"].astype(bool)
    x["cvd"] = snap["cvd"].astype(bool)
    x["htn"] = snap["htn_treated_qd"].astype(bool)
    src = {"ster": "corticosteroid", "apsy": "apsy", "stat": "statin", "psy": "psy",
           "learn": "learn", "gdm": "gdm", "pcos": "pcos"}
    for k, col in src.items():
        x[k] = False if p["qd_force_reduced_model"] else snap[col].astype(bool)
    x.loc[x["sex"] == "Male", ["gdm", "pcos"]] = False
    x["qd_variant"] = "reduced_8core" if p["qd_force_reduced_model"] else "full"

    reasons = pd.Series("", index=x.index, dtype=object)
    for cond, why in [(~x["sex"].isin(["Female", "Male"]), "sex;"),
                      (~x["age"].between(25, 84.999), "age_out_of_range;"),
                      (x["bmi"].isna(), "bmi_missing;"),
                      (x["smoke_cat"].isna(), "smoking_missing;")]:
        reasons = reasons + np.where(cond.fillna(True), why, "")
    x["qd_missing"] = reasons
    x["qd_computable"] = reasons == ""
    return x


def score(snap: pd.DataFrame, years: float = 10, p: dict = PARAMS) -> pd.DataFrame:
    """Snapshot → lp and horizon risk (0–1). NaN for rows that cannot be computed."""
    x = prepare_inputs(snap, p)
    lp = linear_predictor(x).where(x["qd_computable"])
    x["qd_lp"] = lp
    x[f"qd_risk_{years:g}y"] = risk(lp, x["sex"], years, p)
    return x
