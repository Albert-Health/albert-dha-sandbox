"""Leicester Risk Assessment (LRA / Diabetes UK risk score) — puan tablosu.

Kaynak: Gray LJ et al., Diabet Med 2010;27:887–895 (Leicester Risk Assessment score).
Toplam 0–47; kategoriler NHS Health Check raporuyla doğrulandı (düşük 0–6, artmış 7–15,
orta 16–24, yüksek 25–47); pratikte ≥16 "yüksek risk" eşiği.
[DOĞRULAMA BEKLİYOR] Madde bazında puanlar birincil makalenin tablosundan teyit edilmeli
(enclave öncesi erişilemedi); toplam maksimum 47 ile tutarlı.

Not: LRS mevcut (tanı konmamış) IGR/T2D tespiti için geliştirilmiş kesitsel bir skordur;
C3'teki incident benchmark dış kullanım (off-label) olarak raporlanır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import codelists
from ..config import PARAMS

POINTS = {
    "age": [(0, 50, 0), (50, 60, 5), (60, 70, 9), (70, 200, 13)],      # [alt, üst)
    "male": 1,
    "non_white": 6,
    "family_history": 5,
    "waist_cm": [(0, 90, 0), (90, 100, 4), (100, 110, 6), (110, 1000, 9)],
    "bmi": [(0, 25, 0), (25, 30, 3), (30, 35, 5), (35, 1000, 8)],
    "hypertension": 5,                                                   # tanı VEYA ilaç
}
CATEGORIES = [(0, 7, "low"), (7, 16, "increased"), (16, 25, "moderate"), (25, 48, "high")]
MAX_SCORE = 47


def _band(x: pd.Series, bands) -> pd.Series:
    out = pd.Series(np.nan, index=x.index)
    for lo, hi, pts in bands:
        out[(x >= lo) & (x < hi)] = pts
    return out


def score(snap: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """phenotype.core_snapshot → LRS puanı. Eksik girdi → NaN + lrs_missing nedeni."""
    eth = snap["ethnicity"].astype("string").str.strip().str.lower()
    unknown = eth.isna() | eth.isin(codelists.ETHNICITY_UNKNOWN)
    eth_pts = pd.Series(np.where(eth.isin(codelists.LRS_WHITE).fillna(False), 0, POINTS["non_white"]),
                        index=snap.index, dtype=float)
    if p["lrs_unknown_ethnicity_as_missing"]:
        eth_pts = eth_pts.where(~unknown.fillna(True))
    parts = {
        "lrs_age": _band(snap["age"], POINTS["age"]),
        "lrs_sex": pd.Series(np.where(snap["sex"] == "Male", POINTS["male"], 0), index=snap.index, dtype=float)
                     .where(snap["sex"].isin(["Male", "Female"])),
        "lrs_ethnicity": eth_pts,
        "lrs_fh": snap["family_history"].astype(bool).astype(float) * POINTS["family_history"],
        "lrs_waist": _band(snap["waist_cm"], POINTS["waist_cm"]),
        "lrs_bmi": _band(snap["bmi"], POINTS["bmi"]),
        "lrs_htn": snap["htn_lrs"].astype(bool).astype(float) * POINTS["hypertension"],
    }
    x = pd.DataFrame(parts)
    reasons = pd.Series("", index=x.index, dtype=object)
    for col, why in [("lrs_age", "age;"), ("lrs_sex", "sex;"), ("lrs_ethnicity", "ethnicity;"),
                     ("lrs_waist", "waist_missing;"), ("lrs_bmi", "bmi_missing;")]:
        reasons = reasons + np.where(x[col].isna(), why, "")
    x["lrs_missing"] = reasons
    x["lrs_computable"] = reasons == ""
    x["lrs_score"] = x[list(parts)].sum(axis=1, min_count=len(parts)).where(x["lrs_computable"])
    x["lrs_category"] = pd.cut(x["lrs_score"], [c[0] for c in CATEGORIES] + [CATEGORIES[-1][1]],
                               right=False, labels=[c[2] for c in CATEGORIES])
    x["lrs_high_risk"] = (x["lrs_score"] >= p["lrs_high_risk_threshold"]).where(x["lrs_computable"])
    return x
