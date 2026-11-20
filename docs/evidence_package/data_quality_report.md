# Veri Kalite Raporu — NABIDH extract (C1 / C2 / C3)

> Şablon. Kaynak: NB0 {{nb00_run_id}}, NB1 {{nb01_run_id}}.

## 1. Teslim ve şema
- Dosyalar, satır/hasta sayıları, tarih aralıkları  [nb00/volume.csv]
- Şema doğrulama (hata / uyarı; yer tutucu tarihler 1970-01-01 / 1900-01-01 sayılır, atılmaz)  [nb00/schema_validation.csv]
- Vital değerleri makul aralık dışında (BMI, boy, kilo, bel; kullanılmayan satır / hasta)  [nb00/vital_plausibility.csv]
- İstenen vs gelen kodlar (Framework Match)  [nb00/framework_match.csv, nb00/unmapped_codes.csv]

## 2. Tamlık
- Değişken bazında (kohort, T2DM vs prediyabet)  [nb00/core_variable_completeness.csv, nb01/completeness_by_variable.csv]
- Birlikte tamlık (8 çekirdek, LRS)  [nb00/joint_completeness.csv, nb01/joint_completeness.csv]
- BMI ve sigara kaynağı  [nb00/bmi_source.csv, nb00/smoking_source.csv]
- Tedavi edilen hipertansiyon (yalnız tanı / yalnız ilaç / ikisi / hiçbiri; skorların "treated" saydığı küme) ve
  QDiabetes sigara seviyesi  [nb01/htn_derivation.csv, nb01/smoking_level.csv]

## 3. Temsil ve seçilim
- Demografi, etnisite  [nb00/demographics.csv, nb00/ethnicity_categories.csv]
- Tesis temsili  [nb00/facility_representation.csv]
- C1 (tam kayıt) vs C2 (rastgele) seçilim etkisi  [nb01/selection_effect_smd.csv]

## 4. C3 takip yapısı
- Takip süresi, olay kanıt tipleri, olaya kadar geçen gün, washout duyarlılığı
  [nb00/c3_followup_summary.csv, nb00/c3_incident_evidence.csv, nb00/c3_days_to_event.csv, nb00/c3_washout_sensitivity.csv]

## 5. Bulgular ve DHA'ya geri bildirim
{{findings}}
