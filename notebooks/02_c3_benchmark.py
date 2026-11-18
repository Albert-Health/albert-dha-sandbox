# ---
# jupyter:
#   jupytext:
#     formats: py:percent
# ---

# %% [markdown]
# # NB2 — C3 benchmark (incident T2D)
#
# **Kapsam:** Adım 3 — non-diabetic kohortta QDiabetes-2018 A ve LRS'in incident diyabeti
# tahmin performansı. Üç kol: **Kol 1** QDiabetes olduğu gibi, **Kol 2a** baseline recalibration,
# **Kol 2b** baseline + eğim recalibration (Kol 3 = UAE modeli, NB3, koşullu). Recalibration,
# QDiabetes'in ayrı kadın/erkek denklemleri nedeniyle cinsiyete göre katmanlıdır.
#
# - Horizon: `PARAMS["horizon_years"]` (birincil) ve `horizon_years_fallback` (yedek); idari sansür.
# - Washout: `PARAMS["outcome_washout_days"]` [karar bekliyor].
# - Metrikler: Harrell C, zaman-bağımlı AUROC(h) (IPCW), KM-tabanlı O:E ve kalibrasyon, kalibrasyon
#   eğimi, eşik metrikleri (IPCW), bootstrap %95 CI.
# - Recalibration parametreleri eğitim parçasında (temporal split) kestirilir, tüm kollar test
#   parçasında karşılaştırılır.
#
# > **Leicester notu:** Varyant `PARAMS["lrs_variant"]` — varsayılan LPRS (Gray 2012, bel çevresi
# > yok; [KARAR: 2026-11-14, ensargunesdogdu + Zeynep Pelin Polat — K-LRS]), LRA 2010 duyarlılık için.
# > İkisi de mevcut (tanı konmamış) IGR/T2D tespiti için geliştirilmiş kesitsel skorlardır. Burada
# > incident diyabet için değerlendirilmesi *dış kullanım (off-label)* olarak raporlanır; mutlak risk
# > vermedikleri için (LPRS sabit terimsiz doğrusal öngörücü, LRA puan) O:E/kalibrasyon hesaplanmaz.
# > LPRS eşiği seçilmediyse (D23) eşik metrikleri "Pending".
# >
# > **QDiabetes notu:** Kaynak kod yalnızca 10 yıllık baseline survival içerir; Kol 1'de diğer
# > horizon'lar `S0(t)=S0(10)^(t/10)` varsayımıyla türetilir [karar bekliyor]. Kol 2 bu varsayıma bağlı değildir.

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

from sandbox import cohorts, metrics, recalibration, sdc
from sandbox.audit import Run
from sandbox.config import CANONICAL_DIR, PARAMS
from sandbox.io import schema
from sandbox.scores import lrs, qdiabetes2018a as qd

SOURCE = os.environ.get("SANDBOX_SOURCE", "synthetic")   # enclave'de: "nabidh" (Jupyter: %env SANDBOX_SOURCE=nabidh)
P = dict(PARAMS)
# Duyarlılık çalıştırmaları için: SANDBOX_PARAMS='{"outcome_washout_days": 90}' (audit'e yazılır)
P.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))
REPS = int(os.environ.get("SANDBOX_BOOTSTRAP_REPS", P["bootstrap_reps"]))
run = Run("nb02_c3_benchmark", params=P, source=SOURCE)
schema.require_cohorts(CANONICAL_DIR, SOURCE, ("c3",))
run.add_inputs([CANONICAL_DIR / SOURCE / "c3"])
ds = schema.read_dataset(CANONICAL_DIR, SOURCE, "c3")
built = cohorts.build_c3(ds, P)
c3, funnel = built["cohort"], built["funnel"]
run.save_json(funnel, "nb02/c3_funnel.json", "C3 kohort akışı")
run.log("C3 built", **funnel)

q = qd.score(c3, years=10, p=P)
l = lrs.score(c3, p=P)
df = c3.join(q[["qd_lp", "qd_computable", "qd_missing", "qd_variant", "ethn_qd"]]).join(
    l[["lrs_score", "lrs_computable", "lrs_missing"]])
LRS_ARM = f"{lrs.label(P)} (off-label)"
df["T"] = df["followup_years"]
df["E"] = df["incident_diabetes"].astype(bool)
df["age_band"] = pd.cut(df["age"], P["age_band_edges"], right=False, labels=P["age_band_labels"])

coverage = pd.DataFrame([{
    "c3_n": len(df), "events": int(df["E"].sum()),
    "qd_computable_n": int(df["qd_computable"].sum()), "qd_computable_pct": round(100 * df["qd_computable"].mean(), 1),
    "lrs_computable_n": int(df["lrs_computable"].sum()), "lrs_computable_pct": round(100 * df["lrs_computable"].mean(), 1),
    "joint_core8_pct": round(100 * df["ok_core8"].mean(), 1), "joint_lrs_pct": round(100 * df["ok_lrs"].mean(), 1),
    "qd_variant": df["qd_variant"].iloc[0] if len(df) else None,
    "lrs_variant": lrs.label(P),
    "washout_days": P["outcome_washout_days"],
}])
run.save_table(coverage, "nb02/coverage.csv", "Skor kapsama ve birlikte tamlık (C3)")
print(coverage.T)

# %% [markdown]
# ## 1. Eğitim / test ayrımı (recalibration için)

# %%
qd_set = df[df["qd_computable"]].copy()
if P["recal_split"] == "temporal":
    cut = qd_set["index_date"].quantile(P["recal_train_frac"])
    qd_set["split"] = np.where(qd_set["index_date"] <= cut, "train", "test")
else:
    rng = np.random.default_rng(P["seed"])
    qd_set["split"] = np.where(rng.random(len(qd_set)) < P["recal_train_frac"], "train", "test")
split_tbl = qd_set.groupby("split").agg(n=("E", "size"), events=("E", "sum"),
                                        index_min=("index_date", "min"), index_max=("index_date", "max")).reset_index()
run.save_table(split_tbl, "nb02/recal_split.csv", "Recalibration eğitim/test ayrımı")
print(split_tbl)

# %% [markdown]
# ## 2. Kol 1 / 2a / 2b ve Leicester skoru — horizon bazında metrikler

# %%
def evaluate(d: pd.DataFrame, p_h: np.ndarray, h: float, label: str, threshold=None, absolute=True,
             with_ci=True) -> dict:
    t, e = d["T"].to_numpy(), d["E"].to_numpy()
    tt, ee = metrics.truncate(t, e, h)
    out = {"arm": label, "horizon": h, "n": len(d), "events_by_h": int(ee.sum()),
           "c_index": metrics.c_index(tt, ee, p_h),
           "auroc_h": metrics.time_dependent_auc(t, e, p_h, h)}
    if with_ci and REPS > 0 and ee.sum() > 0:
        n = len(d)
        out["c_index_ci"] = metrics.bootstrap_ci(lambda i: metrics.c_index(tt[i], ee[i], p_h[i]), n, REPS, P["seed"])
        out["auroc_h_ci"] = metrics.bootstrap_ci(lambda i: metrics.time_dependent_auc(t[i], e[i], p_h[i], h), n, REPS, P["seed"])
    if absolute:
        out.update(metrics.observed_expected(t, e, p_h, h))
        out["calibration_slope"] = metrics.calibration_slope(t, e, p_h, h)
    if threshold is not None:
        out.update({f"thr_{k}": v for k, v in metrics.threshold_metrics(t, e, p_h, threshold, h).items()})
    else:
        out["thr_status"] = "Pending — threshold not pre-specified"
    return out


results, cal_tables, recal_models = [], {}, []
train, test = qd_set[qd_set["split"] == "train"], qd_set[qd_set["split"] == "test"]
lrs_set = df[df["lrs_computable"]]
qd_thr = None if P["qd_risk_threshold_pct"] is None else P["qd_risk_threshold_pct"] / 100

for h in [P["horizon_years"], P["horizon_years_fallback"]]:
    primary = h == P["horizon_years"]
    p1_test = qd.risk(test["qd_lp"], test["sex"], h, P).to_numpy()
    results.append(evaluate(test, p1_test, h, "Kol 1 — QDiabetes (published)", qd_thr, with_ci=primary))
    p1_all = qd.risk(qd_set["qd_lp"], qd_set["sex"], h, P).to_numpy()
    results.append(evaluate(qd_set, p1_all, h, "Kol 1 — QDiabetes (published), all", qd_thr, with_ci=False))
    for method, name in [("baseline", "Kol 2a — baseline recal"), ("baseline_slope", "Kol 2b — baseline+slope recal")]:
        m = recalibration.fit_stratified(train["T"], train["E"], train["qd_lp"], train["sex"], h, method)
        recal_models.append({"arm": name, "by_sex": m})
        p2 = recalibration.predict_stratified(m, test["qd_lp"], test["sex"])
        results.append(evaluate(test, p2, h, name, qd_thr, with_ci=primary))
        cal_tables[(h, name)] = metrics.calibration_table(test["T"], test["E"], p2, h)
    cal_tables[(h, "Kol 1 — QDiabetes (published)")] = metrics.calibration_table(test["T"], test["E"], p1_test, h)
    if len(lrs_set):
        results.append(evaluate(lrs_set, lrs_set["lrs_score"].to_numpy(dtype=float), h, LRS_ARM,
                                lrs.threshold(P), absolute=False, with_ci=primary))

res = pd.DataFrame(results)
run.save_table(res, "nb02/performance.csv", f"Kol 1/2a/2b ve {lrs.label(P)} performansı (test parçası)")
run.save_json(recal_models, "nb02/recalibration_models.json", "Recalibration parametreleri (eğitim parçası)")
show = ["arm", "horizon", "n", "events_by_h", "c_index", "c_index_ci", "auroc_h", "oe_ratio", "calibration_slope"]
print(res[[c for c in show if c in res]].to_string(index=False))

# %% [markdown]
# ## 3. Kalibrasyon grafiği (test parçası, birincil horizon)

# %%
h = P["horizon_years"]
fig, ax = plt.subplots(figsize=(6.5, 6))
mx = 0.0
for (hh, name), tbl in cal_tables.items():
    if hh != h:
        continue
    ax.plot(tbl["mean_predicted"] * 100, tbl["observed_km"] * 100, "o-", label=name)
    mx = max(mx, tbl["mean_predicted"].max() * 100, tbl["observed_km"].max() * 100)
ax.plot([0, mx * 1.05], [0, mx * 1.05], "--", color="gray", label="İdeal")
ax.set_xlabel(f"Ortalama tahmin, {h} yıl (%)")
ax.set_ylabel(f"Gözlenen (KM), {h} yıl (%)")
ax.set_title("Kalibrasyon — risk ondalıkları")
ax.legend(fontsize=8)
run.save_figure(fig, "nb02/calibration_plot.png", "Kalibrasyon grafiği (birincil horizon)")
cal_all = pd.concat([t.assign(horizon=k[0], arm=k[1]) for k, t in cal_tables.items()], ignore_index=True)
run.save_table(sdc.suppress_small_counts(cal_all, ["n", "events_by_h"]), "nb02/calibration_tables.csv",
               "Kalibrasyon tabloları")

# %% [markdown]
# ## 4. Alt-grup analizi (fairness / gap) — tüm QDiabetes-hesaplanabilir kohort, birincil horizon
# Kol 2a parametreleri eğitim parçasından. < `min_events_subgroup` olay → "insufficient events".

# %%
m2a = recalibration.fit_stratified(train["T"], train["E"], train["qd_lp"], train["sex"], h, "baseline")
qd_set["p1"] = qd.risk(qd_set["qd_lp"], qd_set["sex"], h, P).to_numpy()
qd_set["p2a"] = recalibration.predict_stratified(m2a, qd_set["qd_lp"], qd_set["sex"])
sub_rows = []
for gtype, col in [("Sex", "sex"), ("Age band", "age_band"), (f"Ethnic group ({P['ethnicity_source']})", "ethnicity"),
                   ("QDiabetes ethnicity", "ethn_qd")]:
    for g, d in qd_set.groupby(col, observed=True, dropna=False):
        t, e = d["T"].to_numpy(), d["E"].to_numpy()
        tt, ee = metrics.truncate(t, e, h)
        row = {"group_type": gtype, "group": "<missing>" if pd.isna(g) else str(g), "n": len(d),
               "events_by_h": int(ee.sum())}
        if ee.sum() < P["min_events_subgroup"]:
            row["note"] = "insufficient events"
        else:
            row["c_index"] = metrics.c_index(tt, ee, d["p1"].to_numpy())
            row["oe_kol1"] = metrics.observed_expected(t, e, d["p1"], h)["oe_ratio"]
            row["oe_kol2a"] = metrics.observed_expected(t, e, d["p2a"], h)["oe_ratio"]
            row["mean_pred_kol1"] = d["p1"].mean()
            row["observed_km"] = metrics.km_risk(t, e, h)
        sub_rows.append(row)
sub = pd.DataFrame(sub_rows).reindex(columns=["group_type", "group", "n", "events_by_h", "note", "c_index",
                                              "oe_kol1", "oe_kol2a", "mean_pred_kol1", "observed_km"])
overall_c = metrics.c_index(*metrics.truncate(qd_set["T"], qd_set["E"], h), qd_set["p1"].to_numpy())
sub["delta_c"] = sub["c_index"] - overall_c
run.save_table(sdc.suppress_small_counts(sub, ["n", "events_by_h"]), "nb02/subgroups.csv",
               "Alt-grup C-index ve O:E (Kol 1 / Kol 2a)")
print(sub.to_string(index=False))

fig, ax = plt.subplots(figsize=(8, max(3, 0.3 * len(sub))))
s2 = sub.dropna(subset=["oe_kol2a"])
ax.barh(s2["group_type"] + ": " + s2["group"], s2["oe_kol2a"], color="#4C72B0")
ax.axvline(1, color="k", lw=0.8)
ax.set_title(f"O:E Kol 2a (recalibrated), {h} yıl — alt gruplar")
run.save_figure(fig, "nb02/subgroup_oe.png", "Alt-grup O:E")

# %% [markdown]
# ## 5. KPI girdileri

# %%
def first(arm, horizon):
    r = res[(res["arm"] == arm) & (res["horizon"] == horizon)]
    return r.iloc[0].to_dict() if len(r) else {}


k1 = first("Kol 1 — QDiabetes (published)", h)
k2 = first("Kol 2a — baseline recal", h)
kl = first(LRS_ARM, h)
kpi_values = {
    "horizon_years": h,
    "c3_eligible_n": len(df),
    "joint_completeness_qdiabetes_pct": float(coverage["joint_core8_pct"].iloc[0]),
    "joint_completeness_qdiabetes_n": int(df["ok_core8"].sum()),
    "joint_completeness_lrs_pct": float(coverage["joint_lrs_pct"].iloc[0]),
    "joint_completeness_lrs_n": int(df["ok_lrs"].sum()),
    "qd_variant": coverage["qd_variant"].iloc[0],
    "auroc_qd": k1.get("auroc_h"), "auroc_qd_ci": k1.get("auroc_h_ci"),
    "c_index_qd": k1.get("c_index"), "c_index_qd_ci": k1.get("c_index_ci"),
    "oe_qd_kol1": k1.get("oe_ratio"), "cal_slope_qd_kol1": k1.get("calibration_slope"),
    "oe_qd_kol2a": k2.get("oe_ratio"), "cal_slope_qd_kol2a": k2.get("calibration_slope"),
    "qd_threshold": {k[4:]: v for k, v in k1.items() if k.startswith("thr_") and v == v},
    "lrs_variant": P["lrs_variant"], "lrs_label": lrs.label(P),
    "auroc_lrs": kl.get("auroc_h"), "c_index_lrs": kl.get("c_index"),
    "lrs_threshold": {k[4:]: v for k, v in kl.items() if k.startswith("thr_") and v == v},
    "subgroups_insufficient_events": int((sub["note"] == "insufficient events").sum()),
}
run.save_json(kpi_values, "nb02/kpi_values.json", "NB2 KPI girdileri")
print(pd.Series(kpi_values).to_string())
manifest = run.finish()
print("Run:", run.run_id)
