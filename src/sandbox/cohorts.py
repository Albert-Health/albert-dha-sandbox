"""Kohort kuralları.

- Pozitif havuz (C1/C2, Interim Data Assessment): T2DM veya prediyabet (tanı ve/veya lab),
  T1D hariç. A10 ilacı tek başına statü belirlemez, ayrı raporlanır.
- C3 (Non-Diabetic Cohort Spec v2): ilk normal glisemik değer = index; öncesinde hiç
  diyabet/prediyabet/A10 yok; T1D hiç yok; 25–84 yaş; index sonrası ≥1 glisemik ölçüm.
  Sansür: son glisemik ölçüm.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import codelists, phenotype
from .config import PARAMS
from .io.schema import Dataset


def data_end_date(ds: Dataset) -> pd.Timestamp:
    dates = [ds[t]["date"].max() for t in ("conditions", "medications", "labs", "observations")
             if len(ds[t])]
    return max(d for d in dates if pd.notna(d))


# --------------------------------------------------------------------------
# Pozitif havuz (C1 / C2)
# --------------------------------------------------------------------------
def positive_pool(ds: Dataset, ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """Hasta başı: status (T2DM/Prediabetes), ilk tarih, kanıt tipleri, A10 bayrağı."""
    ev = phenotype.dm_evidence(ds) if ev is None else ev
    t1d_ids = set(ev.loc[ev["status"] == "t1d", "patient_id"])
    ev = ev[~ev["patient_id"].isin(t1d_ids)]
    defining = ev[ev["evidence"] != "medication"]

    t2d = defining[defining["status"] == "t2d"].groupby("patient_id")["date"].min()
    pre = defining[defining["status"] == "pre"].groupby("patient_id")["date"].min()
    ids = t2d.index.union(pre.index)
    out = pd.DataFrame(index=ids.rename("patient_id"))
    out["status"] = np.where(out.index.isin(t2d.index), "T2DM", "Prediabetes")
    out["first_t2dm_date"] = t2d.reindex(out.index)
    out["first_prediabetes_date"] = pre.reindex(out.index)
    ev_types = defining.groupby("patient_id")["evidence"].agg(lambda s: "|".join(sorted(set(s))))
    out["evidence_types"] = ev_types.reindex(out.index)
    a10_ids = set(ev.loc[ev["evidence"] == "medication", "patient_id"])
    out["has_a10"] = out.index.isin(a10_ids)
    return out


POSITIVE_REFERENCES = ("data_end", "first_evidence")


def positive_reference_dates(ds: Dataset, pool: pd.DataFrame, how: str) -> pd.Series:
    """C1/C2 snapshot'ı için hasta başı referans tarihi.

    "data_end": veri sonu — C1 tanımı ("as currently recorded"); tamlık ve seçilim etkisi bununla.
    "first_evidence": statüyü belirleyen ilk kanıt tarihi (T2DM → ilk T2DM, prediyabet → ilk
      prediyabet kanıtı), o gün dahil. "Skor bu hastayı tanı anında yakalar mıydı" sorusu için;
      tanı sonrası kayıtlar (ör. tedavi sonrası BMI) girmez.
    """
    if how == "data_end":
        return pd.Series(data_end_date(ds), index=pool.index)
    if how == "first_evidence":
        return pool["first_t2dm_date"].where(pool["status"] == "T2DM", pool["first_prediabetes_date"])
    raise ValueError(f"bilinmeyen referans: {how!r} (seçenekler: {POSITIVE_REFERENCES})")


def build_c1_c2(ds: Dataset, p: dict = PARAMS) -> dict:
    """Pozitif havuzdan C1 (8 değişken tam, cap) ve C2 (rastgele, cap) seçer.

    Dönüş: {"pool": df, "c1_ids": [...], "c2_ids": [...], "report": {...}}
    """
    pool = positive_pool(ds)
    ref = pd.Series(data_end_date(ds), index=pool.index)
    snap = phenotype.core_snapshot(ds, ref, lookback_days=None, p=p)
    pool = pool.join(snap)

    rng = np.random.default_rng(p["seed"])
    complete = pool.index[pool["ok_core8"]]
    c1_ids = list(complete) if len(complete) <= p["c1_cap"] else \
        list(rng.choice(np.array(complete), size=p["c1_cap"], replace=False))
    # C2: C1'den bağımsız rastgele örneklem; C1 hastaları çerçeveden çıkarılmaz
    rng2 = np.random.default_rng(p["seed"] + 1)
    all_ids = np.array(pool.index)
    c2_ids = list(all_ids) if len(all_ids) <= p["c2_cap"] else \
        list(rng2.choice(all_ids, size=p["c2_cap"], replace=False))

    report = {
        "positive_pool_n": int(len(pool)),
        "positive_pool_t2dm": int((pool["status"] == "T2DM").sum()),
        "positive_pool_prediabetes": int((pool["status"] == "Prediabetes").sum()),
        "c1_achievable_n": int(len(complete)),
        "c1_delivered_n": len(c1_ids),
        "c2_delivered_n": len(c2_ids),
        "c1_c2_overlap_n": len(set(c1_ids) & set(c2_ids)),
        "reference_date": str(ref.iloc[0].date()) if len(ref) else None,
    }
    return {"pool": pool, "c1_ids": c1_ids, "c2_ids": c2_ids, "report": report}


# --------------------------------------------------------------------------
# C3 — non-diabetic, incident
# --------------------------------------------------------------------------
def build_c3(ds: Dataset, p: dict = PARAMS) -> dict:
    """v2 kurallarıyla C3 kohortu: index, outcome, sansür, 8 değişken (index'te).

    Dönüş: {"cohort": df (patient_id index), "funnel": dict}
    """
    glyc = phenotype.glycaemic_events(ds, p)
    ev = phenotype.dm_evidence(ds, glyc)
    pts = ds["patients"].drop_duplicates("patient_id").set_index("patient_id")
    funnel = {"patients_total": int(len(pts))}

    t1d_ids = set(ev.loc[ev["status"] == "t1d", "patient_id"])
    bad = ev[ev["status"].isin(["t2d", "pre"])]                     # A10 dahil
    first_bad = bad.groupby("patient_id")["date"].min()

    cand = glyc[(glyc["status"] == "normal") & glyc["kind"].isin(["hba1c", "fpg"])].copy()
    funnel["with_normal_hba1c_or_fpg"] = int(cand["patient_id"].nunique())

    cand = cand[~cand["patient_id"].isin(t1d_ids)]
    funnel["after_t1d_exclusion"] = int(cand["patient_id"].nunique())

    # Index öncesi/aynı gün hiç DM/prediyabet/A10 kanıtı olmamalı
    cand["first_bad"] = cand["patient_id"].map(first_bad)
    cand = cand[cand["first_bad"].isna() | (cand["date"] < cand["first_bad"])]
    funnel["after_prevalent_dm_pre_exclusion"] = int(cand["patient_id"].nunique())

    dob = cand["patient_id"].map(pts["date_of_birth"])
    cand["age"] = (cand["date"] - dob).dt.days / 365.25
    cand = cand[cand["age"].between(p["age_min"], p["age_max"] + 0.999)]
    funnel["after_age_25_84"] = int(cand["patient_id"].nunique())

    last_glyc = glyc.groupby("patient_id")["date"].max()
    cand["last_glyc"] = cand["patient_id"].map(last_glyc)
    cand = cand[cand["last_glyc"] > cand["date"] + pd.Timedelta(days=p["min_followup_gap_days"])]
    funnel["after_followup_measurement"] = int(cand["patient_id"].nunique())

    # Uygun en erken normal değer = index (aynı gün HbA1c > FPG önceliği)
    cand["kprio"] = cand["kind"].map({"hba1c": 0, "fpg": 1})
    idx = cand.sort_values(["patient_id", "date", "kprio"]).drop_duplicates("patient_id").set_index("patient_id")
    c3 = pd.DataFrame(index=idx.index)
    c3["index_date"] = idx["date"]
    c3["baseline_lab_type"] = idx["kind"]
    c3["baseline_lab_value"] = idx["value"]

    if p.get("c3_cap"):
        rng = np.random.default_rng(p["seed"] + 2)
        keep = rng.choice(np.array(c3.index), size=min(p["c3_cap"], len(c3)), replace=False)
        c3 = c3.loc[sorted(keep)]
    funnel["c3_final"] = int(len(c3))

    # Takip ölçümleri
    g = glyc.merge(c3["index_date"], left_on="patient_id", right_index=True)
    after = g[g["date"] > g["index_date"]].sort_values(["patient_id", "date"])
    c3["n_followup_glycaemic"] = after.groupby("patient_id").size().reindex(c3.index).fillna(0).astype(int)
    last = after.drop_duplicates("patient_id", keep="last").set_index("patient_id")
    c3["last_glycaemic_date"] = last["date"].reindex(c3.index)
    c3["last_glycaemic_type"] = last["kind"].reindex(c3.index)
    c3["last_glycaemic_value"] = last["value"].reindex(c3.index)

    # Outcome'lar
    e = ev.merge(c3["index_date"], left_on="patient_id", right_index=True)
    e = e[e["date"] > e["index_date"]].copy()
    e["prio"] = e["evidence"].map(phenotype.EVIDENCE_PRIORITY)
    t2d = e[e["status"] == "t2d"].sort_values(["patient_id", "date", "prio"])
    primary = t2d[t2d["evidence"] != "medication"].drop_duplicates("patient_id").set_index("patient_id")
    anyev = t2d.drop_duplicates("patient_id").set_index("patient_id")
    c3["incident_diabetes"] = c3.index.isin(primary.index)
    c3["incident_date"] = primary["date"].reindex(c3.index)
    c3["incident_evidence"] = primary["evidence"].reindex(c3.index)
    # Duyarlılık: ilaç-tek kanıt dahil
    c3["incident_diabetes_incl_med"] = c3.index.isin(anyev.index)
    c3["incident_date_incl_med"] = anyev["date"].reindex(c3.index)

    pre = e[e["status"] == "pre"].sort_values(["patient_id", "date"]).drop_duplicates("patient_id").set_index("patient_id")
    c3["incident_prediabetes"] = c3.index.isin(pre.index)
    c3["prediabetes_date"] = pre["date"].reindex(c3.index)

    # Washout: index'e çok yakın olay → prevalent sayılır, hasta çıkarılır
    w = p.get("outcome_washout_days", 0) or 0
    if w > 0:
        early = c3["incident_diabetes"] & ((c3["incident_date"] - c3["index_date"]).dt.days <= w)
        c3 = c3[~early]
    funnel["after_outcome_washout"] = int(len(c3))

    # Takip sonu ve süre (birincil outcome)
    c3["followup_end"] = c3["incident_date"].where(c3["incident_diabetes"], c3["last_glycaemic_date"])
    c3["followup_years"] = (c3["followup_end"] - c3["index_date"]).dt.days / 365.25

    # Index'te 8 çekirdek değişken
    snap = phenotype.core_snapshot(ds, c3["index_date"], lookback_days=p["predictor_lookback_days"], p=p)
    c3 = c3.join(snap.drop(columns=["ref_date"]))
    funnel["incident_t2d_events"] = int(c3["incident_diabetes"].sum())
    return {"cohort": c3, "funnel": funnel}


def subset(ds: Dataset, ids, cohort: str) -> Dataset:
    """Kohort hastalarına ait tüm tablo satırlarını içeren yeni Dataset."""
    ids = set(ids)
    return Dataset(source=ds.source, cohort=cohort,
                   tables={n: df[df["patient_id"].isin(ids)].reset_index(drop=True)
                           for n, df in ds.tables.items()})
