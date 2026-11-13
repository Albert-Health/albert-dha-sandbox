# Validasyon Raporu — Adım 3 (C3 benchmark)

> Şablon. Kaynak: NB2 çalıştırması {{nb02_run_id}}.

## 1. Tasarım
- Kohort: Non-Diabetic Cohort Spec v2 · index = ilk normal HbA1c/FPG · sansür = son glisemik ölçüm
- Horizon: {{horizon_years}} y (yedek {{fallback_years}} y) · washout {{washout_days}} gün
- Recalibration ayrımı: {{recal_split}} ({{recal_train_frac}} eğitim)  [nb02/recal_split.csv]

## 2. Metodlar
Harrell C; zaman-bağımlı AUROC (cumulative/dynamic, IPCW); KM-tabanlı O:E ve kalibrasyon ondalıkları;
kalibrasyon eğimi (Cox, cloglog tahmin); IPCW eşik metrikleri; yüzdelik bootstrap ({{bootstrap_reps}} tekrar).

## 3. Sonuçlar
- Genel performans  [nb02/performance.csv]
- Kalibrasyon grafiği  [nb02/calibration_plot.png, nb02/calibration_tables.csv]
- Alt gruplar  [nb02/subgroups.csv]
- KPI tablosu  [kpi/kpi_table.csv]

## 4. Yorum (KLİNİK — medikal ekip)
- Kol 1 vs Kol 2: sorun seviye mi (recalibration toparlıyor) yoksa yapısal mı (C-index düşük kalıyor)?
- Adım 4 (UAE modeli) tetikleyici eşiği: {{step4_trigger}} → karar: {{step4_decision}}

## 5. Duyarlılık analizleri
Washout 0/90/180, horizon 5/3 y, medication-only outcome, WHO 2006 IFG, FH'siz skor  [SANDBOX_PARAMS ile tekrar edilen NB2 run'ları]
