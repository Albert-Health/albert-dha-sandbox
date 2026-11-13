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
# > **Bu kohortlarda ayrım gücü (C-index, AUROC) ve kalibrasyon HESAPLANMAZ** — tüm hastalar
# > pozitif vakadır, negatif vaka yoktur. Skorlar yalnızca *hesaplanabilirlik* ve dağılım için
# > raporlanır.
#
# - 8 çekirdek değişkenin tekil ve birlikte tamlığı (T2DM vs prediyabet)
# - C1 (tam kayıt) vs C2 (rastgele) seçilim etkisi: standardize ortalama farkı (SMD)
# - QDiabetes-2018 A ve LRS hesaplanabilirlik oranı, eksiklik nedenleri, skor dağılımları
#
# Referans tarih: veri sonu ("as currently recorded"), tüm geçmiş.

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

from sandbox import codelists, cohorts, phenotype, sdc
from sandbox.audit import Run
from sandbox.config import CANONICAL_DIR, PARAMS
from sandbox.io import schema
from sandbox.scores import lrs, qdiabetes2018a as qd

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
    s = s.join(lrs.score(s, p=P)[["lrs_computable", "lrs_missing", "lrs_score", "lrs_category"]])
    snaps[c] = s
    excluded = d.n_patients - len(s)
    run.log(f"{c} snapshot", n=len(s), not_in_positive_pool=excluded)
print({c: len(s) for c, s in snaps.items()})

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
# LRS: bel çevresi zorunlu.

# %%
comp_rows, reasons = [], []
for c, s in snaps.items():
    for grp, g in [("all", s), *s.groupby("status")]:
        comp_rows.append({"cohort": c, "group": grp, "n": len(g),
                          "qd_computable_pct": round(100 * g["qd_computable"].mean(), 1),
                          "lrs_computable_pct": round(100 * g["lrs_computable"].mean(), 1),
                          "qd_variant": g["qd_variant"].iloc[0] if len(g) else None})
    for score_name, col in [("qdiabetes", "qd_missing"), ("lrs", "lrs_missing")]:
        r = s[col].str.split(";").explode()
        r = r[r != ""].value_counts()
        for k, v in r.items():
            reasons.append({"cohort": c, "score": score_name, "reason": k, "n": int(v),
                            "pct": round(100 * v / len(s), 1)})
computability = pd.DataFrame(comp_rows)
reasons = pd.DataFrame(reasons, columns=["cohort", "score", "reason", "n", "pct"])
run.save_table(computability, "nb01/score_computability.csv", "QDiabetes / LRS hesaplanabilirlik")
run.save_table(sdc.suppress_small_counts(reasons, ["n"]), "nb01/score_missing_reasons.csv", "Hesaplanamama nedenleri")
print(computability.to_string(index=False))
print(reasons.to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for c, s in snaps.items():
    (100 * s["qd_risk_10y"]).dropna().plot.hist(bins=40, ax=axes[0], alpha=0.5, density=True, label=c.upper())
    s["lrs_score"].dropna().plot.hist(bins=range(0, 49, 2), ax=axes[1], alpha=0.5, density=True, label=c.upper())
axes[0].set_title("QDiabetes-2018 A — 10 yıllık risk (%)")
axes[1].set_title("LRS puanı")
axes[1].axvline(P["lrs_high_risk_threshold"], ls="--", color="k")
for ax in axes:
    ax.legend()
fig.tight_layout()
run.save_figure(fig, "nb01/score_distributions.png", "Skor dağılımları (yalnızca betimleyici)")

dist = pd.concat([
    s.groupby("status").agg(qd_median_pct=("qd_risk_10y", lambda x: round(100 * x.median(), 2)),
                            lrs_median=("lrs_score", "median"),
                            lrs_high_risk_pct=("lrs_score", lambda x: round(100 * (x >= P["lrs_high_risk_threshold"]).sum() / max(x.notna().sum(), 1), 1)))
     .assign(cohort=c).reset_index() for c, s in snaps.items()])
run.save_table(dist, "nb01/score_summary.csv", "Skor özetleri (betimleyici)")
print(dist.to_string(index=False))

# %% [markdown]
# ## 4. Etnisite eşlemesi kontrolü (NABIDH → QDiabetes)

# %%
eth_map = pd.concat({c: s.groupby([s["ethnicity"].fillna("<missing>"), "ethn_qd"]).size() for c, s in snaps.items()},
                    axis=1).fillna(0).astype(int).reset_index()
eth_map.columns = ["ethnicity_raw", "qdiabetes_category", *snaps]
run.save_table(sdc.suppress_small_counts(eth_map, list(snaps)), "nb01/ethnicity_mapping.csv",
               "NABIDH → QDiabetes etnisite eşlemesi [karar bekliyor]")
print(eth_map.to_string(index=False))

# %%
kpi_values = {
    "c1_achievable_note": "C1 achievable N NABIDH raporundan (build_report / teslim notu)",
    "joint_core8_pct": {r["cohort"]: r["joint_core8_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "joint_lrs_pct": {r["cohort"]: r["joint_lrs_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "qd_computable_pct": {r["cohort"]: r["qd_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "lrs_computable_pct": {r["cohort"]: r["lrs_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "selection_effect_max_abs_smd": float(sel["smd"].abs().max()),
    "selection_effect_imbalanced_vars": sel.loc[sel["imbalance"], "variable"].tolist(),
}
run.save_json(kpi_values, "nb01/kpi_values.json", "NB1 KPI girdileri")
manifest = run.finish()
print("Run:", run.run_id)
