_Exported from the live C2 report on 2026-11-20. Source: VM COPY block `logs/enclave/2026-11-20.log`, `run all` 20 Nov 2026 10:51 UTC, bundle 72efc39be6ba, ingest 1.4.2 (D36 hypertension rule; QDiabetes medians before D36 from the 09:56 block in the same file). Aggregates only; counts under 10 show as "<10". Data behind every table: [data/c2_report.json](data/c2_report.json)._

_DHA HEALTH DATA SANDBOX · PHASE 1 · COHORT C2_

# C2 End-of-Day Report

C2 is a random sample of the same known type 2 diabetes and prediabetes patients, with no completeness requirement: the realistic picture of NABIDH data. The question is still whether the pipeline works, not how good the scores are. Of **2,564** known positives, QDiabetes ran for **372** (**14.5%**). Smoking decides it: QDiabetes needs it, and it is missing for **85.1%** of C2. LPRS ran for **0**: it needs ethnicity, and ethnicity did not arrive. Positive family history is **19.6%** here, against **98.7%** in C1 (section 5). Scored with unknown ethnicity as White or as Other, LPRS runs for **94.5%** of C2 (BMI is the rest); what each score flags at each threshold is in section 6.

> From the enclave run of 20 November 2026, 10:51 UTC: bundle 72efc39be6ba, ingest 1.4.2, all four steps exit 0. Treated hypertension follows decision D36 (diagnosis or drug, for QDiabetes and LPRS).

## 1 · Can the scores run?

From delivered patients to patients each score was produced for. The other colour is the same run with ethnicity read from the NABIDH EthnicGroup field instead of nationality, from NB1's ethnicity source comparison.

| Step | Patients | % of known positives | Run |
|---|---|---|---|
| Patients delivered (Patient view) | 2,600 | — | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| Known positives (T2DM or prediabetes evidence) | 2,564 | 100.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| QDiabetes computable | 372 | 14.5% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| 7 core variables complete (all but ethnicity) | 372 | 14.5% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · ethnicity from nationality (default) | 0 | 0.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · unknown ethnicity scored as White or Other (scenario) | 2,422 | 94.5% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| LPRS computable · NABIDH EthnicGroup field | 237 | 9.2% | Same run · ethnicity from the NABIDH EthnicGroup field (NB1 comparison) |
| All 8 core variables · nationality (default) | 0 | 0.0% | Run all · 20 Nov 10:51 UTC · ingest 1.4.2 |
| All 8 core variables · NABIDH EthnicGroup field | 31 | 1.2% | Same run · ethnicity from the NABIDH EthnicGroup field (NB1 comparison) |

### Each score input: how it is mapped, and what went wrong

| Input | Score | Mapping | Issue | Value | Unit | Status |
|---|---|---|---|---|---|---|
| Age band | QDiabetes 25–84 | Patient.Age (no date of birth) | Outside 25–84: score not computed | 0 | patients | Works |
| Age band | LPRS 40–75 | Patient.Age | Outside the LPRS development band (scored, flagged) | 23.1 | % of C2 | Works |
| Ethnicity | QDiabetes | Unknown → reference group 'White or not stated' | Fixed for every patient: no nationality column; risk may be underestimated for higher-risk groups | 2,564 | patients | Fixed value |
| Ethnicity | LPRS | White vs other, from nationality (default) | Not computable: ethnicity unknown | 2,564 | patients | Blocked |
| Ethnicity | LPRS | White vs other, from the NABIDH EthnicGroup field | Still unknown for most patients | 2,298 | patients | Blocked |
| Treated hypertension | QDiabetes, LPRS | ICD-10 I10–I16 diagnosis OR an antihypertensive drug (DDC → ingredient → ATC C02/C03/C07/C08/C09); decision D36 | Counted as treated: diagnosis, drug, or both | 49.6 | % of C2 | Works |
| Treated hypertension | QDiabetes | Published QDiabetes-2018 definition: diagnosis AND drug | Counted now, not under the published definition (diagnosis only + drug only) | 16.2 | % of C2 | Decision D36 |
| Treated hypertension | LPRS | Published LPRS (Gray 2012) definition: drug only | Counted now, not under the published definition (diagnosis only) | 12.8 | % of C2 | Decision D36 |
| Smoking level | QDiabetes | Never / Low / Medium / High → never / light / moderate / heavy; Occasional → light (temporary, D7) | Smoking status missing: QDiabetes not computed | 2,183 | patients | Works |
| Smoking level | QDiabetes | Ex-smoker: no such value in SocialHistory; only from diagnosis code Z87.891 | QDiabetes 'ex-smoker' category is practically empty | <10 | patients | Gap |
| Smoking level | QDiabetes | 'Other' (may be shisha / midwakh) | Not mapped, decision D7 | 306 | rows | Decision pending |
| BMI | QDiabetes, LPRS | Observation 39156-5, else height 8302-2 + weight 3141-9, else Z68 band | BMI missing | 140 | patients | Works |
| Sex | QDiabetes, LPRS | Patient.Gender_Code M / F | Not male / female ('U') | <10 | patients | Works |
| Family history of diabetes | QDiabetes, LPRS | FamilyHistory (SNOMED / ICD-10 / text) first-degree + Z83.3; present / absent | Share with a positive first-degree family history (C1: far higher, section 5) | 19.6 | % of C2 | Works |
| Cardiovascular disease | QDiabetes | ICD-10 I20–I25, I50, I6x, G45; present / absent | Share with a CVD diagnosis | 16.9 | % of C2 | Works |

> For present / absent inputs (family history, cardiovascular disease, hypertension) the value is the share of C2 with the condition, not a completeness figure.

### Treated hypertension: diagnosis, drug, or both

| C2 patients with | Patients | % | Counted as treated by |
|---|---|---|---|
| Diagnosis and medication | 856 | 33.4 | QDiabetes, LPRS, LRA 2010 |
| Diagnosis only | 328 | 12.8 | QDiabetes, LPRS, LRA 2010 |
| Medication only | 88 | 3.4 | QDiabetes, LPRS, LRA 2010 |
| Neither | 1,292 | 50.4 | none |

> Decision D36 (20 November): QDiabetes and LPRS count a hypertension diagnosis or an antihypertensive drug. The published definitions are narrower: QDiabetes-2018 needs both, LPRS (Gray 2012) the drug only. Both stay available as sensitivity runs. LRA 2010 is the older Leicester assessment, for reference.

### Smoking level as QDiabetes reads it

| Level | Recorded as | Patients | % | From a diagnosis code |
|---|---|---|---|---|
| Never | never | 318 | 12.4 | 0 |
| Ex-smoker | ex | <10 | suppressed (<10) | <10 |
| Light | light | 26 | 1.0 | 0 |
| Moderate | moderate | 11 | 0.4 | 0 |
| Moderate | current, intensity not recorded (D7 → moderate) | <10 | suppressed (<10) | <10 |
| Heavy | heavy | 11 | 0.4 | 0 |
| Missing | no smoking record | 1,248 | 48.7 | 0 |
| Missing | records present, none usable (unknown / unmapped, e.g. other) | 927 | 36.2 | 0 |
| Missing | undated records disagree (D28) | <10 | suppressed (<10) | 0 |

> SocialHistory has no ex-smoker value, so that level comes only from a diagnosis code. "Current, intensity not recorded" is set to moderate (decision D7).

### QDiabetes 10-year risk in C2 (median): what D36 changed

| Group | Diagnosis and drug (09:56 run) | Diagnosis or drug (D36, from 10:25) | Change, points |
|---|---|---|---|
| Prediabetes | 2.63% | 2.97% | +0.34 |
| T2DM | 6.07% | 6.41% | +0.34 |

> Same data, same patients; only the hypertension rule differs. The **16.2%** of C2 with a diagnosis or a drug alone now get the hypertension term, so their risk rises. Risk is shown to describe the pipeline, not to judge the score: C2 holds known positives only.

## 2 · Data Completeness (KPI, target ≥ 90%, owner DHA)

C2 has no completeness requirement, so this is how full the data really is: which variables are missing, and which are filled but not usable.

| KPI | Target | Actual (today's KPI run) | Status | What it means for C2 |
|---|---|---|---|---|
| Data Completeness for Required Variables | >= 90% | C1 0.0%; C2 0.0% | Not Met | C2 is a random sample: the realistic picture of how full NABIDH data is |

The KPI takes the weakest of the 8 core variables. Ethnicity is 0%, so the KPI is 0%. Without ethnicity the weakest is smoking at **14.9%**, and all 7 other variables are complete together for **14.5%** of C2.

### Completeness by variable

| Variable | Measured as | Patients | With a usable value | % | ≥ 90% | What is counted |
|---|---|---|---|---|---|---|
| Sex | Recorded value | 2,564 | suppressed (<10 missing) | suppressed (<10) | Yes | a value in the record |
| Age | Recorded value | 2,564 | 2,564 | 100.0 | Yes | a value in the record |
| Ethnicity | Recorded value | 2,564 | 0 | 0.0 | No | a value in the record |
| BMI | Recorded value | 2,564 | 2,424 | 94.5 | Yes | a value in the record |
| Smoking | Recorded value | 2,564 | 381 | 14.9 | No | a value in the record |
| Family history of diabetes | Present / absent | 2,564 | 2,564 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 19.6% of C2 |
| Family history: a record exists | Recorded value | 2,564 | 507 | 19.8 | No | FamilyHistory record (positive / negative / other relative) or Z83.3 |
| Cardiovascular disease | Present / absent | 2,564 | 2,564 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 17.2% of C2 |
| Treated hypertension | Present / absent | 2,564 | 2,564 | 100.0 | Not tested (yes / no variable) | Yes or no for every patient; no record counts as no. Yes for 49.6% of C2 (diagnosis or drug, D36) |

> Family history, cardiovascular disease and hypertension are present / absent: a patient with no record of the condition is counted as not having it. Every patient therefore has a value (yes or no), so these rows are 100% by construction and say nothing about how full the data is; the ≥ 90% test does not apply to them. "A record exists" shows how many patients have any family history record. "With a usable value" counts patients who have the variable; the rest are missing it (for smoking, see the smoking level table in section 1 for why). Where fewer than 10 patients are missing a value, the count and the rate are both hidden.

### Completeness per score: the inputs each score reads

#### QDiabetes (reduced Model A)

| Input | Needed as | With a usable value | % |
|---|---|---|---|
| Sex | Required | suppressed (<10 missing) | suppressed (<10) |
| Age (25–84) | Required | 2,564 | 100.0 |
| Ethnicity | Not required: unknown → reference group | 0 | 0.0 |
| BMI | Required | 2,424 | 94.5 |
| Smoking | Required | 381 | 14.9 |
| Family history of diabetes | Present / absent: 100% by definition | 2,564 | 100.0 |
| Cardiovascular disease | Present / absent: 100% by definition | 2,564 | 100.0 |
| Treated hypertension (diagnosis or drug, D36) | Present / absent: 100% by definition | 2,564 | 100.0 |
| All inputs, ethnicity as reference group = score computed | Joint | 372 | 14.5 |
| All inputs, ethnicity required (KPI 'Joint Completeness – QDiabetes') | Joint | 0 | 0.0 |

#### LPRS (Leicester Practice Risk Score, no waist)

| Input | Needed as | With a usable value | % |
|---|---|---|---|
| Age | Required | 2,564 | 100.0 |
| Sex | Required | suppressed (<10 missing) | suppressed (<10) |
| Ethnicity · nationality (default) | Required | 0 | 0.0 |
| Ethnicity · NABIDH EthnicGroup field | Required | 266 | 10.4 |
| BMI | Required | 2,424 | 94.5 |
| Family history of diabetes | Present / absent: 100% by definition | 2,564 | 100.0 |
| Hypertension (diagnosis or drug, D36) | Present / absent: 100% by definition | 2,564 | 100.0 |
| All inputs · ethnicity from nationality = score computed (KPI 'Joint Completeness – LRS') | Joint | 0 | 0.0 |
| All inputs · ethnicity from the EthnicGroup field | Joint | 237 | 9.2 |

> The two scores read different inputs, so their completeness differs. QDiabetes runs without ethnicity: an unknown ethnicity takes its reference group, so **14.5%** of C2 is scored: smoking is what is missing. The KPI "Joint Completeness – QDiabetes" requires ethnicity as well, so it reads 0%. LPRS needs ethnicity and has no reference group, so it is scored for nobody with nationality and for **9.2%** with the EthnicGroup field. Whether ethnicity should count for QDiabetes completeness is part of decision D32.

### Filled but not usable

| What | Variable | Rows | Handling |
|---|---|---|---|
| Vital rows with an empty value | BMI / height / weight | 1,107 | Dropped and counted |
| Vital rows with a placeholder ('0' or '-') | BMI / height / weight | 2,441 | Dropped and counted |
| Smoking rows 'Other' | Smoking | 306 | Not mapped (decision D7) |
| Smoking records present, none usable | Smoking | 927 | Counted as missing |
| Undated smoking records that disagree | Smoking | <10 | Counted as missing (D28) |
| Lab results that are not numbers | HbA1c / glucose | 10 | Dropped and counted |
| Diagnoses without a date | CVD / hypertension | 36 | Dropped and counted |
| Diagnoses dated exactly 1970-01-01 | Diagnoses | 0 | Counted, kept (decision D31) |
| Medications without a date | Hypertension treatment | <10 | Dropped and counted |
| Sex 'U' | Sex | <10 | Score not computed |

### Patients a score could not be produced for

| Score | Missing input | Patients | % |
|---|---|---|---|
| QDiabetes | Smoking status | 2,183 | 85.1 |
| QDiabetes | BMI | 140 | 5.5 |
| QDiabetes | Sex not male / female | <10 | suppressed (<10) |
| LPRS | Ethnicity | 2,564 | 100.0 |
| LPRS | BMI | 140 | 5.5 |
| LPRS | Sex not male / female | <10 | suppressed (<10) |

### Joint completeness by group and ethnicity source

| Ethnicity source | Group | Patients | 7 core | % | 8 core | % | LPRS inputs | % |
|---|---|---|---|---|---|---|---|---|
| Nationality (default) | All | 2,564 | 372 | 14.5 | 0 | 0.0 | 0 | 0.0 |
| Nationality (default) | Prediabetes | 1,162 | 211 | 18.2 | 0 | 0.0 | 0 | 0.0 |
| Nationality (default) | T2DM | 1,402 | 161 | 11.5 | 0 | 0.0 | 0 | 0.0 |
| NABIDH EthnicGroup field | All | 2,564 | 372 | 14.5 | 31 | 1.2 | 237 | 9.2 |

> Joint completeness is the share of patients who have every variable in a set at the same time, not one by one. Each variable can be nearly full on its own while the set is not, because the gaps fall on different patients, and one variable that never arrived (ethnicity) takes the whole set to 0%. 7 core: all but ethnicity, what QDiabetes needs here (ethnicity is fixed at its reference group). 8 core: all eight. LPRS inputs: age, sex, ethnicity, BMI, family history, hypertension. Per score, input by input: see "Completeness per score" above.

## 3 · Applicant Data Requirement Framework Match (Universal KPI)

Did the 8 requested variables arrive, and in the requested form? The KPI is now read variable by variable, and it is Partial. Ethnicity arrived only as the EthnicGroup field, filled for few patients, because nationality is not in the view. Drugs arrived as Dubai Drug Codes, so treated hypertension is derived, not delivered as ATC. Part of family history is recognised from text, not from a code. SocialHistory has no ex-smoker value.

| KPI | Target | Actual (today's KPI run) | Status | What it means for C2 |
|---|---|---|---|---|
| Applicant Data Requirement Framework Match | Match | Partial: ethnicity, smoking, family_history, hypertension | Partial | Did the 8 variables arrive, and in the requested form |

| Variable | Arrived as (view.column) | Route | Patients with a value | % | Match | Why not a full match |
|---|---|---|---|---|---|---|
| Sex | Patient.Gender_Code | As requested | suppressed (<10 missing) | suppressed (<10) | Match | — |
| Age | Patient.Age | As requested | 2,600 | 100.0 | Match | — |
| Ethnicity | Patient.Nationality \| Patient.EthnicGroup_Description | Substitute field | 267 | 10.3 | Partial | requested nationality not delivered; only ethnicity_raw has values; values for only 10.3% of patients (< 50%) |
| BMI | Observation.ObservationValue (LOINC 39156-5 BMI; 8302-2 height + 3141-9 weight) | As requested | 2,431 | 93.5 | Match | — |
| Smoking | SocialHistory.SocialHabitQty_Description | As requested | 381 | 14.7 | Partial | level seen in < 10 patients: ex; values for only 14.7% of patients (< 50%) |
| Family history of diabetes | FamilyHistory.Diagnosis_Code | Derived by the adapter | 508 | 19.5 | Partial | 62% of the records not in the requested system (ICD-10 / SNOMED code); values for only 19.5% of patients (< 50%) |
| Cardiovascular disease | Diagnosis.Diagnosis_Code | As requested | 440 | 16.9 | Match | — |
| Treated hypertension | Diagnosis.Diagnosis_Code + Medication.DrugProduct_Code | Derived by the adapter | 1,272 | 48.9 | Partial | drug: 100% of the rows not in the requested system (ATC) |

> From NB0 (nb00/framework_variables.csv). Partial means the variable arrived, but not as requested: a substitute field, a missing level, more than 5% of records in another code system, or values for fewer than 50% of patients. These two thresholds are the developer's proposal and wait for the medical team (decisions D29, D30). For CVD and hypertension the share is of patients with the condition.

## 4 · Data quality

### Ranges and units, after cleaning

| Measure | Unit | Patients | p5 | Median | p95 | Plausible range | Rows outside | Patients affected | Note |
|---|---|---|---|---|---|---|---|---|---|
| BMI | kg/m² | 301 | 21 | 27 | 38 | 12–80 | 14 | 13 | A value outside 12–80 is taken as an entry error and skipped. The patient's latest value inside the range is used; if there is none, BMI is computed from height and weight, then taken from a Z68 code |
| Height | cm | 2,435 | 151 | 165 | 182 | 120–230 | 384 | 182 | Mostly below 120 cm (376 rows), skipped; 42 rows given in metres, converted. Latest value inside the range from the full history goes into BMI |
| Weight | kg | 2,484 | 55 | 78 | 112 | 25–350 | 211 | 94 | A value outside 25–350 is skipped; the latest value inside the range goes into BMI from height and weight |
| HbA1c (4548-4) | % | 208 | 5.0 | 5.8 | 8.7 | — | — | — | Unit %, no mmol/mol seen |
| Fasting glucose (1558-6) | mg/dL | 727 | 81.1 | 101 | 181 | — | — | — | Unit mg/dL; 209 rows spelled MG/DL normalised |

> Plausible range: the values an adult measurement can realistically take, ends included: BMI 12–80 kg/m², height 120–230 cm, weight 25–350 kg, waist 40–250 cm. A value outside it is treated as an entry error (for example a unit mix-up or a test value; heights given in metres are converted to cm first) and is not used; the row stays in the data and is counted here. "Rows outside" counts such rows; "Patients affected" counts patients with at least one. The ranges are set in the code in one place (`phenotype.VITAL_PLAUSIBLE_RANGE`) and are the developer's choice, not a clinical decision yet.

> HbA1c and fasting glucose are eligibility and outcome evidence only; lab values are never score inputs.

### Coding systems

| Field | Expected | Arrived | Count | Of | Usable |
|---|---|---|---|---|---|
| Diagnosis_Code | ICD-10 | ICD-10-CM with dots (E11.9, R73.03, I10) | 89 | cells with 2 codes, split | Yes |
| Diagnosis_Code | ICD-10 | Trailing dot | <10 | codes cleaned | Yes |
| LabResultItem.TestItemCode_Code | LOINC | LOINC 1558-6, 4548-4, 1521-4 | — | — | Yes |
| Observation.ObservationCode_Code | LOINC | LOINC 39156-5, 8302-2, 3141-9 only | — | — | Yes |
| Medication.DrugProduct_Code | INN / ATC | DDC product code (Dubai Drug Code) | 21,217 | rows | Mapped: DDC → ingredient (INN) → ATC |
| Medication.DrugProduct_Code | INN / ATC | DDC scientific code | 3,109 | rows | Mapped |
| Medication.DrugProduct_Code | INN / ATC | 6-digit DDC stem | 139 | rows | Mapped |
| Medication.DrugProduct_Code | INN / ATC | VMP<id>,<dose>,<form> (no reference list) | 122 | rows | By drug name |
| Medication.DrugProduct_Code | INN / ATC | No code | 35 | rows | By drug name |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | SNOMED | 223 | rows | Yes |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | ICD-10 | 33 | rows | Yes |
| FamilyHistory.Diagnosis_Code | SNOMED / ICD-10 | Text only (local codes) | 424 | rows | By description text |

## 5 · How C2 differs from C1 (selection effect)

C2 is the random sample; C1 the complete-case extract of the same positives. The standardised mean difference (SMD) shows how far apart they are; above 0.1 counts as an imbalance. Read from C2, the outlier is C1: almost every C1 patient has a positive family history of diabetes, against about one in five here. C2 is the better guide to what an unselected NABIDH population looks like; its scores are less inflated by family history, but most of it cannot be scored yet because smoking is missing. C2 is also more male, older, and has fewer current smokers recorded.

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

Every C2 patient is a known positive (type 2 diabetes or prediabetes), so the one thing a score can be checked on here is how many of them it flags as high risk: sensitivity. A score's threshold is not decided yet (D5 for QDiabetes, D23 for LPRS), so sensitivity is shown at a range of thresholds. LPRS needs ethnicity, which did not arrive, so it is scored twice: every unknown ethnicity taken as White, then as Other. The truth lies between the two.

> **Why there is no specificity, PPV, F1 or AUROC here.** These need patients without diabetes: how many of them the score wrongly flags. C1 and C2 hold only patients with diabetes or prediabetes, so there are none, and any such figure would be invented. They come from C3 in Phase 2, where patients start without diabetes and some develop it.

### LPRS with unknown ethnicity scored as White, then as Other

| Unknown ethnicity scored as | Patients | Scored | % | Median score | p25 | p75 |
|---|---|---|---|---|---|---|
| White | 2,564 | 2,422 | 94.5 | 4.79 | 4.24 | 5.38 |
| Other | 2,564 | 2,422 | 94.5 | 5.54 | 5.00 | 6.13 |

> "Other" adds the LPRS ethnicity term (0.757) for every patient whose ethnicity is unknown, so its scores are higher by that amount. Patients not scored here are missing BMI or sex, not ethnicity. Known ethnicity (none with nationality) is kept as it is.

#### QDiabetes: share flagged at each 10-year risk threshold

> Chart in the live report; the same values are in the table below.

#### LPRS: share flagged at each score threshold

> Chart in the live report; the same values are in the table below.

### All thresholds, with 95% confidence intervals

| Score | Flagged when | Scored | Flagged | Sensitivity % | 95% CI low | 95% CI high |
|---|---|---|---|---|---|---|
| QDiabetes | 10-year risk ≥ 1% | 372 | 323 | 86.8 | 83.0 | 89.9 |
| QDiabetes | 10-year risk ≥ 2.5% | 372 | 246 | 66.1 | 61.2 | 70.8 |
| QDiabetes | 10-year risk ≥ 5% | 372 | 164 | 44.1 | 39.1 | 49.2 |
| QDiabetes | 10-year risk ≥ 7.5% | 372 | 122 | 32.8 | 28.2 | 37.7 |
| QDiabetes | 10-year risk ≥ 10% | 372 | 88 | 23.7 | 19.6 | 28.2 |
| QDiabetes | 10-year risk ≥ 15% | 372 | 49 | 13.2 | 10.1 | 17.0 |
| QDiabetes | 10-year risk ≥ 20% | 372 | 30 | 8.1 | 5.7 | 11.3 |
| LPRS · unknown ethnicity as White | score ≥ 4 | 2,422 | 2,054 | 84.8 | 83.3 | 86.2 |
| LPRS · unknown ethnicity as White | score ≥ 4.5 | 2,422 | 1,547 | 63.9 | 61.9 | 65.8 |
| LPRS · unknown ethnicity as White | score ≥ 5 | 2,422 | 987 | 40.8 | 38.8 | 42.7 |
| LPRS · unknown ethnicity as White | score ≥ 5.5 | 2,422 | 511 | 21.1 | 19.5 | 22.8 |
| LPRS · unknown ethnicity as White | score ≥ 6 | 2,422 | 203 | 8.4 | 7.3 | 9.6 |
| LPRS · unknown ethnicity as White | score ≥ 6.5 | 2,422 | 73 | 3.0 | 2.4 | 3.8 |
| LPRS · unknown ethnicity as White | score ≥ 7 | 2,422 | 18 | 0.7 | 0.5 | 1.2 |
| LPRS · unknown ethnicity as White | score ≥ 7.5 | 2,422 | <10 | suppressed (<10) | suppressed (<10) | suppressed (<10) |
| LPRS · unknown ethnicity as Other | score ≥ 4 | 2,422 | 2,396 | 98.9 | 98.4 | 99.3 |
| LPRS · unknown ethnicity as Other | score ≥ 4.5 | 2,422 | 2,237 | 92.4 | 91.2 | 93.4 |
| LPRS · unknown ethnicity as Other | score ≥ 5 | 2,422 | 1,816 | 75.0 | 73.2 | 76.7 |
| LPRS · unknown ethnicity as Other | score ≥ 5.5 | 2,422 | 1,262 | 52.1 | 50.1 | 54.1 |
| LPRS · unknown ethnicity as Other | score ≥ 6 | 2,422 | 734 | 30.3 | 28.5 | 32.2 |
| LPRS · unknown ethnicity as Other | score ≥ 6.5 | 2,422 | 338 | 14.0 | 12.6 | 15.4 |
| LPRS · unknown ethnicity as Other | score ≥ 7 | 2,422 | 123 | 5.1 | 4.3 | 6.0 |
| LPRS · unknown ethnicity as Other | score ≥ 7.5 | 2,422 | 33 | 1.4 | 1.0 | 1.9 |

> Sensitivity = flagged / scored, with the Wilson 95% interval. Reference date: the end of the data. Where the flagged count, or the rest, is under 10, the rate is hidden. These are prevalent cases scored on their current record, not a prospective test.

## 7 · Process KPIs, and what C2 does not measure

### Critical process KPIs (measured over the whole sandbox, not from data)

| KPI | Target | Actual | Status | Note |
|---|---|---|---|---|
| Audit Trail Completeness | 100% | 100.0% (96/96 runs) | Met | Closed after the fact as abandoned (run_end appended, D34): 20261119T054135Z_nb00_data_profile_b068d0 |
| Evidence Package Completeness | Complete | — | Pending | — |
| Data Security / No-Incident | 0 incidents | 0 incidents | Met | — |

### Performance KPIs: not measured in C2 (Phase 2, C3)

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
- From DHA: a nationality field, a facility field (none is mapped, so facility representation cannot be shown), and what "Unknown" and "Other" mean in SocialHistory (927 C2 patients have only those).
- Which row of section 6 is "the" detection rate depends on a threshold for each score (D5 for QDiabetes, D23 for LPRS) and, for LPRS, on the ethnicity source (D6).

## Definitions

- Known positive: a C2 patient with type 2 diabetes or prediabetes evidence (diagnosis, HbA1c, fasting glucose or a diabetes drug).
- The 8 core variables: sex, age, ethnicity, BMI, smoking, family history of diabetes, cardiovascular disease, treated hypertension.
- Family history of diabetes: from the NABIDH FamilyHistory view and the patient's own Z83.3 diagnosis. A record counts as diabetes by its code (ICD-10 E08–E14 or Z83.3; SNOMED 160303001, 73211009, 44054006, 46635009) or, when the code is a local number or text, by its description ("diabet", "DM"); prediabetes records and other conditions are left out. There is no yes / no column, so a diabetes record is positive unless its text negates it ("No history of …", "denies"). Father, mother, brother, sister, child or parent is first degree; aunts, uncles, grandparents and cousins are recorded but not counted positive. A patient is positive with any first-degree positive record, whatever its date (D27), or with Z83.3.
- QDiabetes-2018 Model A without lab values, on the 8 core variables (reduced model, decision D9). LPRS is the Leicester Practice Risk Score (Gray 2012), without waist circumference.
- Open decisions: see the Decision Pack linked above. D5 / D23 score thresholds are only needed for a single detection rate and in Phase 2.
- Treated hypertension (D36): a hypertension diagnosis or an antihypertensive drug counts, for QDiabetes and LPRS. This departs from both published definitions (QDiabetes-2018: diagnosis and drug; LPRS: drug only).
- All numbers are aggregates from the enclave's output block. Counts under 10 show as "<10"; a rate whose count, or the rest of the group, is under 10 shows as "suppressed". Status and note columns are the project team's reading of those numbers.
