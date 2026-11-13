# ---
# jupyter:
#   jupytext:
#     formats: py:percent
# ---

# %% [markdown]
# # NB0 — Veri profili (C1 / C2 / C3)
#
# **Amaç:** DHA enclave'de verilen verinin içinde gerçekten ne var, ne yok — analizden önce.
#
# - Şema doğrulama (kanonik format)
# - Tablo hacimleri, tarih aralıkları, tesis temsili
# - İstenen kodlar vs gelen kodlar (KPI: *Applicant Data Requirement Framework Match*)
# - 8 çekirdek değişkenin tekil ve birlikte tamlığı (KPI: *Data Completeness ≥ %90*)
# - Lab dağılımları, zaman çizgisi
#
# Çalıştırma: `python notebooks/00_data_profile.py` veya Jupyter/VS Code'da hücre hücre.
# Tüm çıktılar `outputs/<run_id>/nb00/` altına yazılır ve audit log'a kaydedilir.

# %%
import os
import sys
from pathlib import Path

ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "src" / "sandbox").exists())
sys.path.insert(0, str(ROOT / "src"))

import matplotlib

if "ipykernel" not in sys.modules:   # script olarak çalışırken ekran gerekmez
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from sandbox import codelists, cohorts, phenotype, sdc
from sandbox.audit import Run
from sandbox.config import CANONICAL_DIR, COHORTS, PARAMS
from sandbox.io import schema

SOURCE = os.environ.get("SANDBOX_SOURCE", "synthetic")   # enclave'de: "nabidh"
pd.set_option("display.width", 160)

run = Run("nb00_data_profile")
run.add_inputs([CANONICAL_DIR / SOURCE / c for c in COHORTS if (CANONICAL_DIR / SOURCE / c).exists()])
data = {c: schema.read_dataset(CANONICAL_DIR, SOURCE, c) for c in COHORTS
        if (CANONICAL_DIR / SOURCE / c).exists()}
run.log("datasets loaded", source=SOURCE, cohorts=list(data))
print({c: d.n_patients for c, d in data.items()})

# %% [markdown]
# ## 1. Şema doğrulama

# %%
val = pd.concat([schema.validate(d).assign(cohort=c) for c, d in data.items()], ignore_index=True)
issues = val[val["severity"] != "INFO"]
run.save_table(val, "nb00/schema_validation.csv", "Şema ve veri kalitesi kontrolleri")
print(issues if len(issues) else "Uyarı/hata yok")
assert not (val["severity"] == "ERROR").any(), "Şema hatası var — adapter'ı düzeltmeden devam etme"

# %% [markdown]
# ## 2. Hacim, tarih aralığı, tesis temsili

# %%
rows = []
for c, d in data.items():
    for t, df in d.tables.items():
        rows.append({"cohort": c, "table": t, "rows": len(df), "patients": df["patient_id"].nunique(),
                     "date_min": df["date"].min() if "date" in df else None,
                     "date_max": df["date"].max() if "date" in df else None})
volume = pd.DataFrame(rows)
run.save_table(volume, "nb00/volume.csv", "Tablo hacimleri ve tarih aralıkları")
print(volume.to_string(index=False))

fac = []
for c, d in data.items():
    vc = d["patients"]["facility_id"].value_counts(dropna=False)
    fac.append({"cohort": c, "n_facilities": int(d["patients"]["facility_id"].nunique()),
                "top_facility_share_pct": round(100 * vc.iloc[0] / vc.sum(), 1) if len(vc) else None,
                "facility_missing_pct": round(100 * d["patients"]["facility_id"].isna().mean(), 1)})
fac = pd.DataFrame(fac)
run.save_table(fac, "nb00/facility_representation.csv", "Tesis temsili")
print(fac.to_string(index=False))

# %% [markdown]
# ## 3. Demografi

# %%
demo = []
for c, d in data.items():
    end = cohorts.data_end_date(d)
    p = d["patients"]
    age = (end - p["date_of_birth"]).dt.days / 365.25
    demo.append({"cohort": c, "n": len(p), "age_median": round(age.median(), 1),
                 "age_iqr": f"{age.quantile(.25):.0f}–{age.quantile(.75):.0f}",
                 "age_25_84_pct": round(100 * age.between(25, 84.999).mean(), 1),
                 "male_pct": round(100 * (p["sex"] == "Male").mean(), 1)})
demo = pd.DataFrame(demo)
run.save_table(demo, "nb00/demographics.csv", "Demografi özeti")
print(demo.to_string(index=False))

eth = pd.concat({c: d["patients"]["ethnicity_raw"].fillna("<missing>").value_counts()
                 for c, d in data.items()}, axis=1).fillna(0).astype(int)
eth_out = sdc.suppress_small_counts(eth.reset_index().rename(columns={"index": "ethnicity_raw"}), list(data))
run.save_table(eth_out, "nb00/ethnicity_categories.csv", "Etnisite kategorileri (küçük hücre bastırılmış)")
print(eth_out.to_string(index=False))

fig, axes = plt.subplots(1, len(data), figsize=(5 * len(data), 4), squeeze=False)
for ax, (c, d) in zip(axes[0], data.items()):
    end = cohorts.data_end_date(d)
    ((end - d["patients"]["date_of_birth"]).dt.days / 365.25).plot.hist(bins=30, ax=ax, color="#4C72B0")
    ax.set_title(f"{c.upper()} — yaş (veri sonu)")
fig.tight_layout()
run.save_figure(fig, "nb00/age_hist.png", "Yaş dağılımı")

# %% [markdown]
# ## 4. İstenen kodlar vs gelen kodlar (Framework Match)

# %%
req = codelists.requested_codes_table()
match_rows = []
for c, d in data.items():
    cond, meds = d["conditions"], d["medications"]
    for grp in codelists.DX:
        n = cond.loc[codelists.match_dx(cond, grp), "patient_id"].nunique()
        match_rows.append({"cohort": c, "domain": "diagnosis", "group": grp, "patients_with_any": n,
                           "pct_patients": round(100 * n / d.n_patients, 1)})
    for grp in codelists.ATC:
        n = meds.loc[codelists.match_atc(meds, grp), "patient_id"].nunique()
        match_rows.append({"cohort": c, "domain": "medication", "group": grp, "patients_with_any": n,
                           "pct_patients": round(100 * n / d.n_patients, 1)})
    labs = d["labs"]
    for code, name in codelists.LOINC_LAB.items():
        n = labs.loc[labs["loinc"] == code, "patient_id"].nunique()
        match_rows.append({"cohort": c, "domain": "lab", "group": f"{name} ({code})", "patients_with_any": n,
                           "pct_patients": round(100 * n / d.n_patients, 1)})
    obs = d["observations"]
    for concept in sorted(set(codelists.OBS_CODE_TO_CONCEPT.values()) | {"smoking_status"}):
        n = obs.loc[obs["concept"] == concept, "patient_id"].nunique()
        match_rows.append({"cohort": c, "domain": "observation", "group": concept, "patients_with_any": n,
                           "pct_patients": round(100 * n / d.n_patients, 1)})
fm = pd.DataFrame(match_rows)
fm["received"] = fm["patients_with_any"] > 0
run.save_table(sdc.suppress_small_counts(fm, ["patients_with_any"]), "nb00/framework_match.csv",
               "İstenen kod grupları — gelen veride hasta sayısı")
print(fm.pivot_table(index=["domain", "group"], columns="cohort", values="pct_patients").to_string())

# Gelen ama istenmeyen / eşlenemeyen kodlar
unmapped = []
for c, d in data.items():
    o = d["observations"]
    um = o.loc[o["concept"].astype("string").str.startswith("unmapped:").fillna(False), "concept"].value_counts()
    for k, v in um.items():
        unmapped.append({"cohort": c, "item": k, "rows": int(v)})
    labs_unknown = d["labs"].loc[~d["labs"]["loinc"].isin(codelists.LOINC_LAB), "loinc"].value_counts()
    for k, v in labs_unknown.items():
        unmapped.append({"cohort": c, "item": f"lab LOINC {k}", "rows": int(v)})
unmapped = pd.DataFrame(unmapped, columns=["cohort", "item", "rows"])
run.save_table(unmapped, "nb00/unmapped_codes.csv", "Kod listesinde olmayan gelen kodlar")
print(unmapped if len(unmapped) else "Eşlenemeyen kod yok")

# %% [markdown]
# ## 5. 8 çekirdek değişkenin tamlığı
#
# C1/C2: veri sonu itibarıyla tüm geçmiş ("as currently recorded").
# C3: index tarihinde, prediktör lookback = `PARAMS["predictor_lookback_days"]`.

# %%
comp_rows, joint_rows, snaps = [], [], {}
ok_cols = [f"ok_{v}" for v in codelists.CORE_VARIABLES]
for c, d in data.items():
    if c == "c3":
        snap = cohorts.build_c3(d)["cohort"]
        snap["group"] = "non-diabetic"
    else:
        pool = cohorts.positive_pool(d)
        ref = pd.Series(cohorts.data_end_date(d), index=pool.index)
        snap = phenotype.core_snapshot(d, ref, lookback_days=None).join(pool["status"].rename("group"))
    snaps[c] = snap
    for grp, s in [("all", snap), *snap.groupby("group")]:
        for col in ok_cols + ["waist_cm"]:
            ok = s[col].notna() if col == "waist_cm" else s[col].astype(bool)
            comp_rows.append({"cohort": c, "group": grp, "variable": col.replace("ok_", ""),
                              "n": len(s), "complete_pct": round(100 * ok.mean(), 1)})
        joint_rows.append({"cohort": c, "group": grp, "n": len(s),
                           "joint_core8_n": int(s["ok_core8"].sum()),
                           "joint_core8_pct": round(100 * s["ok_core8"].mean(), 1),
                           "joint_lrs_n": int(s["ok_lrs"].sum()),
                           "joint_lrs_pct": round(100 * s["ok_lrs"].mean(), 1)})
comp = pd.DataFrame(comp_rows)
joint = pd.DataFrame(joint_rows)
run.save_table(comp, "nb00/core_variable_completeness.csv", "Değişken bazında tamlık")
run.save_table(sdc.suppress_small_counts(joint, ["joint_core8_n", "joint_lrs_n"]),
               "nb00/joint_completeness.csv", "Birlikte tamlık (8 çekirdek, LRS)")
print(comp[comp["group"] == "all"].pivot(index="variable", columns="cohort", values="complete_pct").to_string())
print(joint.to_string(index=False))

bmi_src = pd.concat({c: s["bmi_source"].fillna("missing").value_counts(normalize=True).round(3) * 100
                     for c, s in snaps.items()}, axis=1)
smk_src = pd.concat({c: s["smoking_source"].fillna("missing").value_counts(normalize=True).round(3) * 100
                     for c, s in snaps.items()}, axis=1)
run.save_table(bmi_src.reset_index(names="bmi_source"), "nb00/bmi_source.csv", "BMI kaynağı (%)")
run.save_table(smk_src.reset_index(names="smoking_source"), "nb00/smoking_source.csv", "Sigara kaynağı (%)")
print(bmi_src, "\n", smk_src)

# %% [markdown]
# ## 6. Lab dağılımları ve zaman çizgisi

# %%
fig, axes = plt.subplots(len(data), 2, figsize=(11, 3.2 * len(data)), squeeze=False)
for i, (c, d) in enumerate(data.items()):
    g = phenotype.glycaemic_events(d)
    for j, (kind, lines) in enumerate([("hba1c", [5.7, 6.5]), ("fpg", [100, 126])]):
        v = g.loc[g["kind"] == kind, "value"]
        ax = axes[i][j]
        if len(v):
            v.clip(upper=v.quantile(.995)).plot.hist(bins=40, ax=ax, color="#C44E52")
        for x in lines:
            ax.axvline(x, ls="--", color="k", lw=.8)
        ax.set_title(f"{c.upper()} — {kind} (n={len(v):,})")
fig.tight_layout()
run.save_figure(fig, "nb00/lab_distributions.png", "HbA1c / FPG dağılımları")

fig, ax = plt.subplots(figsize=(11, 3.5))
for c, d in data.items():
    s = pd.concat([d[t]["date"] for t in ("conditions", "labs", "observations", "medications")])
    s.dt.to_period("M").value_counts().sort_index().plot(ax=ax, label=c.upper())
ax.set_title("Aylık kayıt sayısı")
ax.legend()
run.save_figure(fig, "nb00/timeline.png", "Aylık kayıt hacmi")

# %% [markdown]
# ## 7. C3 takip yapısı (incident tasarımın fizibilitesi)

# %%
if "c3" in snaps:
    s = snaps["c3"]
    c3_sum = pd.DataFrame([{
        "n": len(s),
        "incident_t2d": int(s["incident_diabetes"].sum()),
        "incident_t2d_incl_med": int(s["incident_diabetes_incl_med"].sum()),
        "incident_prediabetes": int(s["incident_prediabetes"].sum()),
        "followup_years_median": round(s["followup_years"].median(), 2),
        "followup_ge_horizon_pct": round(100 * (s["followup_years"] >= PARAMS["horizon_years"]).mean(), 1),
        "followup_ge_fallback_pct": round(100 * (s["followup_years"] >= PARAMS["horizon_years_fallback"]).mean(), 1),
        "n_followup_glycaemic_median": float(s["n_followup_glycaemic"].median()),
    }])
    run.save_table(c3_sum, "nb00/c3_followup_summary.csv", "C3 takip ve olay özeti")
    print(c3_sum.T)
    ev = s.loc[s["incident_diabetes"], "incident_evidence"].value_counts()
    run.save_table(ev.reset_index(), "nb00/c3_incident_evidence.csv", "İlk olay kanıt tipi")
    # Olay index'e ne kadar yakın? (çok yakın olay = muhtemelen başlangıçta tanı konmamış diyabet)
    dte = (s["incident_date"] - s["index_date"]).dt.days.dropna()
    bins = pd.cut(dte, [0, 30, 90, 180, 365, 730, 100000],
                  labels=["≤30g", "31–90g", "91–180g", "181–365g", "1–2y", ">2y"]).value_counts().sort_index()
    run.save_table(bins.rename_axis("days_to_event").reset_index(name="events"), "nb00/c3_days_to_event.csv",
                   "İlk olaya kadar geçen gün dağılımı")
    print(bins)
    sens = []
    for w in (0, 90, 180):
        r = cohorts.build_c3(data["c3"], dict(PARAMS, outcome_washout_days=w))
        sens.append({"washout_days": w, "n": r["funnel"]["c3_final"] if w == 0 else r["funnel"]["after_outcome_washout"],
                     "events": int(r["cohort"]["incident_diabetes"].sum()),
                     "followup_years_median": round(r["cohort"]["followup_years"].median(), 2)})
    sens = pd.DataFrame(sens)
    run.save_table(sens, "nb00/c3_washout_sensitivity.csv", "Outcome washout duyarlılığı")
    print(sens.to_string(index=False))

    fig, ax = plt.subplots(figsize=(7, 3.5))
    s["followup_years"].plot.hist(bins=30, ax=ax, color="#55A868")
    ax.axvline(PARAMS["horizon_years"], ls="--", color="k")
    ax.set_title("C3 takip süresi (yıl)")
    run.save_figure(fig, "nb00/c3_followup_hist.png", "C3 takip süresi")

# %% [markdown]
# ## 8. KPI ön okuması

# %%
kpi = []
allc = comp[comp["group"] == "all"]
for c in data:
    sub = allc[(allc["cohort"] == c) & (allc["variable"].isin(codelists.CORE_VARIABLES))]
    kpi.append({"kpi": "Data Completeness for Required Variables (min over 8 core)", "cohort": c,
                "target": ">= 90%", "actual": f"{sub['complete_pct'].min():.1f}%",
                "met": bool(sub["complete_pct"].min() >= 90),
                "weakest_variable": sub.sort_values("complete_pct").iloc[0]["variable"]})
not_received = fm[(~fm["received"]) & fm["group"].isin(
    ["t2d", "prediabetes", "hypertension", "cvd", "family_history_dm", "antihypertensive",
     "antidiabetic", "hba1c (4548-4)", "fpg (1558-6)", "bmi", "height_cm", "weight_kg", "waist_cm", "smoking_status"])]
kpi.append({"kpi": "Applicant Data Requirement Framework Match", "cohort": "all", "target": "Match",
            "actual": "Match" if not_received.empty else f"{not_received['group'].nunique()} grup eksik",
            "met": not_received.empty,
            "weakest_variable": ", ".join(sorted(not_received["group"].unique())[:6])})
kpi = pd.DataFrame(kpi)
run.save_table(kpi, "nb00/kpi_preview.csv", "NB0'dan beslenen KPI'lar")
core_min = allc[allc["variable"].isin(codelists.CORE_VARIABLES)].groupby("cohort")["complete_pct"].min()
run.save_json({"data_completeness_min_core8_pct": core_min.to_dict(),
               "data_completeness_weakest": {c: r["weakest_variable"] for c, r in
                                             kpi[kpi["cohort"] != "all"].set_index("cohort").iterrows()},
               "framework_match": bool(not_received.empty),
               "framework_missing_groups": sorted(not_received["group"].unique().tolist()),
               "schema_errors": int((val["severity"] == "ERROR").sum()),
               "schema_warnings": int((val["severity"] == "WARN").sum())},
              "nb00/kpi_values.json", "NB0 KPI girdileri")
print(kpi.to_string(index=False))

# %%
manifest = run.finish()
print("Run:", run.run_id, "→", manifest)
