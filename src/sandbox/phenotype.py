"""Glisemik ölçümler, diyabet/prediyabet kanıtı ve 8 çekirdek değişkenin
belirli bir referans tarihindeki durumu.

Lab değerleri yalnızca outcome / uygunluk tanımında kullanılır; asla model girdisi değildir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import codelists
from .config import PARAMS
from .io.schema import Dataset
from .scores import lrs

# Aynı gün birden çok kanıt varsa öncelik (küçük = önce)
EVIDENCE_PRIORITY = {"lab_hba1c": 0, "lab_fpg": 1, "lab_ogtt": 2, "lab_random_glucose": 3,
                     "diagnosis": 4, "medication": 5}


# --------------------------------------------------------------------------
# Glisemik ölçümler
# --------------------------------------------------------------------------
def glycaemic_events(ds: Dataset, p: dict = PARAMS) -> pd.DataFrame:
    """Glisemik lablar, birim normalize edilmiş, ADA sınıflı.

    Dönüş: patient_id, date, kind (hba1c/fpg/ogtt_2h/random_glucose), value, status (normal/pre/dm/na)
    """
    labs = ds["labs"]
    kind = labs["loinc"].map(codelists.LOINC_LAB)
    g = labs.assign(kind=kind).dropna(subset=["kind", "value", "date"]).copy()
    unit = g["unit"].astype("string").str.lower().fillna("")

    # HbA1c IFCC (mmol/mol) → NGSP %
    ifcc = (g["kind"] == "hba1c_ifcc") | ((g["kind"] == "hba1c") & unit.str.contains("mmol/mol"))
    g.loc[ifcc, "value"] = g.loc[ifcc, "value"] / 10.929 + 2.15
    g.loc[ifcc, "kind"] = "hba1c"
    # Glukoz mmol/L → mg/dL
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
        default="na",  # random glucose < 200 → normallik kanıtı değil
    )
    g["status"] = status
    return g[["patient_id", "date", "kind", "value", "unit", "status"]].reset_index(drop=True)


def dm_evidence(ds: Dataset, glyc: pd.DataFrame | None = None) -> pd.DataFrame:
    """Diyabet / prediyabet / T1D kanıtları (uzun format).

    Dönüş: patient_id, date, status (t2d/pre/t1d), evidence
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
# Çekirdek değişkenler (snapshot)
# --------------------------------------------------------------------------
_MISSING_ETH = {"", "not recorded", "unknown", "not stated", "na", "n/a", "none", "other - not stated"}
# FamilyHistory kaydının "kayıt var" sayıldığı değerler (unknown / unmapped sayılmaz)
FH_RECORDED_VALUES = {"positive", "negative", "positive_non_first_degree"}


def _z68_to_bmi(code: pd.Series) -> pd.Series:
    """Z68.xx bandını yaklaşık BMI'ye çevirir (bant ortası). Sadece yedek kaynak."""
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
    """df satırlarını hastanın referans tarihi penceresine filtreler: (ref - lookback, ref]."""
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
    """Her hasta için referans tarihindeki 8 çekirdek değişken (+ bel, + QDiabetes ek bayrakları).

    ref: index = patient_id, değer = referans tarihi (Timestamp).
    lookback_days: ölçüm değerleri (BMI, bel, ilaç) için pencere; None = tüm geçmiş.
    Tanı bayrakları (KVH, HT tanısı, FH vb.) her zaman tüm geçmişe bakar.
    """
    ref = ref.dropna()
    out = pd.DataFrame(index=ref.index.rename("patient_id"))
    pts = ds["patients"].drop_duplicates("patient_id").set_index("patient_id")

    # Demografi
    out["sex"] = pts["sex"].reindex(out.index)
    dob = pts["date_of_birth"].reindex(out.index)
    out["age"] = (ref - dob).dt.days / 365.25
    # Etnik grup: PARAMS["ethnicity_source"] sütunundan (uyruk veya NABIDH etnisitesi)
    src = p.get("ethnicity_source", PARAMS["ethnicity_source"])
    eth = pts[codelists.ETHNICITY_SOURCE_COLUMN[src]].reindex(out.index)
    eth = eth.where(~eth.astype("string").str.strip().str.lower().isin(_MISSING_ETH).fillna(True))
    out["ethnicity_source_value"] = eth
    out["ethnicity"] = codelists.ethnic_group(eth, src)

    # Gözlemler (pencere içi)
    obs_all = ds["observations"]
    obs_win = _window(obs_all, ref, lookback_days)
    num = obs_win.assign(v=pd.to_numeric(obs_win["value"], errors="coerce"))

    bmi_direct = _latest(num[(num["concept"] == "bmi") & num["v"].between(12, 80)], "v")
    w = _latest(num[(num["concept"] == "weight_kg") & num["v"].between(25, 350)], "v")
    # Boy yetişkinde stabil: tüm geçmişten en son değer
    obs_hist = _window(obs_all, ref, None)
    numh = obs_hist.assign(v=pd.to_numeric(obs_hist["value"], errors="coerce"))
    h = _latest(numh[(numh["concept"] == "height_cm") & numh["v"].between(120, 230)], "v")
    bmi_hw = (w / (h.reindex(w.index) / 100) ** 2).dropna()
    bmi_hw = bmi_hw[bmi_hw.between(12, 80)]

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

    out["waist_cm"] = _latest(num[(num["concept"] == "waist_cm") & num["v"].between(40, 250)], "v").reindex(out.index)

    # Sigara: en son durum (tüm geçmiş, ref'e kadar) — önce yapısal alan, sonra tanı kodu.
    # Yalnızca tanınan değerler (never/ex/current/light/moderate/heavy …) sayılır; "unknown" veya
    # adapter'ın eşleyemediği değerler önceki bilgili kaydı ezmez.
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
    out["smoking_cat"] = out["smoking_raw"].map(codelists.SMOKING_TEXT_TO_CAT)

    # Tanı bayrakları (tüm geçmiş, ref dahil)
    for grp, col in [("family_history_dm", "family_history"), ("cvd", "cvd"), ("hypertension", "htn_dx"),
                     ("gdm", "gdm"), ("pcos", "pcos"), ("learning_disability", "learn"),
                     ("schizophrenia_bipolar", "psy")]:
        ids = set(cond_hist.loc[codelists.match_dx(cond_hist, grp), "patient_id"])
        out[col] = out.index.isin(ids)

    # Aile öyküsü: Z83.3 tanısı VEYA FamilyHistory kaydı (adapter → observations concept
    # family_history_dm; değer positive / negative / positive_non_first_degree / unknown).
    # Pozitif = birinci derece akrabada diyabet (QDiabetes ve LRS tanımı). Kayıt var = pozitif veya negatif.
    fh = obs_hist[obs_hist["concept"] == "family_history_dm"]
    fh_val = fh["value"].astype("string").str.strip().str.lower()
    fh_pos = set(fh.loc[fh_val.eq("positive").fillna(False).astype(bool), "patient_id"])
    fh_rec = set(fh.loc[fh_val.isin(list(FH_RECORDED_VALUES)).fillna(False).astype(bool), "patient_id"])
    dx_fh = out["family_history"]
    out["family_history"] = dx_fh | out.index.isin(fh_pos)
    out["family_history_recorded"] = dx_fh | out.index.isin(fh_rec)

    # İlaç bayrakları (pencere içi)
    med_win = _window(ds["medications"], ref, lookback_days)
    for grp, col in [("antihypertensive", "htn_med"), ("statin", "statin"),
                     ("corticosteroid", "corticosteroid"), ("atypical_antipsychotic", "apsy")]:
        ids = set(med_win.loc[codelists.match_atc(med_win, grp), "patient_id"])
        out[col] = out.index.isin(ids)

    out["htn_treated_qd"] = out["htn_dx"] & out["htn_med"]      # QDiabetes: tanı VE ilaç
    out["htn_lrs"] = out["htn_dx"] | out["htn_med"]             # LRA 2010: tanı VEYA ilaç
    # LPRS (Gray 2012) yalnız ilacı kullanır: htn_med

    # Tamlık bayrakları (C1 tanımı + KPI'lar)
    out["ok_sex"] = out["sex"].isin(["Male", "Female"])
    out["ok_age"] = out["age"].notna()
    out["ok_ethnicity"] = out["ethnicity"].notna()
    out["ok_bmi"] = out["bmi_source"].isin(["direct", "height_weight"])   # Z68 bandı tam sayılmaz
    out["ok_smoking"] = out["smoking_raw"].notna()
    out["ok_family_history"] = out["family_history_recorded"] if p["c1_require_fh_record"] else True
    out["ok_cvd"] = True            # EHR'de var/yok
    out["ok_hypertension"] = True   # tanı ve ilaç ayrı alanlar; var/yok
    ok_cols = [f"ok_{v}" for v in codelists.CORE_VARIABLES]
    out["ok_core8"] = out[ok_cols].all(axis=1)
    # Leicester skoru birlikte tamlığı: bel çevresi yalnız LRA 2010 varyantında gerekir (K-LRS)
    out["ok_lrs"] = out[["ok_sex", "ok_age", "ok_ethnicity", "ok_bmi", "ok_family_history",
                         "ok_hypertension"]].all(axis=1)
    if lrs.needs_waist(p):
        out["ok_lrs"] &= out["waist_cm"].notna()
    out["ref_date"] = ref
    return out
