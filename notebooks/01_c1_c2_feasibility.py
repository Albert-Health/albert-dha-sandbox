# ---
# jupyter:
#   jupytext:
#     formats: py:percent
# ---

# %% [markdown]
# # NB1 — C1 / C2 fizibilite (kesitsel)
#
# **Kapsam:** Adım 1 — pozitif kohortlar (T2DM + prediyabet). Veri yapısı ve tamlık kontrolü.
#
# Study Flow 1. ve 2. basamak. **C1'in birincil amacı:** diyabetli / prediyabetli olduğu bilinen
# hastaları QDiabetes ve Leicester skorunun ne oranda "yüksek risk" diye yakaladığı (duyarlılık). **C2:** kayıt
# tamlığı şartı olmadan değişkenlerin NABIDH'te ne kadar dolu olduğu (completeness).
#
# > Tüm hastalar pozitif vakadır, negatif vaka yoktur → yalnızca **duyarlılık** hesaplanır.
# > Özgüllük, PPV, ayrım gücü (C-index, AUROC) ve kalibrasyon burada HESAPLANMAZ (C3 / NB2).
#
# - 8 çekirdek değişkenin tekil ve birlikte tamlığı (T2DM vs prediyabet)
# - C1 (tam kayıt) vs C2 (rastgele) seçilim etkisi: standardize ortalama farkı (SMD)
# - QDiabetes-2018 A ve Leicester skoru hesaplanabilirlik oranı, eksiklik nedenleri, skor dağılımları
#   Leicester varyantı `PARAMS["lrs_variant"]`: varsayılan LPRS (Gray 2012, bel çevresi yok)
#   [KARAR: 2026-11-14, ensargunesdogdu + Zeynep Pelin Polat — K-LRS]; LRA 2010 duyarlılık için.
# - C1 (ve karşılaştırma için C2) yakalama oranı (duyarlılık) — §4
#
# Referans tarih: tamlık ve seçilim etkisi için veri sonu ("as currently recorded"), tüm geçmiş.
# Duyarlılık iki referansla yan yana raporlanır (veri sonu / ilk kanıt günü) [KARAR BEKLİYOR — D22].

# %%
import json
import os
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "src" / "sandbox").exists())
sys.path.insert(0, str(ROOT / "src"))

import matplotlib

if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sandbox import codelists, cohorts, metrics, phenotype, sdc
from sandbox.audit import Run
from sandbox.config import CANONICAL_DIR, PARAMS
from sandbox.io import schema
from sandbox.scores import lprs, lrs, qdiabetes2018a as qd

SOURCE = os.environ.get("SANDBOX_SOURCE", "synthetic")   # enclave'de: "nabidh"
P = dict(PARAMS)
P.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))   # duyarlılık çalıştırmaları (audit'e yazılır)
run = Run("nb01_c1_c2_feasibility", params=P, source=SOURCE)
run.add_inputs([CANONICAL_DIR / SOURCE / c for c in ("c1", "c2")])
data = {c: schema.read_dataset(CANONICAL_DIR, SOURCE, c) for c in ("c1", "c2")}
run.log("datasets loaded", source=SOURCE, n={c: d.n_patients for c, d in data.items()})

snaps = {}
for c, d in data.items():
    pool = cohorts.positive_pool(d)
    ref = pd.Series(cohorts.data_end_date(d), index=pool.index)
    s = phenotype.core_snapshot(d, ref, lookback_days=None, p=P).join(pool[["status", "has_a10"]])
    s = s.join(qd.score(s, years=10, p=P)[["qd_computable", "qd_missing", "qd_variant", "qd_risk_10y", "ethn_qd"]])
    s = s.join(lrs.score(s, p=P)[["lrs_computable", "lrs_missing", "lrs_score", "lrs_category", "lrs_variant"]])
    snaps[c] = s
    excluded = d.n_patients - len(s)
    run.log(f"{c} snapshot", n=len(s), not_in_positive_pool=excluded)
print({c: len(s) for c, s in snaps.items()})
LRS_LABEL, LRS_THR = lrs.label(P), lrs.threshold(P)
print("Leicester varyantı:", LRS_LABEL, "| yüksek risk eşiği:", LRS_THR)

# %% [markdown]
# ## 1. Tamlık — değişken bazında ve birlikte (T2DM vs prediyabet)

# %%
ok_cols = [f"ok_{v}" for v in codelists.CORE_VARIABLES]
rows, joint = [], []
for c, s in snaps.items():
    for grp, g in [("all", s), *s.groupby("status")]:
        for col in ok_cols:
            rows.append({"cohort": c, "group": grp, "variable": col[3:], "n": len(g),
                         "complete_pct": round(100 * g[col].astype(bool).mean(), 1)})
        if lrs.needs_waist(P):          # yalnız LRA 2010 (bel zorunlu); LPRS bel istemez
            rows.append({"cohort": c, "group": grp, "variable": "waist (LRS)", "n": len(g),
                         "complete_pct": round(100 * g["waist_cm"].notna().mean(), 1)})
        joint.append({"cohort": c, "group": grp, "n": len(g),
                      "joint_core8_n": int(g["ok_core8"].sum()), "joint_core8_pct": round(100 * g["ok_core8"].mean(), 1),
                      "joint_lrs_n": int(g["ok_lrs"].sum()), "joint_lrs_pct": round(100 * g["ok_lrs"].mean(), 1)})
comp = pd.DataFrame(rows)
joint = pd.DataFrame(joint)
run.save_table(comp, "nb01/completeness_by_variable.csv", "C1/C2 değişken tamlığı (T2DM / prediyabet)")
run.save_table(sdc.suppress_small_counts(joint, ["joint_core8_n", "joint_lrs_n"]),
               "nb01/joint_completeness.csv", "C1/C2 birlikte tamlık")
print(comp.pivot_table(index="variable", columns=["cohort", "group"], values="complete_pct").to_string())
print(joint.to_string(index=False))

# %% [markdown]
# ## 2. Seçilim etkisi: C1 (tam kayıt) vs C2 (rastgele)
# SMD |d| > 0.1 anlamlı dengesizlik olarak işaretlenir.

# %%
def smd(a: pd.Series, b: pd.Series, binary: bool) -> float:
    a, b = a.dropna().astype(float), b.dropna().astype(float)
    if binary:
        p1, p2 = a.mean(), b.mean()
        den = np.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / 2)
        return float((p1 - p2) / den) if den else 0.0
    den = np.sqrt((a.var() + b.var()) / 2)
    return float((a.mean() - b.mean()) / den) if den else 0.0


def features(s: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=s.index)
    f["age"] = s["age"]
    f["bmi"] = s["bmi"]
    f["male"] = s["sex"].eq("Male")
    f["t2dm (vs prediabetes)"] = s["status"].eq("T2DM")
    f["family_history"] = s["family_history"]
    f["cvd"] = s["cvd"]
    f["htn_dx"] = s["htn_dx"]
    f["htn_med"] = s["htn_med"]
    f["smoking_current"] = s["smoking_raw"].astype("string").isin(["current", "light", "moderate", "heavy"])
    f["has_a10"] = s["has_a10"]
    for e in ["Emirati", "Indian", "Pakistani", "Filipino"]:
        f[f"eth_{e}"] = s["ethnicity"].eq(e)
    return f


f1, f2 = features(snaps["c1"]), features(snaps["c2"])
sel = []
for col in f1.columns:
    binary = f1[col].dtype == bool
    sel.append({"variable": col, "c1": round(f1[col].astype(float).mean(), 3), "c2": round(f2[col].astype(float).mean(), 3),
                "smd": round(smd(f1[col], f2[col], binary), 3)})
sel = pd.DataFrame(sel)
sel["imbalance"] = sel["smd"].abs() > 0.1
run.save_table(sel, "nb01/selection_effect_smd.csv", "C1 vs C2 standardize ortalama farkları")
print(sel.to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for ax, col, bins in [(axes[0], "age", 30), (axes[1], "bmi", 30)]:
    for c, s in snaps.items():
        s[col].dropna().plot.hist(bins=bins, ax=ax, alpha=0.5, density=True, label=c.upper())
    ax.set_title(f"{col} — C1 vs C2")
    ax.legend()
fig.tight_layout()
run.save_figure(fig, "nb01/selection_age_bmi.png", "C1 vs C2 yaş/BMI dağılımı")

# %% [markdown]
# ## 3. Skor hesaplanabilirliği ve dağılımları
# QDiabetes: indirgenmiş Model A (`PARAMS["qd_force_reduced_model"]`), 10 yıllık risk.
# Leicester: `lrs_variant`. LPRS (varsayılan) = yaş, cinsiyet, etnisite (BME), BMI, aile öyküsü,
# antihipertansif ilaç — bel çevresi yok; skor doğrusal öngörücüdür (mutlak risk değil). LRA 2010: bel zorunlu.
# `lrs_outside_dev_age_pct`: LPRS geliştirme yaş aralığı (40–75) dışındaki hastalar (ekstrapolasyon).

# %%
comp_rows, reasons = [], []
for c, s in snaps.items():
    for grp, g in [("all", s), *s.groupby("status")]:
        comp_rows.append({"cohort": c, "group": grp, "n": len(g),
                          "qd_computable_pct": round(100 * g["qd_computable"].mean(), 1),
                          "lrs_computable_pct": round(100 * g["lrs_computable"].mean(), 1),
                          "lrs_outside_dev_age_pct": (round(100 * (~g["age"].between(*lprs.DEV_AGE_RANGE)).mean(), 1)
                                                      if P["lrs_variant"] == "practice_2012" else None),
                          "qd_variant": g["qd_variant"].iloc[0] if len(g) else None,
                          "lrs_variant": LRS_LABEL})
    for score_name, col in [("qdiabetes", "qd_missing"), ("lrs", "lrs_missing")]:
        r = s[col].str.split(";").explode()
        r = r[r != ""].value_counts()
        for k, v in r.items():
            reasons.append({"cohort": c, "score": score_name, "reason": k, "n": int(v),
                            "pct": round(100 * v / len(s), 1)})
computability = pd.DataFrame(comp_rows)
reasons = pd.DataFrame(reasons, columns=["cohort", "score", "reason", "n", "pct"])
run.save_table(computability, "nb01/score_computability.csv", f"QDiabetes / {LRS_LABEL} hesaplanabilirlik")
run.save_table(sdc.suppress_small_counts(reasons, ["n"]), "nb01/score_missing_reasons.csv", "Hesaplanamama nedenleri")
print(computability.to_string(index=False))
print(reasons.to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for c, s in snaps.items():
    (100 * s["qd_risk_10y"]).dropna().plot.hist(bins=40, ax=axes[0], alpha=0.5, density=True, label=c.upper())
    if s["lrs_score"].notna().any():
        s["lrs_score"].dropna().plot.hist(bins=range(0, 49, 2) if lrs.VARIANTS[P["lrs_variant"]]["points"] else 30,
                                          ax=axes[1], alpha=0.5, density=True, label=c.upper())
axes[0].set_title("QDiabetes-2018 A — 10 yıllık risk (%)")
axes[1].set_title(f"{LRS_LABEL} — skor")
if LRS_THR is not None:
    axes[1].axvline(LRS_THR, ls="--", color="k")
for ax in axes:
    if ax.get_legend_handles_labels()[0]:
        ax.legend()
fig.tight_layout()
run.save_figure(fig, "nb01/score_distributions.png", "Skor dağılımları (yalnızca betimleyici)")

dist = pd.concat([
    s.groupby("status").agg(qd_median_pct=("qd_risk_10y", lambda x: round(100 * x.median(), 2)),
                            lrs_median=("lrs_score", "median"),
                            lrs_p25=("lrs_score", lambda x: x.quantile(.25)),
                            lrs_p75=("lrs_score", lambda x: x.quantile(.75)),
                            lrs_high_risk_pct=("lrs_score", lambda x: None if LRS_THR is None else
                                               round(100 * (x >= LRS_THR).sum() / max(x.notna().sum(), 1), 1)))
     .assign(cohort=c, lrs_variant=LRS_LABEL).reset_index() for c, s in snaps.items()])
run.save_table(dist, "nb01/score_summary.csv", "Skor özetleri (betimleyici)")
print(dist.to_string(index=False))

# %% [markdown]
# ## 4. C1 — bilinen pozitiflerde yakalama oranı (duyarlılık)
# Study Flow 1. basamağın birincil sorusu: diyabetli / prediyabetli olduğu bilinen hastaların yüzde
# kaçını skor "yüksek risk" buluyor? C2 karşılaştırma için (tamlık şartı olmayan pozitif örneklem).
# - Leicester: skor ≥ etkin varyantın eşiği (`lrs.threshold(P)`: LPRS → `lprs_high_risk_threshold`,
#   D23: şimdilik eşik yok → "Pending"; LRA 2010 → `lrs_high_risk_threshold` = 16). `variant` sütunu
#   hangi skorun kullanıldığını gösterir. QDiabetes: `horizon_years` riski ≥ `qd_risk_threshold_pct`
#   (NB2 ile aynı eşik; D5: şimdilik eşik yok → "Pending").
# - Referans tarihi [KARAR BEKLİYOR — D22]: `data_end` (veri sonu; tamlıkla aynı) ve `first_evidence`
#   (statüyü belirleyen ilk kanıt günü, o gün dahil; tanı sonrası kayıtlar girmez).
# - `sens_computable`: yakalanan / skoru hesaplanabilen (Wilson %95 GA). `sens_all`: yakalanan / tüm
#   hastalar (hesaplanamayan = yakalanmadı).
# - Kısıt: prevalan vakalar (prospektif değil); C1 tam kayıtlı hastalardır (seçilim etkisi §2).

# %%
h = P["horizon_years"]
qd_col = f"qd_risk_{h:g}y"
qd_thr = None if P["qd_risk_threshold_pct"] is None else P["qd_risk_threshold_pct"] / 100
thr_text = {"lrs": "Pending (D23: no LPRS threshold)" if LRS_THR is None else f"score >= {LRS_THR}",
            "qdiabetes": "Pending (D5: no threshold)" if qd_thr is None
            else f"{h:g}y risk >= {P['qd_risk_threshold_pct']}%"}
rate_cols = ["sens_computable", "ci_low", "ci_high", "sens_all"]

det_rows = []
for c, d in data.items():
    pool = cohorts.positive_pool(d)
    for how in cohorts.POSITIVE_REFERENCES:
        ref = cohorts.positive_reference_dates(d, pool, how)
        s = phenotype.core_snapshot(d, ref, lookback_days=None, p=P).join(pool[["status"]])
        s = s.join(qd.score(s, years=h, p=P)[["qd_computable", "qd_variant", qd_col]])
        s = s.join(lrs.score(s, p=P)[["lrs_computable", "lrs_score"]])
        variant_text = {"lrs": LRS_LABEL,
                        "qdiabetes": f"QDiabetes-2018 A ({s['qd_variant'].iloc[0]})" if len(s) else "QDiabetes-2018 A"}
        flags = {"lrs": None if LRS_THR is None else (s["lrs_score"] >= LRS_THR).astype("boolean")
                        .mask(~s["lrs_computable"].astype(bool)),
                 "qdiabetes": None if qd_thr is None else (s[qd_col] >= qd_thr).astype("boolean")
                              .mask(~s["qd_computable"].astype(bool))}
        groups = [("all", s.index)] + [(g, s.index[s["status"] == g]) for g in ("T2DM", "Prediabetes")]
        for grp, idx in groups:
            for score_name, f in flags.items():
                row = {"cohort": c, "reference": how, "group": grp, "score": score_name,
                       "variant": variant_text[score_name], "threshold": thr_text[score_name]}
                if f is None:
                    comp_col = "qd_computable" if score_name == "qdiabetes" else "lrs_computable"
                    row.update({"n": len(idx), "n_computable": int(s.loc[idx, comp_col].sum())})
                else:
                    r = metrics.detection_rate(f.reindex(idx))
                    row.update({k: round(100 * v, 1) if k in rate_cols else v for k, v in r.items()})
                det_rows.append(row)
    run.log(f"{c} detection rate", references=list(cohorts.POSITIVE_REFERENCES))
detection = pd.DataFrame(det_rows, columns=["cohort", "reference", "group", "score", "variant", "threshold", "n",
                                            "n_computable", "n_flagged", *rate_cols])
detection["n_flagged"] = detection["n_flagged"].astype("Int64")   # "Pending" (eşiksiz) satırlarda NA
det_out =sdc.suppress_rates(detection, "n_flagged", ["n_computable", "n"], rate_cols)
det_out = sdc.suppress_small_counts(det_out, ["n", "n_computable", "n_flagged"])
run.save_table(det_out, "nb01/c1_detection_rate.csv",
               f"Bilinen pozitiflerde yakalama oranı (duyarlılık) — {LRS_LABEL} / QDiabetes, iki referans tarihi")
print(detection.to_string(index=False))

# %% [markdown]
# ## 5. Etnik grup eşlemesi kontrolü (uyruk / etnisite → grup → QDiabetes)
# Kaynak: `PARAMS["ethnicity_source"]`. "Other (unmapped nationality)" satırları eşleme tablosuna
# (codelists.NATIONALITY_COUNTRIES) eklenecek adaylardır [karar bekliyor — D6].

# %%
src_name = P["ethnicity_source"]
eth_map = pd.concat({c: s.groupby([s["ethnicity_source_value"].fillna("<missing>"),
                                   s["ethnicity"].fillna("<missing>"), "ethn_qd"]).size()
                     for c, s in snaps.items()}, axis=1).fillna(0).astype(int).reset_index()
eth_map.columns = [f"{src_name}_raw", "ethnic_group", "qdiabetes_category", *snaps]
run.save_table(sdc.suppress_small_counts(eth_map, list(snaps)), "nb01/ethnicity_mapping.csv",
               f"{src_name} → etnik grup → QDiabetes eşlemesi [karar bekliyor]")
print(eth_map.to_string(index=False))

# %%
kpi_values = {
    "c1_achievable_note": "C1 achievable N NABIDH raporundan (build_report / teslim notu)",
    "joint_core8_pct": {r["cohort"]: r["joint_core8_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "joint_lrs_pct": {r["cohort"]: r["joint_lrs_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "qd_computable_pct": {r["cohort"]: r["qd_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "lrs_computable_pct": {r["cohort"]: r["lrs_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "lrs_variant": P["lrs_variant"], "lrs_label": LRS_LABEL, "lrs_threshold": LRS_THR,
    "selection_effect_max_abs_smd": float(sel["smd"].abs().max()),
    "selection_effect_imbalanced_vars": sel.loc[sel["imbalance"], "variable"].tolist(),
    # C1 birincil amaç: yakalama oranı (% skoru hesaplanabilenlerde); None = eşik yok / hesaplanamadı
    "c1_detection_pct": {f"{r['reference']}|{r['score']}": None if pd.isna(r["sens_computable"])
                         else float(r["sens_computable"])
                         for _, r in detection[(detection["cohort"] == "c1") & (detection["group"] == "all")].iterrows()},
}
run.save_json(kpi_values, "nb01/kpi_values.json", "NB1 KPI girdileri")
manifest = run.finish()
print("Run:", run.run_id)
