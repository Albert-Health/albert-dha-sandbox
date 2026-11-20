# ---
# jupyter:
#   jupytext:
#     formats: py:percent
# ---

# %% [markdown]
# # NB1 — C1 / C2 feasibility (cross-sectional)
#
# **Scope:** Step 1 — positive cohorts (T2DM + prediabetes). Data structure and completeness check.
#
# Study Flow steps 1 and 2. **C1's primary aim:** the share of patients known to have diabetes / prediabetes
# that QDiabetes and the Leicester score flag as "high risk" (sensitivity). **C2:** how well the variables are
# filled in NABIDH without a record-completeness requirement (completeness).
#
# > All patients are positive cases, there are no negative cases → only **sensitivity** is computed.
# > Specificity, PPV, discrimination (C-index, AUROC) and calibration are NOT computed here (C3 / NB2).
#
# - Single and joint completeness of the 8 core variables (T2DM vs prediabetes)
# - C1 (complete records) vs C2 (random) selection effect: standardised mean difference (SMD)
# - QDiabetes-2018 A and Leicester score computability, reasons for missingness, score distributions
#   Leicester variant `PARAMS["lrs_variant"]`: default LPRS (Gray 2012, no waist circumference)
#   [DECIDED: 2026-11-14, ensargunesdogdu + Zeynep Pelin Polat — K-LRS]; LRA 2010 for sensitivity.
# - C1 (and C2 for comparison) detection rate (sensitivity) — §4
#
# Reference date: for completeness and selection effect, the data end ("as currently recorded"), full history.
# Sensitivity is reported side by side for two references (data end / first evidence day) [DECISION PENDING — D22].

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
import pandas as pd

from sandbox import breakdowns, codelists, cohorts, metrics, phenotype, sdc
from sandbox.audit import Run
from sandbox.config import CANONICAL_DIR, PARAMS
from sandbox.io import schema
from sandbox.scores import lprs, lrs, qdiabetes2018a as qd

SOURCE = os.environ.get("SANDBOX_SOURCE", "synthetic")   # in the enclave: "nabidh" (Jupyter: %env SANDBOX_SOURCE=nabidh)
P = dict(PARAMS)
P.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))   # sensitivity runs (written to the audit)
run = Run("nb01_c1_c2_feasibility", params=P, source=SOURCE)
schema.require_cohorts(CANONICAL_DIR, SOURCE, ("c1", "c2"))
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
print("Leicester variant:", LRS_LABEL, "| high-risk threshold:", LRS_THR)

# %% [markdown]
# ## 1. Completeness — per variable and joint (T2DM vs prediabetes)
# `measure`: `recorded` = a value is in the record; `present_absent` (CVD, hypertension; family history unless
# `c1_require_fh_record`, D17) = no record means absent, so 100% by definition — not a fill rate (`meets_90` = "-").
# `family_history_recorded`: a FamilyHistory record or Z83.3 (the fill rate of family history).
# Joint: core-7 = the 8 core variables without ethnicity; core-8 = core-7 + ethnicity (by ethnicity source: §1b).

# %%
rows, joint = [], []
for c, s in snaps.items():
    for grp, g in [("all", s), *s.groupby("status")]:
        rows += [{"cohort": c, "group": grp, **r} for r in phenotype.completeness_by_variable(g, P)]
        joint.append({"cohort": c, "group": grp, **phenotype.joint_completeness(g)})
comp = pd.DataFrame(rows)
joint = pd.DataFrame(joint)
run.save_table(sdc.suppress_count_rate_pairs(comp, "n", [("complete_n", "complete_pct")]),
               "nb01/completeness_by_variable.csv",
               "C1/C2 variable completeness (T2DM / prediabetes); measure recorded / present_absent")
run.save_table(sdc.suppress_count_rate_pairs(joint, "n", [(f"joint_{k}_n", f"joint_{k}_pct")
                                                           for k in ("core7", "core8", "lrs")]),
               "nb01/joint_completeness.csv",
               "C1/C2 joint completeness: core-7 (without ethnicity), core-8 (core-7 + ethnicity), Leicester inputs")
print(comp.pivot_table(index="variable", columns=["cohort", "group"], values="complete_pct").to_string())
print(joint.to_string(index=False))

# %% [markdown]
# ## 1b. Ethnicity source (D6 pending): the default source next to the NABIDH ethnicity field
# Reporting only: sections 2–5 use PARAMS["ethnicity_source"]. QDiabetes needs no recorded ethnicity (missing →
# White / not stated, its reference group); the Leicester score does.

# %%
ETH_SOURCES = list(dict.fromkeys([P["ethnicity_source"], "nationality", "ethnicity"]))
# joint_core7 (without ethnicity) does not depend on the source; joint_core8 = core-7 + this source's ethnicity
ETH_COMPARE = [("ethnicity_known", "ok_ethnicity"), ("qd_computable", "qd_computable"),
               ("lrs_computable", "lrs_computable"), ("joint_core7", "ok_core7"), ("joint_core8", "ok_core8")]
eth_rows, eth_maps = [], []
for src in ETH_SOURCES:
    p_src = {**P, "ethnicity_source": src}
    per_cohort = {}
    for c, d in data.items():
        if src == P["ethnicity_source"]:
            s = snaps[c]
        else:
            pool = cohorts.positive_pool(d)
            ref = pd.Series(cohorts.data_end_date(d), index=pool.index)
            s = phenotype.core_snapshot(d, ref, lookback_days=None, p=p_src).join(pool[["status"]])
            s = s.join(qd.score(s, years=10, p=p_src)[["qd_computable", "ethn_qd"]])
            s = s.join(lrs.score(s, p=p_src)[["lrs_computable"]])
        for grp, g in [("all", s), *s.groupby("status")]:
            row = {"cohort": c, "group": grp, "ethnicity_source": src, "default": src == P["ethnicity_source"], "n": len(g)}
            for name, col in ETH_COMPARE:
                row[f"{name}_n"] = int(g[col].astype(bool).sum())
                row[f"{name}_pct"] = round(100 * g[col].astype(bool).mean(), 1)
            eth_rows.append(row)
        per_cohort[c] = s.groupby([s["ethnicity_source_value"].fillna("<missing>"), s["ethnicity"].fillna("<missing>"),
                                   "ethn_qd"]).size()
    m = pd.concat(per_cohort, axis=1).fillna(0).astype(int).reset_index()
    m.columns = ["source_value", "ethnic_group", "qdiabetes_category", *per_cohort]
    eth_maps.append(m.assign(ethnicity_source=src))
eth_cmp = pd.DataFrame(eth_rows)
for name, _ in ETH_COMPARE:     # a rate must not reveal a count < 10
    eth_cmp = sdc.suppress_rates(eth_cmp, f"{name}_n", ["n"], [f"{name}_pct"])
eth_cmp = sdc.suppress_small_counts(eth_cmp, [c for c in eth_cmp.columns if c.endswith("_n")])
run.save_table(eth_cmp, "nb01/ethnicity_source_compare.csv",
               "Ethnicity known, QDiabetes / Leicester computable and joint completeness (core-7 without ethnicity, "
               "core-8 = core-7 + ethnicity) by ethnicity source [D6 pending]")
eth_map_all = pd.concat(eth_maps, ignore_index=True)[["ethnicity_source", "source_value", "ethnic_group",
                                                      "qdiabetes_category", *snaps]]
eth_map_all = sdc.collapse_rare_rows(eth_map_all, list(snaps), ["source_value", "ethnic_group", "qdiabetes_category"],
                                     by=["ethnicity_source"])
run.save_table(sdc.suppress_small_counts(eth_map_all, list(snaps)), "nb01/ethnicity_mapping_by_source.csv",
               "Ethnicity source value → ethnic group → QDiabetes category, per source (labels seen in < 10 patients merged)")
print(eth_cmp.to_string(index=False))

# %% [markdown]
# ## 2. Selection effect: C1 (complete records) vs C2 (random)
# SMD |d| > 0.1 is flagged as meaningful imbalance (`breakdowns.selection_effect`). c1 / c2: mean (binary: share
# 0–1) over patients with a value. Saved table: a share with < 10 patients (or < 10 without) is hidden, and its SMD.

# %%
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
sel = breakdowns.selection_effect(f1, f2)
run.save_table(breakdowns.suppressed_selection_effect(sel), "nb01/selection_effect_smd.csv",
               "C1 vs C2 standardised mean differences (|SMD| > 0.1 = imbalance)")
print(sel.drop(columns=["c1_k", "c2_k"]).to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for ax, col, bins in [(axes[0], "age", 30), (axes[1], "bmi", 30)]:
    for c, s in snaps.items():
        s[col].dropna().plot.hist(bins=bins, ax=ax, alpha=0.5, density=True, label=c.upper())
    ax.set_title(f"{col} — C1 vs C2")
    ax.legend()
fig.tight_layout()
run.save_figure(fig, "nb01/selection_age_bmi.png", "C1 vs C2 age/BMI distribution")

# %% [markdown]
# ## 3. Score computability and distributions
# QDiabetes: reduced Model A (`PARAMS["qd_force_reduced_model"]`), 10-year risk.
# Leicester: `lrs_variant`. LPRS (default) = age, sex, ethnicity (BME), BMI, family history,
# antihypertensive medication — no waist circumference; the score is a linear predictor (not an absolute risk). LRA 2010: waist required.
# `lrs_outside_dev_age_pct`: patients outside the LPRS development age range (40–75) (extrapolation).

# %%
comp_rows, reasons = [], []
for c, s in snaps.items():
    for grp, g in [("all", s), *s.groupby("status")]:
        outside = ~g["age"].between(*lprs.DEV_AGE_RANGE)
        lprs_on = P["lrs_variant"] == "practice_2012"
        comp_rows.append({"cohort": c, "group": grp, "n": len(g),
                          "qd_computable_n": int(g["qd_computable"].sum()),
                          "qd_computable_pct": round(100 * g["qd_computable"].mean(), 1),
                          "lrs_computable_n": int(g["lrs_computable"].sum()),
                          "lrs_computable_pct": round(100 * g["lrs_computable"].mean(), 1),
                          "lrs_outside_dev_age_n": int(outside.sum()) if lprs_on else None,
                          "lrs_outside_dev_age_pct": round(100 * outside.mean(), 1) if lprs_on else None,
                          "qd_variant": g["qd_variant"].iloc[0] if len(g) else None,
                          "lrs_variant": LRS_LABEL})
    for score_name, col in [("qdiabetes", "qd_missing"), ("lrs", "lrs_missing")]:
        r = s[col].str.split(";").explode()
        reasons.append(breakdowns.category_shares(r[r != ""], "reason", len(s)).assign(cohort=c, score=score_name))
computability = pd.DataFrame(comp_rows)
reasons = pd.concat(reasons, ignore_index=True)[["cohort", "score", "reason", "n", "n_cohort", "pct"]]
# A rate is hidden where its count or (N − count) is < 10 (sdc.suppress_count_rate_pairs); the helper counts dropped
comp_counts = ["qd_computable", "lrs_computable", "lrs_outside_dev_age"]
run.save_table(sdc.suppress_count_rate_pairs(computability, "n", [(f"{k}_n", f"{k}_pct") for k in comp_counts])
               .drop(columns=[f"{k}_n" for k in comp_counts]),
               "nb01/score_computability.csv", f"QDiabetes / {LRS_LABEL} computability")
run.save_table(breakdowns.suppressed_shares(reasons), "nb01/score_missing_reasons.csv",
               "Reasons a score could not be computed")
print(computability.to_string(index=False))
print(reasons.to_string(index=False))

# Where smoking came from (D28: undated records used only if consistent; conflicting → missing)
sm_src = pd.concat([breakdowns.smoking_source(s).assign(cohort=c) for c, s in snaps.items()], ignore_index=True)
sm_src = sm_src[["cohort", "smoking_source", "n", "n_cohort", "pct"]]
run.save_table(breakdowns.suppressed_shares(sm_src), "nb01/smoking_source.csv", "Smoking status source (D28)")
print(sm_src.to_string(index=False))

fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
for c, s in snaps.items():
    (100 * s["qd_risk_10y"]).dropna().plot.hist(bins=40, ax=axes[0], alpha=0.5, density=True, label=c.upper())
    if s["lrs_score"].notna().any():
        s["lrs_score"].dropna().plot.hist(bins=range(0, 49, 2) if lrs.VARIANTS[P["lrs_variant"]]["points"] else 30,
                                          ax=axes[1], alpha=0.5, density=True, label=c.upper())
axes[0].set_title("QDiabetes-2018 A — 10-year risk (%)")
axes[1].set_title(f"{LRS_LABEL} — score")
if LRS_THR is not None:
    axes[1].axvline(LRS_THR, ls="--", color="k")
for ax in axes:
    if ax.get_legend_handles_labels()[0]:
        ax.legend()
fig.tight_layout()
run.save_figure(fig, "nb01/score_distributions.png", "Score distributions (descriptive only)")

dist = []
for c, s in snaps.items():
    for grp, g in s.groupby("status"):
        q, x = g["qd_risk_10y"].dropna(), g["lrs_score"].dropna()
        high = None if LRS_THR is None else int((x >= LRS_THR).sum())
        dist.append({"status": grp, "qd_n": len(q), "qd_median_pct": round(100 * q.median(), 2) if len(q) else None,
                     "lrs_n": len(x), "lrs_median": x.median(), "lrs_p25": x.quantile(.25), "lrs_p75": x.quantile(.75),
                     "lrs_high_risk_n": high,
                     "lrs_high_risk_pct": None if high is None else round(100 * high / max(len(x), 1), 1),
                     "cohort": c, "lrs_variant": LRS_LABEL})
dist = pd.DataFrame(dist)
# Medians / quartiles over < 10 scores hidden; the high-risk % where flagged or (scored − flagged) is < 10
dist_out = sdc.suppress_small_group_stats(dist, "qd_n", ["qd_median_pct"])
dist_out = sdc.suppress_small_group_stats(dist_out, "lrs_n", ["lrs_median", "lrs_p25", "lrs_p75"])
dist_out = sdc.suppress_rates(dist_out, "lrs_high_risk_n", ["lrs_n"], ["lrs_high_risk_pct"])
run.save_table(dist_out.drop(columns=["qd_n", "lrs_n", "lrs_high_risk_n"]), "nb01/score_summary.csv",
               "Score summaries (descriptive)")
print(dist.to_string(index=False))

# %% [markdown]
# ## 3b. Treated hypertension and smoking level (how two score inputs are derived)
# - Hypertension: patients with a diagnosis only / medication only / both / neither. QDiabetes counts diagnosis OR
#   medication (`qd_treated_htn`, D36; the QDiabetes-2018 definition, diagnosis AND medication, as a sensitivity run),
#   LPRS medication only, LRA 2010 diagnosis OR medication (`counted_as_treated_by`).
# - Smoking: the QDiabetes level each patient gets (non / ex / light / moderate / heavy / missing) by what it was
#   recorded as. NABIDH SocialHistory has no structured ex-smoker value (`nabidh.SMOKING_VALUES`): "ex" comes only
#   from a diagnosis code (`n_from_diagnosis_code`). Occasional / rare → light and "current" without intensity →
#   `qd_smoking_current_category` are interim [DECISION PENDING — D7]; "other" is not mapped → missing.

# %%
htn = pd.concat([breakdowns.htn_derivation(s, p=P).assign(cohort=c) for c, s in snaps.items()], ignore_index=True)
htn = htn[["cohort", *htn.columns.drop("cohort")]]
htn_out = sdc.suppress_small_counts(sdc.suppress_rates(htn, "n", ["n_group"], ["pct"]), ["n", "n_group"])
run.save_table(htn_out, "nb01/htn_derivation.csv",
               "Hypertension diagnosis / medication / both / neither, and which set each score counts as treated")
print(htn.to_string(index=False))

sm_lvl = pd.concat([breakdowns.smoking_levels(s, data[c]["observations"], P).assign(cohort=c)
                    for c, s in snaps.items()], ignore_index=True)
sm_lvl = sm_lvl[["cohort", *sm_lvl.columns.drop("cohort")]]
sm_lvl_out = sdc.suppress_rates(sm_lvl, "n", ["n_cohort"], ["pct"])
sm_lvl_out = sdc.suppress_small_counts(sm_lvl_out, ["n", "n_from_diagnosis_code"]).drop(columns="n_cohort")
run.save_table(sm_lvl_out, "nb01/smoking_level.csv",
               "QDiabetes smoking level per patient by what it was recorded as [D7 pending]")
print(sm_lvl.to_string(index=False))

# %% [markdown]
# ## 4. C1 — detection rate in known positives (sensitivity)
# The primary question of Study Flow step 1: what percentage of patients known to have diabetes / prediabetes
# does the score find "high risk"? C2 for comparison (positive sample without a completeness requirement).
# - Leicester: score ≥ the active variant's threshold (`lrs.threshold(P)`: LPRS → `lprs_high_risk_threshold`,
#   D23: no threshold yet → "Pending"; LRA 2010 → `lrs_high_risk_threshold` = 16). The `variant` column
#   shows which score was used. QDiabetes: `horizon_years` risk ≥ `qd_risk_threshold_pct`
#   (same threshold as NB2; D5: no threshold yet → "Pending").
# - Reference date [DECISION PENDING — D22]: `data_end` (data end; same as completeness) and `first_evidence`
#   (the first evidence day that sets the status, that day included; records after diagnosis are excluded).
# - `sens_computable`: flagged / score computable (Wilson 95% CI). `sens_all`: flagged / all
#   patients (not computable = not flagged).
# - Limitation: prevalent cases (not prospective); C1 are patients with complete records (selection effect §2).

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
detection["n_flagged"] = detection["n_flagged"].astype("Int64")   # NA in "Pending" (no-threshold) rows
det_out =sdc.suppress_rates(detection, "n_flagged", ["n_computable", "n"], rate_cols)
det_out = sdc.suppress_small_counts(det_out, ["n", "n_computable", "n_flagged"])
run.save_table(det_out, "nb01/c1_detection_rate.csv",
               f"Detection rate in known positives (sensitivity) — {LRS_LABEL} / QDiabetes, two reference dates")
print(detection.to_string(index=False))

# %% [markdown]
# ## 5. Ethnic group mapping check (nationality / ethnicity → group → QDiabetes)
# Source: `PARAMS["ethnicity_source"]`. "Other (unmapped nationality)" rows are candidates to add to the
# mapping table (codelists.NATIONALITY_COUNTRIES) [decision pending — D6].

# %%
src_name = P["ethnicity_source"]
eth_map = pd.concat({c: s.groupby([s["ethnicity_source_value"].fillna("<missing>"),
                                   s["ethnicity"].fillna("<missing>"), "ethn_qd"]).size()
                     for c, s in snaps.items()}, axis=1).fillna(0).astype(int).reset_index()
eth_map.columns = [f"{src_name}_raw", "ethnic_group", "qdiabetes_category", *snaps]
run.save_table(sdc.suppress_small_counts(eth_map, list(snaps)), "nb01/ethnicity_mapping.csv",
               f"{src_name} → ethnic group → QDiabetes mapping [decision pending]")
print(eth_map.to_string(index=False))

# %%
kpi_values = {
    "c1_achievable_note": "C1 achievable N from the NABIDH report (build_report / delivery note)",
    "joint_core8_pct": {r["cohort"]: r["joint_core8_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "joint_lrs_pct": {r["cohort"]: r["joint_lrs_pct"] for _, r in joint[joint["group"] == "all"].iterrows()},
    "joint_n": {r["cohort"]: {"n": int(r["n"]), "core8_n": int(r["joint_core8_n"]), "lrs_n": int(r["joint_lrs_n"])}
                for _, r in joint[joint["group"] == "all"].iterrows()},
    "qd_computable_pct": {r["cohort"]: r["qd_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "lrs_computable_pct": {r["cohort"]: r["lrs_computable_pct"] for _, r in computability[computability["group"] == "all"].iterrows()},
    "lrs_variant": P["lrs_variant"], "lrs_label": LRS_LABEL, "lrs_threshold": LRS_THR,
    "selection_effect_max_abs_smd": float(sel["smd"].abs().max()),
    "selection_effect_imbalanced_vars": sel.loc[sel["imbalance"], "variable"].tolist(),
    # C1 primary aim: detection rate (% among those with a computable score); None = no threshold / not computable
    "c1_detection_pct": {f"{r['reference']}|{r['score']}": None if pd.isna(r["sens_computable"])
                         else float(r["sens_computable"])
                         for _, r in detection[(detection["cohort"] == "c1") & (detection["group"] == "all")].iterrows()},
    # counts behind c1_detection_pct: kpi.py hides a rate whose flagged or (computable − flagged) is < 10
    "c1_detection_counts": {f"{r['reference']}|{r['score']}": {"n_flagged": int(r["n_flagged"]),
                                                               "n_computable": int(r["n_computable"])}
                            for _, r in detection[(detection["cohort"] == "c1") & (detection["group"] == "all")
                                                  & detection["n_flagged"].notna()].iterrows()},
}
run.save_json(kpi_values, "nb01/kpi_values.json", "NB1 KPI inputs")
manifest = run.finish()
print("Run:", run.run_id)
