"""Central configuration.

All analysis parameters live here. Changes are written to the audit log automatically
(audit.Run records the PARAMS dictionary of this module).

Source documents:
- MVP Dataset v1.0 (code lists)
- Interim Data Assessment (C1/C2 definition, cap = 2,600)
- Non-Diabetic Cohort Spec v2 (C3: index, lookback, follow-up, outcome)
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = {
    "synthetic": DATA_DIR / "synthetic" / "raw",
    "nabidh": DATA_DIR / "nabidh" / "raw",
}
CANONICAL_DIR = DATA_DIR / "canonical"          # canonical/<source>/<cohort>/
OUTPUT_DIR = REPO_ROOT / "outputs"
AUDIT_DIR = OUTPUT_DIR / "audit"

COHORTS = ("c1", "c2", "c3")

# --------------------------------------------------------------------------
# Analysis parameters (single source of truth)
# --------------------------------------------------------------------------
PARAMS = {
    # General
    "seed": 42,
    "age_min": 25,                    # QDiabetes valid range
    "age_max": 84,

    # Ethnicity source: "nationality" | "ethnicity" (NABIDH ethnicity field).
    # [DECIDED: 2026-11-13, ensargunesdogdu] Nationality is used instead of ethnicity. The content of the
    # nationality → ethnic group mapping (codelists.NATIONALITY_COUNTRIES) is separately [DECISION PENDING] (D6).
    "ethnicity_source": "nationality",

    # Glycaemic thresholds (ADA 2024) — mg/dL and %
    "hba1c_dm": 6.5,
    "hba1c_pre_low": 5.7,
    "fpg_dm": 126.0,
    "fpg_pre_low": 100.0,
    "ogtt_dm": 200.0,
    "ogtt_pre_low": 140.0,
    "random_glucose_dm": 200.0,

    # Applicant Data Requirement Framework Match by variable (framework.py): Match / Partial / Absent. A variable is
    # Partial when it arrived but not as requested: more than `framework_derived_max_pct` of its records are not in
    # the requested code system (drug code → ATC, family history from text), a substitute field / only some of the
    # requested levels came, or (recorded variables only) fewer than `framework_min_patient_pct` of the patients have a
    # value. How full a variable is stays with the Data Completeness KPI (≥ 90%).
    # [DECISION PENDING] both thresholds are the developer's proposal; medical team / DFF to confirm.
    "framework_min_patient_pct": 50,
    "framework_derived_max_pct": 5,

    # C1 / C2 (Interim Data Assessment)
    "c1_cap": 2600,
    "c2_cap": 2600,
    # C1 completeness definition: family history / CVD / HTN codes are treated as "present/absent".
    # True → a family history record (FamilyHistory positive/negative or Z83.3) is required.
    # [DECISION PENDING] D17 — to be settled once NABIDH's C1 definition is seen in the enclave.
    "c1_require_fh_record": False,
    # Family history of diabetes (first-degree relative; FamilyHistory record and Z83.3) is taken as present / absent.
    # Non-diabetes condition records are dropped in the adapter. The record date is not used: undated records and
    # records entered after the reference date also count. NABIDH FamilyHistory.EnteredOn is mostly empty.
    # [DECIDED: 2026-11-19, ensargunesdogdu] D27. False → only records dated up to the reference date.
    "family_history_any_date": True,
    # Smoking without a usable dated record (NABIDH SocialHistory.EnteredOn is mostly empty): if all of the patient's
    # undated structured smoking records give the same QDiabetes category, that value is used (date ignored).
    # Order: latest dated record up to the reference date → smoking diagnosis code → consistent undated records.
    # Conflicting undated records → missing. Unmapped values ("other") are not compared.
    # [DECIDED: 2026-11-19, ensargunesdogdu] D28. False → undated records are not used.
    "smoking_undated_if_consistent": True,

    # C3 (Non-Diabetic Cohort Spec v2)
    # The two versions of the v2 document disagree: 24 months (first version) vs 12 months (2026-11-13).
    # [DECIDED: 2026-11-13, ensargunesdogdu] D3: 1 year primary; 2 years (730 days) as an extra check via a sensitivity
    # run: SANDBOX_PARAMS='{"predictor_lookback_days": 730}' (.run "4c").
    "predictor_lookback_days": 365,
    "min_followup_gap_days": 0,       # a v2 sub-version suggests ">= 3 months"; 0 = no requirement
    # [DECIDED: 2026-11-13, ensargunesdogdu] D2: primary horizon 3 years "for now" — to be assessed
    # in detail. 5 years continues to be reported as the secondary horizon.
    "horizon_years": 3,               # primary
    "horizon_years_fallback": 5,      # secondary (reported without CI in NB2)
    "c3_cap": None,                   # v2: "no cap"
    # An event within N days after index = already diabetic at baseline (undiagnosed); the patient
    # is removed from the cohort. The NB0 sensitivity table reports 0/90/180.
    # [DECIDED: 2026-11-13, ensargunesdogdu] D1: 90 days (v2 had no washout; 0 = v2 sensitivity, .run "4b").
    "outcome_washout_days": 90,

    # QDiabetes-2018 Model A (scores/qdiabetes2018a.py) — items marked [DECISION PENDING] are with the medical team
    # The revised MVP asks for only the 8 core variables → steroids, statins, atypical antipsychotics,
    # schizophrenia/bipolar, learning disability, GDM, PCOS = 0 ("reduced Model A"). False → used if present in the data.
    "qd_force_reduced_model": True,          # [DECIDED: 2026-11-13, ensargunesdogdu] D9: stays out of scope
    "qd_townsend": 0.0,                      # [DECIDED: 2026-11-13, ensargunesdogdu] D10: out of scope → 0
    "qd_smoking_current_category": 3,        # "current" without intensity → 3=moderate [DECISION PENDING] D7
    # Treated hypertension as QDiabetes reads it. QDiabetes-2018 defines it as a hypertension diagnosis AND an
    # antihypertensive drug ("dx_and_med"); here a diagnosis OR a drug counts ("dx_or_med"): NABIDH has many patients
    # with only one of the two (VM 2026-11-20, C1: diagnosis only 10.4%, drug only 5.0%, both 28.1%).
    # [DECIDED: 2026-11-20, ensargunesdogdu] D36. "dx_and_med" = the published definition, for a sensitivity run.
    "qd_treated_htn": "dx_or_med",
    # [DECIDED: 2026-11-13, ensargunesdogdu] D8: no smoking record = unknown (not counted as non-smoker) →
    # QDiabetes is not computed; the missingness reason is reported as "smoking_missing".
    "qd_missing_smoking_as_non": False,
    # The source code only gives the 10-year baseline survival. For other horizons
    # S0(t) = S0(10)^(t/10) (constant baseline hazard assumption) [DECISION PENDING]
    "qd_baseline_time_scaling": "power",
    # Horizon risk threshold (%) for sens/spec/PPV. [DECIDED: 2026-11-13, ensargunesdogdu] D5: default for now
    # (None) → threshold KPIs "Pending".
    "qd_risk_threshold_pct": None,

    # Leicester score (scores/lrs.py → variant selector). Waist circumference is not in the NABIDH delivery list →
    # LRA 2010 cannot be computed (K-LRS).
    # [DECIDED: 2026-11-14, ensargunesdogdu + Zeynep Pelin Polat] K-LRS: option (b) — the Leicester Practice Risk
    # Score, which needs no waist circumference (Gray et al., Diabetologia 2012;55:959–966), is used
    # (Slack #sandboxteam, 2026-11-13). LRA 2010 stays for comparison:
    # SANDBOX_PARAMS='{"lrs_variant": "assessment_2010"}'.
    "lrs_variant": "practice_2012",          # "practice_2012" (LPRS, no waist) | "assessment_2010" (LRA, waist required)
    # LPRS is a linear predictor (no intercept, not an absolute risk); there is no published absolute threshold —
    # the authors used ranking (top 10% per practice / target sensitivity). Until a threshold value
    # (score ≥ x → high risk) is chosen, None → C1 capture rate and threshold metrics "Pending".
    "lprs_high_risk_threshold": None,        # [DECISION PENDING] D23
    # Hypertension as LPRS reads it. Gray 2012 uses antihypertensive medication only ("med"); here a hypertension
    # diagnosis OR a drug counts ("dx_or_med"), the same rule as QDiabetes (qd_treated_htn).
    # [DECIDED: 2026-11-20, ensargunesdogdu] D36. "med" = the published definition, for a sensitivity run.
    "lprs_treated_htn": "dx_or_med",
    "lrs_high_risk_threshold": 16,           # assessment_2010 only: ≥16 high risk (NHS Health Check)
    "lrs_unknown_ethnicity_as_missing": True,  # both variants: "Not recorded" → score not computed [DECISION PENDING] D12

    # Recalibration (Arm 2)
    "recal_split": "temporal",               # "temporal" (by index date) | "random"
    "recal_train_frac": 0.7,

    # Subgroups
    "age_band_edges": [25, 40, 55, 70, 85],  # [25,40) [40,55) [55,70) [70,85)
    "age_band_labels": ["25–39", "40–54", "55–69", "70–84"],

    # Manual KPI input
    "security_incidents": 0,                 # Data Security KPI — manual, from the enclave incident log

    # Statistics
    "bootstrap_reps": 500,
    "min_events_subgroup": 50,
    "small_cell_threshold": 10,       # n < 10 → "<10" in output tables
}
