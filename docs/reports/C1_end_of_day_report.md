_Exported from the live C1 report on 2026-11-20. Source: VM COPY block `logs/enclave/2026-11-20.log`, `run all` 20 Nov 2026 10:51 UTC, bundle 72efc39be6ba, ingest 1.4.2 (D36 hypertension rule; QDiabetes medians before D36 from the 09:56 block in the same file). Aggregates only; counts under 10 show as "<10". Data behind every table: [data/c1_report.json](data/c1_report.json)._

_DHA HEALTH DATA SANDBOX · PHASE 1 · COHORT C1_

# C1 End-of-Day Report

C1 is the guaranteed complete-case set: known type 2 diabetes and prediabetes patients in NABIDH. The question here is whether the pipeline works, not how good the scores are. Of **2,595** known positives, QDiabetes ran for **2,519** (**97.1%**), with ethnicity fixed at its reference group. The Leicester Practice Risk Score (LPRS) ran for **0**: it needs ethnicity, and ethnicity did not arrive. Leave ethnicity out and the other 7 core variables are complete for **97.1%**. One finding stands out: **98.7%** of C1 has a positive family history of diabetes, against **19.6%** in the random sample C2 (section 5). Scored with unknown ethnicity as White or as Other, LPRS runs for all but fewer than 10 C1 patients; what each score flags at each threshold is in section 6.

> From the enclave run of 20 November 2026, 10:51 UTC: bundle 72efc39be6ba, ingest 1.4.2, all four steps exit 0. Treated hypertension follows decision D36 (diagnosis or drug, for QDiabetes and LPRS).

## 1 · Can the scores run?

From delivered patients to patients each score was produced for. The other colour is the same run with ethnicity read from the NABIDH EthnicGroup field instead of nationality, from NB1's ethnicity source comparison.

| Step | Patients | % of known positives | Run |
|---|---|---|---|
| Patients delivered (Patient view) | 2,596 | — | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| Known positives (T2DM or prediabetes evidence) | 2,595 | 100.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| QDiabetes computable | 2,519 | 97.1% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| 7 core variables complete (all but ethnicity) | 2,519 | 97.1% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · ethnicity from nationality (default) | 0 | 0.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · unknown ethnicity scored as White or Other (scenario) | all but <10 | suppressed (<10) | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · NABIDH EthnicGroup field | 168 | 6.5% | Same run · ethnicity from the NABIDH EthnicGroup field (NB1 comparison) |
| All 8 core variables · nationality (default) | 0 | 0.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| All 8 core variables · NABIDH EthnicGroup field | 162 | 6.2% | Same run · ethnicity from the NABIDH EthnicGroup field (NB1 comparison) |

### Each score input: how it is mapped, and what went wrong

| Input | Score | Mapping | Issue | Value | Unit | Status |
|---|---|---|---|---|---|---|
| Age band | QDiabetes 25–84 | Patient.Age (no date of birth) | Outside 25–84: score not computed | 0 | patients | Works |
| Age band | LPRS 40–75 | Patient.Age | Outside the LPRS development band (scored, flagged) | 30.2 | % of C1 | Works |
| Ethnicity | QDiabetes | Unknown → reference group 'White or not stated' | Fixed for every patient: no nationality column; risk may be underestimated for higher-risk groups | 2,595 | patients | Fixed value |
| Ethnicity | LPRS | White vs other, from nationality (default) | Not computable: ethnicity unknown | 2,595 | patients | Blocked |
| Ethnicity | LPRS | White vs other, from the NABIDH EthnicGroup field | Still unknown for most patients | 2,427 | patients | Blocked |
| Treated hypertension | QDiabetes, LPRS | ICD-10 I10–I16 diagnosis OR an antihypertensive drug (DDC → ingredient → ATC C02/C03/C07/C08/C09); decision D36 | Counted as treated: diagnosis, drug, or both | 43.5 | % of C1 | Works |
| Treated hypertension | QDiabetes | Published QDiabetes-2018 definition: diagnosis AND drug | Counted now, not under the published definition (diagnosis only + drug only) | 15.4 | % of C1 | Decision D36 |
| Treated hypertension | LPRS | Published LPRS (Gray 2012) definition: drug only | Counted now, not under the published definition (diagnosis only) | 10.4 | % of C1 | Decision D36 |
| Smoking level | QDiabetes | Never / Low / Medium / High → never / light / moderate / heavy; Occasional → light (temporary, D7) | Smoking status missing: QDiabetes not computed | 74 | patients | Works |
| Smoking level | QDiabetes | Ex-smoker: no such value in SocialHistory; only from diagnosis code Z87.891 | QDiabetes 'ex-smoker' category is practically empty | <10 | patients | Gap |
| Smoking level | QDiabetes | 'Other' (may be shisha / midwakh) | Not mapped, decision D7 | 428 | rows | Decision pending |
| BMI | QDiabetes, LPRS | Observation 39156-5, else height 8302-2 + weight 3141-9, else Z68 band | BMI missing | <10 | patients | Works |
| Sex | QDiabetes, LPRS | Patient.Gender_Code M / F | Not male / female ('U') | <10 | patients | Works |
| Family history of diabetes | QDiabetes, LPRS | FamilyHistory (SNOMED / ICD-10 / text) first-degree + Z83.3; present / absent | Share with a positive first-degree family history (see section 5: far above C2) | 98.7 | % of C1 | Works |
| Cardiovascular disease | QDiabetes | ICD-10 I20–I25, I50, I6x, G45; present / absent | Share with a CVD diagnosis | 19.3 | % of C1 | Works |

> For present / absent inputs (family history, cardiovascular disease, hypertension) the value is the share of C1 with the condition, not a completeness figure.

### Treated hypertension: diagnosis, drug, or both

| C1 patients with | Patients | % | Counted as treated by |
|---|---|---|---|
| Diagnosis and medication | 729 | 28.1 | QDiabetes, LPRS, LRA 2010 |
| Diagnosis only | 269 | 10.4 | QDiabetes, LPRS, LRA 2010 |
| Medication only | 130 | 5.0 | QDiabetes, LPRS, LRA 2010 |
| Neither | 1,467 | 56.5 | none |

> Decision D36 (20 November): QDiabetes and LPRS count a hypertension diagnosis or an antihypertensive drug. The published definitions are narrower: QDiabetes-2018 needs both, LPRS (Gray 2012) the drug only. Both stay available as sensitivity runs. LRA 2010 is the older Leicester assessment, for reference.

### Smoking level as QDiabetes reads it

| Level | Recorded as | Patients | % | From a diagnosis code |
|---|---|---|---|---|
| Never | never | 2,177 | 83.9 | 0 |
| Ex-smoker | ex | <10 | suppressed (<10) | <10 |
| Light | light | 179 | 6.9 | 0 |
| Moderate | moderate | 45 | 1.7 | 0 |
| Moderate | current, intensity not recorded (D7 → moderate) | 10 | 0.4 | 10 |
| Heavy | heavy | 108 | 4.2 | 0 |
| Missing | undated records disagree (D28) | 60 | 2.3 | 0 |
| Missing | no smoking record | 10 | 0.4 | 0 |
| Missing | records present, none usable (unknown / unmapped, e.g. other) | <10 | suppressed (<10) | 0 |

> SocialHistory has no ex-smoker value, so that level comes only from a diagnosis code. "Current, intensity not recorded" is set to moderate (decision D7).

### QDiabetes 10-year risk in C1 (median): what D36 changed

| Group | Diagnosis and drug (09:56 run) | Diagnosis or drug (D36, from 10:25) | Change, points |
|---|---|---|---|
| Prediabetes | 3.02% | 3.19% | +0.17 |
| T2DM | 7.78% | 8.26% | +0.48 |

> Same data, same patients; only the hypertension rule differs. The 15.4% of C1 with a diagnosis or a drug alone now get the hypertension term, so their risk rises. Risk is shown to describe the pipeline, not to judge the score: C1 holds known positives only.

## 2 · Data Completeness (KPI, target ≥ 90%, owner DHA)

By definition C1 should be 100% complete. This is the first test of the KPI: is it really complete, and are there values that are filled but not usable?

| KPI | Target | Actual (today's KPI run) | Status | What it means for C1 |
|---|---|---|---|---|
| Data Completeness for Required Variables | >= 90% | C1 0.0%; C2 0.0% | Not Met | C1 should be 100% by definition; the first test of this KPI |

The KPI takes the weakest of the 8 core variables. Ethnicity is 0%, so the KPI is 0%. Without ethnicity the weakest is smoking at **97.1%**, and all 7 other variables are complete together for **97.1%** of C1.

### Completeness by variable

| Variable | Measured as | Patients | With a usable value | % | ≥ 90% | What is counted |
|---|---|---|---|---|---|---|
| Sex | Recorded value | 2,595 | suppressed (<10 missing) | suppressed (<10) | Yes | a value in the record |
| Age | Recorded value | 2,595 | 2,595 | 100.0 | Yes | a value in the record |
| Ethnicity | Recorded value | 2,595 | 0 | 0.0 | No | a value in the record |
| BMI | Recorded value | 2,595 | suppressed (<10 missing) | suppressed (<10) | Yes | a value in the record |
| Smoking | Recorded value | 2,595 | 2,521 | 97.1 | Yes | a value in the record |
| Family history of diabetes | Present / absent | 2,595 | 2,595 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 98.7% of C1 |
| Family history: a record exists | Recorded value | 2,595 | 2,584 | 99.6 | Yes | FamilyHistory record (positive / negative / other relative) or Z83.3 |
| Cardiovascular disease | Present / absent | 2,595 | 2,595 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 19.3% of C1 |
| Treated hypertension | Present / absent | 2,595 | 2,595 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 43.5% of C1 (diagnosis or drug, D36) |

> Family history, cardiovascular disease and hypertension are present / absent: a patient with no record of the condition is counted as not having it. Every patient therefore has a value (yes or no), so these rows are 100% by construction and say nothing about how full the data is; the ≥ 90% test does not apply to them. "A record exists" shows how many patients have any family history record. "With a usable value" counts patients who have the variable; the rest are missing it (for smoking, see the smoking level table in section 1 for why). Where fewer than 10 patients are missing a value, the count and the rate are both hidden.

### Completeness per score: the inputs each score reads

#### QDiabetes (reduced Model A)

| Input | Needed as | With a usable value | % |
|---|---|---|---|
| Sex | Required | suppressed (<10 missing) | suppressed (<10) |
| Age (25–84) | Required | 2,595 | 100.0 |
| Ethnicity | Not required: unknown → reference group | 0 | 0.0 |
| BMI | Required | suppressed (<10 missing) | suppressed (<10) |
| Smoking | Required | 2,521 | 97.1 |
| Family history of diabetes | Present / absent: 100% by definition | 2,595 | 100.0 |
| Cardiovascular disease | Present / absent: 100% by definition | 2,595 | 100.0 |
| Treated hypertension (diagnosis or drug, D36) | Present / absent: 100% by definition | 2,595 | 100.0 |
| All inputs, ethnicity as reference group = score computed | Joint | 2,519 | 97.1 |
| All inputs, ethnicity required (KPI 'Joint Completeness – QDiabetes') | Joint | 0 | 0.0 |

#### LPRS (Leicester Practice Risk Score, no waist)

| Input | Needed as | With a usable value | % |
|---|---|---|---|
| Age | Required | 2,595 | 100.0 |
| Sex | Required | suppressed (<10 missing) | suppressed (<10) |
| Ethnicity · nationality (default) | Required | 0 | 0.0 |
| Ethnicity · NABIDH EthnicGroup field | Required | 168 | 6.5 |
| BMI | Required | suppressed (<10 missing) | suppressed (<10) |
| Family history of diabetes | Present / absent: 100% by definition | 2,595 | 100.0 |
| Hypertension (diagnosis or drug, D36) | Present / absent: 100% by definition | 2,595 | 100.0 |
| All inputs · ethnicity from nationality = score computed (KPI 'Joint Completeness – LRS') | Joint | 0 | 0.0 |
| All inputs · ethnicity from the EthnicGroup field | Joint | 168 | 6.5 |

> The two scores read different inputs, so their completeness differs. QDiabetes runs without ethnicity: an unknown ethnicity takes its reference group, so 97.1% of C1 is scored. The KPI "Joint Completeness – QDiabetes" requires ethnicity as well, so it reads 0%. LPRS needs ethnicity and has no reference group, so it is scored for nobody with nationality and for 6.5% with the EthnicGroup field. Whether ethnicity should count for QDiabetes completeness is part of decision D32.

### Filled but not usable

| What | Variable | Rows | Handling |
|---|---|---|---|
| Vital rows with an empty value | BMI / height / weight | 7,441 | Dropped and counted |
| Vital rows with a placeholder ('0' or '-') | BMI / height / weight | 14,079 | Dropped and counted |
| Smoking rows 'Other' | Smoking | 428 | Not mapped (decision D7) |
| Smoking records present, none usable | Smoking | <10 | Counted as missing |
| Undated smoking records that disagree | Smoking | 60 | Counted as missing (D28) |
| Lab results that are not numbers | HbA1c / glucose | <10 | Dropped and counted |
| Diagnoses without a date | CVD / hypertension | 17 | Dropped and counted |
| Diagnoses dated exactly 1970-01-01 | Diagnoses | <10 | Counted, kept (decision D31) |
| Medications without a date | Hypertension treatment | 34 | Dropped and counted |
| Sex 'U' | Sex | <10 | Score not computed |

### Patients a score could not be produced for

| Score | Missing input | Patients | % |
|---|---|---|---|
| QDiabetes | Smoking status | 74 | 2.9 |
| QDiabetes | Sex not male / female | <10 | suppressed (<10) |
| QDiabetes | BMI | <10 | suppressed (<10) |
| LPRS | Ethnicity | 2,595 | 100.0 |
| LPRS | Sex not male / female | <10 | suppressed (<10) |
| LPRS | BMI | <10 | suppressed (<10) |

### Joint completeness by group and ethnicity source

| Ethnicity source | Group | Patients | 7 core | % | 8 core | % | LPRS inputs | % |
|---|---|---|---|---|---|---|---|---|
| Nationality (default) | All | 2,595 | 2,519 | 97.1 | 0 | 0.0 | 0 | 0.0 |
| Nationality (default) | Prediabetes | 1,376 | 1,327 | 96.4 | 0 | 0.0 | 0 | 0.0 |
| Nationality (default) | T2DM | 1,219 | 1,192 | 97.8 | 0 | 0.0 | 0 | 0.0 |
| NABIDH EthnicGroup field | All | 2,595 | 2,519 | 97.1 | 162 | 6.2 | 168 | 6.5 |

> Joint completeness is the share of patients who have every variable in a set at the same time, not one by one. Each variable can be nearly full on its own while the set is not, because the gaps fall on different patients, and one variable that never arrived (ethnicity) takes the whole set to 0%. 7 core: all but ethnicity, what QDiabetes needs here (ethnicity is fixed at its reference group). 8 core: all eight. LPRS inputs: age, sex, ethnicity, BMI, family history, hypertension. Per score, input by input: see "Completeness per score" above.

## 3 · Applicant Data Requirement Framework Match (Universal KPI)

Did the 8 requested variables arrive, and in the requested form? The KPI is now read variable by variable, and it is Partial. Ethnicity arrived only as the EthnicGroup field, filled for few patients, because nationality is not in the view. Drugs arrived as Dubai Drug Codes, so treated hypertension is derived, not delivered as ATC. Part of family history is recognised from text, not from a code. SocialHistory has no ex-smoker value.

| KPI | Target | Actual (today's KPI run) | Status | What it means for C1 |
|---|---|---|---|---|
| Applicant Data Requirement Framework Match | Match | Partial: ethnicity, smoking, family_history, hypertension | Partial | Did the 8 variables arrive, and in the requested form |

| Variable | Arrived as (view.column) | Route | Patients with a value | % | Match | Why not a full match |
|---|---|---|---|---|---|---|
| Sex | Patient.Gender_Code | As requested | suppressed (<10 missing) | suppressed (<10) | Match | — |
| Age | Patient.Age | As requested | 2,596 | 100.0 | Match | — |
| Ethnicity | Patient.Nationality \| Patient.EthnicGroup_Description | Substitute field | 168 | 6.5 | Partial | requested nationality not delivered; only ethnicity_raw has values; values for only 6.5% of patients (< 50%) |
| BMI | Observation.ObservationValue (LOINC 39156-5 BMI; 8302-2 height + 3141-9 weight) | As requested | suppressed (<10 missing) | suppressed (<10) | Match | — |
| Smoking | SocialHistory.SocialHabitQty_Description | As requested | 2,522 | 97.1 | Partial | level seen in < 10 patients: ex |
| Family history of diabetes | FamilyHistory.Diagnosis_Code | Derived by the adapter | 2,585 | 99.6 | Partial | 38% of the records not in the requested system (ICD-10 / SNOMED code) |
| Cardiovascular disease | Diagnosis.Diagnosis_Code | As requested | 502 | 19.3 | Match | — |
| Treated hypertension | Diagnosis.Diagnosis_Code + Medication.DrugProduct_Code | Derived by the adapter | 1,128 | 43.5 | Partial | drug: 100% of the rows not in the requested system (ATC) |

> From NB0 (nb00/framework_variables.csv). Partial means the variable arrived, but not as requested: a substitute field, a missing level, more than 5% of records in another code system, or values for fewer than 50% of patients. These two thresholds are the developer's proposal and wait for the medical team (decisions D29, D30). For CVD and hypertension the share is of patients with the condition.

## 4 · Data quality

### Ranges and units, after cleaning

| Measure | Unit | Patients | p5 | Median | p95 | Plausible range | Rows outside | Patients affected | Note |
|---|---|---|---|---|---|---|---|---|---|
| BMI | kg/m² | 2,595 | 21 | 28 | 39 | 12–80 | 94 | 80 | A value outside 12–80 is taken as an entry error and skipped. The patient's latest value inside the range is used; if there is none, BMI is computed from height and weight, then taken from a Z68 code |
| Height | cm | 2,596 | 152 | 165 | 183 | 120–230 | 892 | 492 | Mostly below 120 cm (876 rows), skipped; 125 rows given in metres, converted. Latest value inside the range from the full history goes into BMI |
| Weight | kg | 2,596 | 56 | 79 | 116 | 25–350 | 402 | 270 | A value outside 25–350 is skipped; the latest value inside the range goes into BMI from height and weight |
| HbA1c (4548-4) | % | 460 | 4.7 | 5.5 | 7.9 | — | — | — | Unit %, no mmol/mol seen |
| Fasting glucose (1558-6) | mg/dL | 920 | 80 | 97 | 165 | — | — | — | Unit mg/dL; 619 rows spelled MG/DL normalised |

> Plausible range: the values an adult measurement can realistically take, ends included: BMI 12–80 kg/m², height 120–230 cm, weight 25–350 kg, waist 40–250 cm. A value outside it is treated as an entry error (for example a unit mix-up or a test value; heights given in metres are converted to cm first) and is not used; the row stays in the data and is counted here. "Rows outside" counts such rows; "Patients affected" counts patients with at least one. The ranges are set in the code in one place (`phenotype.VITAL_PLAUSIBLE_RANGE`) and are the developer's choice, not a clinical decision yet.

> HbA1c and fasting glucose are eligibility and outcome evidence only; lab values are never score inputs.

### Coding systems

| Field | Expected | Arrived | Count | Of | Usable |
|---|---|---|---|---|---|
| Diagnosis_Code | ICD-10 | ICD-10-CM with dots (E11.9, R73.03, I10) | 87 | cells with 2 codes, split | Yes |
| Diagnosis_Code | ICD-10 | Trailing dot | 11 | codes cleaned | Yes |
| LabResultItem.TestItemCode_Code | LOINC | LOINC 1558-6, 4548-4, 1521-4 | — | — | Yes |
| Observation.ObservationCode_Code | LOINC | LOINC 39156-5, 8302-2, 3141-9 only | — | — | Yes |
| Medication.DrugProduct_Code | INN / ATC | DDC product code (Dubai Drug Code) | 19,427 | rows | Mapped: DDC → ingredient (INN) → ATC |
| Medication.DrugProduct_Code | INN / ATC | DDC scientific code | 3,806 | rows | Mapped |
| Medication.DrugProduct_Code | INN / ATC | 6-digit DDC stem | 125 | rows | Mapped |
| Medication.DrugProduct_Code | INN / ATC | VMP<id>,<dose>,<form> (no reference list) | 382 | rows | By drug name |
| Medication.DrugProduct_Code | INN / ATC | No code | 173 | rows | By drug name |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | SNOMED | 2,354 | rows | Yes |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | ICD-10 | 172 | rows | Yes |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | Text only (local codes) | 1,555 | rows | By description text |

## 5 · How C1 differs from C2 (selection effect)

C1 is a complete-case extract, C2 a random sample of the same positives. The standardised mean difference (SMD) shows how far apart they are; above 0.1 counts as an imbalance. Family history is the outlier: almost every C1 patient has a positive first-degree family history of diabetes. Being complete-case appears to have selected patients with a family history record, and nearly all of those records are positive. QDiabetes and LPRS both add risk for family history, so C1 scores will run higher than in an unselected population. C1 is also more female, younger, and has more current smokers recorded.

| Variable | C1 | C2 | SMD | \|SMD\| > 0.1 |
|---|---|---|---|---|
| Age (mean, years) | 46.1 | 49.7 | -0.33 | Yes |
| BMI (mean) | 28.3 | 28.5 | -0.05 | No |
| Male | 40.0% | 60.7% | -0.42 | Yes |
| T2DM (vs prediabetes) | 47.0% | 54.7% | -0.15 | Yes |
| Positive family history of diabetes | 98.7% | 19.6% | 2.71 | Yes |
| Cardiovascular disease | 19.3% | 17.2% | 0.06 | No |
| Hypertension diagnosis | 38.5% | 46.2% | -0.16 | Yes |
| Antihypertensive drug | 33.1% | 36.8% | -0.08 | No |
| Current smoker | 13.2% | 2.2% | 0.42 | Yes |
| Diabetes drug (A10) | 47.4% | 43.2% | 0.08 | No |

> Shares are % of patients with a value; age and BMI are means. Ethnic groups are not compared: ethnicity is unknown in both cohorts.

## 6 · Sensitivity in known positives

Every C1 patient is a known positive (type 2 diabetes or prediabetes), so the one thing a score can be checked on here is how many of them it flags as high risk: sensitivity. A score's threshold is not decided yet (D5 for QDiabetes, D23 for LPRS), so sensitivity is shown at a range of thresholds. LPRS needs ethnicity, which did not arrive, so it is scored twice: every unknown ethnicity taken as White, then as Other. The truth lies between the two.

> **Why there is no specificity, PPV, F1 or AUROC here.** These need patients without diabetes: how many of them the score wrongly flags. C1 and C2 hold only patients with diabetes or prediabetes, so there are none, and any such figure would be invented. They come from C3 in Phase 2, where patients start without diabetes and some develop it.

### LPRS with unknown ethnicity scored as White, then as Other

| Unknown ethnicity scored as | Patients | Scored | % | Median score | p25 | p75 |
|---|---|---|---|---|---|---|
| White | 2,595 | suppressed (<10 missing) | suppressed (<10) | 4.94 | 4.36 | 5.54 |
| Other | 2,595 | suppressed (<10 missing) | suppressed (<10) | 5.69 | 5.12 | 6.29 |

> "Other" adds the LPRS ethnicity term (0.757) for every patient whose ethnicity is unknown, so its scores are higher by that amount. Patients not scored here are missing BMI or sex, not ethnicity. Known ethnicity (none with nationality) is kept as it is.

#### QDiabetes: share flagged at each 10-year risk threshold

> Chart in the live report; the same values are in the table below.

#### LPRS: share flagged at each score threshold

> Chart in the live report; the same values are in the table below.

### All thresholds, with 95% confidence intervals

| Score | Flagged when | Scored | Flagged | Sensitivity % | 95% CI low | 95% CI high |
|---|---|---|---|---|---|---|
| QDiabetes | 10-year risk ≥ 1% | 2,519 | 2,229 | 88.5 | 87.2 | 89.7 |
| QDiabetes | 10-year risk ≥ 2.5% | 2,519 | 1,770 | 70.3 | 68.5 | 72.0 |
| QDiabetes | 10-year risk ≥ 5% | 2,519 | 1,300 | 51.6 | 49.7 | 53.6 |
| QDiabetes | 10-year risk ≥ 7.5% | 2,519 | 985 | 39.1 | 37.2 | 41.0 |
| QDiabetes | 10-year risk ≥ 10% | 2,519 | 764 | 30.3 | 28.6 | 32.2 |
| QDiabetes | 10-year risk ≥ 15% | 2,519 | 469 | 18.6 | 17.1 | 20.2 |
| QDiabetes | 10-year risk ≥ 20% | 2,519 | 290 | 11.5 | 10.3 | 12.8 |
| LPRS · unknown ethnicity as White | score ≥ 4 | all but <10 | 2,341 | 90.3 | 89.1 | 91.4 |
| LPRS · unknown ethnicity as White | score ≥ 4.5 | all but <10 | 1,800 | 69.4 | 67.6 | 71.2 |
| LPRS · unknown ethnicity as White | score ≥ 5 | all but <10 | 1,228 | 47.4 | 45.4 | 49.3 |
| LPRS · unknown ethnicity as White | score ≥ 5.5 | all but <10 | 692 | 26.7 | 25.0 | 28.4 |
| LPRS · unknown ethnicity as White | score ≥ 6 | all but <10 | 295 | 11.4 | 10.2 | 12.7 |
| LPRS · unknown ethnicity as White | score ≥ 6.5 | all but <10 | 110 | 4.2 | 3.5 | 5.1 |
| LPRS · unknown ethnicity as White | score ≥ 7 | all but <10 | 24 | 0.9 | 0.6 | 1.4 |
| LPRS · unknown ethnicity as White | score ≥ 7.5 | all but <10 | <10 | suppressed (<10) | suppressed (<10) | suppressed (<10) |
| LPRS · unknown ethnicity as Other | score ≥ 4 | all but <10 | 2,583 | 99.6 | 99.3 | 99.8 |
| LPRS · unknown ethnicity as Other | score ≥ 4.5 | all but <10 | 2,481 | 95.7 | 94.8 | 96.4 |
| LPRS · unknown ethnicity as Other | score ≥ 5 | all but <10 | 2,072 | 79.9 | 78.3 | 81.4 |
| LPRS · unknown ethnicity as Other | score ≥ 5.5 | all but <10 | 1,501 | 57.9 | 56.0 | 59.8 |
| LPRS · unknown ethnicity as Other | score ≥ 6 | all but <10 | 975 | 37.6 | 35.8 | 39.5 |
| LPRS · unknown ethnicity as Other | score ≥ 6.5 | all but <10 | 450 | 17.4 | 15.9 | 18.9 |
| LPRS · unknown ethnicity as Other | score ≥ 7 | all but <10 | 178 | 6.9 | 6.0 | 7.9 |
| LPRS · unknown ethnicity as Other | score ≥ 7.5 | all but <10 | 47 | 1.8 | 1.4 | 2.4 |

> Sensitivity = flagged / scored, with the Wilson 95% interval. Reference date: the end of the data. Where the flagged count, or the rest, is under 10, the rate is hidden. These are prevalent cases scored on their current record, not a prospective test.

## 7 · Process KPIs, and what C1 does not measure

### Critical process KPIs (measured over the whole sandbox, not from data)

| KPI | Target | Actual | Status | Note |
|---|---|---|---|---|
| Audit Trail Completeness | 100% | 100.0% (96/96 runs) | Met | Closed after the fact as abandoned (run_end appended, D34): 20261119T054135Z_nb00_data_profile_b068d0 |
| Evidence Package Completeness | Complete | — | Pending | — |
| Data Security / No-Incident | 0 incidents | 0 incidents | Met | — |

### Performance KPIs: not measured in C1 (Phase 2, C3)

| KPI | Target | Status |
|---|---|---|
| Sensitivity (Recall, positive class) | >= 70% | Pending |
| Specificity | >= 70% | Pending |
| NPV & PPV | Documented | Pending |
| AUROC | >= 0.75 | Pending |
| C-Index | 0.55-0.90 | Pending |
| Precision / Recall / F1 | Documented | Pending |
| Recalibration Slope / O:E | Documented | Pending |
| Alert Rate per 1,000 Patients | Pending NABIDH | Pending |

> These KPI rows are measured in C3 (Phase 2). Section 6 shows sensitivity in known positives only, for orientation; it is not the KPI.

## Open items

- Decisions for the medical team and DHA are collected, with today's numbers, in the [Phase 1 Decision Pack](https://claude.ai/artifact/4f6qU3GPJdmU7JngbQ8xmp): ethnicity source (D6), smoking 'Other' (D7), the Partial thresholds (D29, D30), placeholder dates (D31), the Data Completeness definition (D32), and how detection is shown (D33).
- Audit Trail is 100%: the run left open on 19 November was closed by appending a closing record (D34); nothing was deleted.
- From DHA: a nationality field, a facility field (none is mapped, so facility representation cannot be shown), and read access to the C1 Encounter view (the query returns a privilege error).
- Which row of section 6 is "the" detection rate depends on a threshold for each score (D5 for QDiabetes, D23 for LPRS) and, for LPRS, on the ethnicity source (D6).

## Definitions

- Known positive: a C1 patient with type 2 diabetes or prediabetes evidence (diagnosis, HbA1c, fasting glucose or a diabetes drug).
- The 8 core variables: sex, age, ethnicity, BMI, smoking, family history of diabetes, cardiovascular disease, treated hypertension.
- Family history of diabetes: from the NABIDH FamilyHistory view and the patient's own Z83.3 diagnosis. A record counts as diabetes by its code (ICD-10 E08–E14 or Z83.3; SNOMED 160303001, 73211009, 44054006, 46635009) or, when the code is a local number or text, by its description ("diabet", "DM"); prediabetes records and other conditions are left out. There is no yes / no column, so a diabetes record is positive unless its text negates it ("No history of …", "denies"). Father, mother, brother, sister, child or parent is first degree; aunts, uncles, grandparents and cousins are recorded but not counted positive. A patient is positive with any first-degree positive record, whatever its date (D27), or with Z83.3.
- QDiabetes-2018 Model A without lab values, on the 8 core variables (reduced model, decision D9). LPRS is the Leicester Practice Risk Score (Gray 2012), without waist circumference.
- Open decisions: see the Decision Pack linked above. D5 / D23 score thresholds are only needed for the C1 detection rate and in Phase 2.
- Treated hypertension (D36): a hypertension diagnosis or an antihypertensive drug counts, for QDiabetes and LPRS. This departs from both published definitions (QDiabetes-2018: diagnosis and drug; LPRS: drug only).
- All numbers are aggregates from the enclave's output block. Counts under 10 show as "<10"; a rate whose count, or the rest of the group, is under 10 shows as "suppressed". Status and note columns are the project team's reading of those numbers.
