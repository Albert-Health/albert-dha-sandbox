# Kohort Türetme Dokümanı

> Kod tek doğruluk kaynağıdır: `src/sandbox/cohorts.py`, `src/sandbox/phenotype.py`, `src/sandbox/codelists.py`,
> parametreler `src/sandbox/config.py` (her run'ın `run_manifest.json` dosyasında anlık görüntü).

## 1. Pozitif havuz (C1 / C2) — Interim Data Assessment
- T2DM: E11.x / SNOMED 44054006 veya HbA1c ≥6.5 / FPG ≥126 / OGTT ≥200 (her zaman)
- Prediyabet: R73.x veya HbA1c 5.7–6.4 / FPG 100–125 / OGTT 140–199; T1D (E10) hariç; A10 tek başına statü belirlemez
- C1: 8 çekirdek değişken dolu (FH/KVH/HT var-yok), cap {{c1_cap}} · C2: rastgele, cap {{c2_cap}}, seed {{seed}}

## 2. C3 — Non-Diabetic Cohort Spec v2
| Adım | Kural | N |
|---|---|---|
| 1 | Normal HbA1c (<5.7) veya FPG (<100) | {{with_normal_hba1c_or_fpg}} |
| 2 | T1D hiç yok | {{after_t1d_exclusion}} |
| 3 | Index'te/öncesinde DM, prediyabet, A10 yok | {{after_prevalent_dm_pre_exclusion}} |
| 4 | Index'te 25–84 yaş | {{after_age_25_84}} |
| 5 | Index sonrası ≥1 glisemik ölçüm | {{after_followup_measurement}} |
| 6 | Washout ({{outcome_washout_days}} gün) | {{after_outcome_washout}} |
[nb02/c3_funnel.json]

- Outcome: ilk DM lab / random glukoz ≥200 / E11 tanısı (ilaç-tek → duyarlılık); aynı gün öncelik lab > tanı > ilaç
- Sansür: son glisemik ölçüm · Prediktör penceresi: index öncesi {{predictor_lookback_days}} gün (tanılar tüm geçmiş)

## 3. Kod listeleri
`src/sandbox/codelists.py` — klinik onay: {{codelist_signoff}}
