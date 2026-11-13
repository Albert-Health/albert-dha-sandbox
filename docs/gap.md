# Açık işler, kararlar ve bilinen kısıtlar

Son güncelleme: 2026-11-13. Durum etiketleri: **[AÇIK]** yapılacak · **[KARAR BEKLİYOR]** medikal ekip /
danışman kararı · **[DIŞ]** DHA / NABIDH / DFF'ten bilgi · **[KISIT]** raporlanacak bilinen sınırlama.

## 1. Kod — kalan işler
| # | İş | Durum | Not |
|---|---|---|---|
| K1 | 100k sentetik veride uçtan uca çalıştırma (build → NB0 → NB1 → NB2 → KPI) | [AÇIK] | Mini veride geçti; 44k C3'te bootstrap süresi/bellek görülmedi |
| K2 | Eksik veri stratejisi: complete-case (mevcut) vs multiple imputation (QDiabetes orijinal yöntemi) | [AÇIK] + [KARAR BEKLİYOR] | Mini veride QDiabetes yalnızca %3 hastada hesaplanabiliyor; parametreli yapılmalı |
| K3 | NABIDH adapter MAPPING (`io/adapters/nabidh.py`) | [AÇIK] | Enclave'de dosya/sütun adları görülünce |
| K4 | Offline kurulum paketi (wheel'ler) | [AÇIK] + [DIŞ] | VM OS / Python sürümü bilinmiyor |
| K5 | LRS madde puanlarının Gray et al. 2010 birincil tablosuyla doğrulanması | [AÇIK] | Kategoriler NHS Health Check belgesiyle doğrulandı |
| K6 | Evidence package şablonlarının doldurulması (`docs/evidence_package/filled/`) | [AÇIK] + [KARAR BEKLİYOR] | Doldurulana kadar KPI "Not Met" → graduation ön değerlendirmesi "Do Not Graduate" |
| K7 | Adım 3 / UAE modeli (`notebooks/03_uae_model.py`) | Koşullu | Keşif–sınama ayrımı, tanı-öncesi tampon, girdi çiti (app'te sorulabilir, lab yok) |
| K8 | Sentetik veri üreticisi repoda yok | [KISIT] | 100k sentetik veri ekip içinde ayrı paylaşılıyor |

## 2. Medikal ekipten kararlar (config parametresiyle)
| # | Karar | Parametre | Varsayılan | Bağlam |
|---|---|---|---|---|
| D1 | Outcome washout (index sonrası N gün içindeki olay = prevalent, hasta çıkarılır) | `outcome_washout_days` | 0 (v2) | Sentetikte olayların %74'ü ≤30 gün; öneri 90 |
| D2 | Birincil horizon 5 y mı 3 y mı | `horizon_years`, `horizon_years_fallback` | 5 / 3 | Sentetikte takip medyanı 2,35 y; ≥5 y %20 |
| D3 | Prediktör penceresi (index öncesi; index sonrası ± gün) | `predictor_lookback_days` | 365 | v2 iki sürüm: 12 vs 24 ay. Sentetikte index'te BMI %37, sigara %21 |
| D4 | Eksik veri yaklaşımı | (K2 ile eklenecek) | complete-case | — |
| D5 | QDiabetes risk eşiği (sens/spec/PPV/alert rate) | `qd_risk_threshold_pct` | None | Yoksa ilgili KPI'lar "Pending" |
| D6 | Etnisite eşlemesi NABIDH → QDiabetes 9 kategori / LRS | `codelists` eşleme tabloları | Emirati, Gulf Arab, Arab → "Other" | Sentetikte "Other" eşlemesi tek başına ~2× düşük tahmin üretiyor |
| D7 | Yoğunluksuz "current" sigara kategorisi | `qd_smoking_current_category` | 3 (moderate) | Midwakh / shisha nasıl ele alınacak |
| D8 | Sigara kaydı yok = non-smoker mı | `qd_missing_smoking_as_non` | False | — |
| D9 | Kapsam dışı 7 Model A prediktörü = 0 (indirgenmiş model) | `qd_force_reduced_model` | True | Statin, steroid, atipik antipsikotik, şizofreni/bipolar, öğrenme güçlüğü, GDM, PCOS |
| D10 | Townsend = 0 | `qd_townsend` | 0.0 | UAE'de karşılığı yok |
| D11 | 5 y risk için baseline ölçekleme S0(t) = S0(10)^(t/10) | `qd_baseline_time_scaling` | "power" | Yayınlanmış kodda yalnız 10 y baseline var — ayrıca [KISIT] |
| D12 | LRS'de etnisite "Not recorded" → skor hesaplanmaz | `lrs_unknown_ethnicity_as_missing` | True | — |
| D13 | Recalibration bölme yöntemi | `recal_split` | "temporal" | Temporal test parçasında 5 y AUROC hesaplanamıyor (≥5 y takipli kontrol yok) |
| D14 | Başlangıçta prediyabet: hariç (v2) / duyarlılıkta dahil | (eklenecek) | hariç | QDiabetes geliştirme popülasyonuyla uyum |
| D15 | Outcome için doğrulayıcı ikinci test; random glukoz ≥200 ve yalnız E11 tanısı olay mı | (eklenecek) | tek test; ikisi de olay | ADA ikinci test ister |
| D16 | Gebelik dönemi lab'ları dışlansın mı | (eklenecek) | dışlanmıyor | GDM / O24 |
| D17 | Aile öyküsü kaydı yok = negatif mi (C1 tamlık) | `c1_require_fh_record` | False | — |
| D18 | KVH tanımı (I50 ve tüm I60–I69 dahil mi) | `codelists.DX["cvd"]` | geniş | QDiabetes: angina, MI, inme, TIA |
| D19 | Adım 3'ü tetikleyecek "yeterli performans" | (eklenecek) | — | Veriye bakmadan önce yazılmalı |
| D20 | Fairness alt grupları ve kabul edilebilir fark | (eklenecek) | cinsiyet, yaş bandı, etnisite | — |
| D21 | Kod listelerinin klinik onayı; model card klinik bölümleri | — | — | Evidence package (Critical KPI) için şart |

## 3. Dış taraflar
**DHA / NABIDH [DIŞ]:** veri sözlüğü ve dosya formatı; etnisite/uyruk kategori listesi; birimler;
C3'te cap/örneklem neden uygulandı ve tam eligible N; VM ortamı (OS, Python, pip, Jupyter);
enclave'den çıktı çıkarma kuralları (küçük hücre eşiği, figür onayı).

**DFF / Precoh [DIŞ]:** "Joint Completeness — QDiabetes"nin 8 çekirdek değişkenle yeniden tanımı;
AUROC 0.75'in tanımı (sansürlü veride horizon'da zaman-bağımlı); 4 TBD KPI slotu (önerimiz: skor
hesaplanabilirlik %, alt-grup kalibrasyon farkı, C1–C2 seçilim etkisi, Kol 1→2 kalibrasyon iyileşmesi);
evidence package kontrol listesi; iki haftalık rapor formatı.

**Belge tutarsızlıkları:** v2 lookback 12 vs 24 ay (NABIDH'e hangisi gitti); Study Flow'da sansür
"last recorded contact" → "son glisemik ölçüm" olmalı; Scope Özeti v0.1 güncel değil (LRS kapsamda,
Layer 2 koşullu).

## 4. Bilinen kısıtlar [KISIT]
- LRS kesitsel tespit skoru; C3'te incident benchmark'ı dış kullanımdır.
- C1/C2 yalnızca pozitif vaka içerir; buradan performans metriği çıkmaz.
- QDiabetes 5 y riski 10 y baseline'dan varsayımla türetiliyor (D11).
- İndirgenmiş Model A (D9) ve Townsend = 0 (D10) karşılaştırılabilirliği sınırlar.
- C3 iki glisemik ölçüm şartı daha sık test edilen (muhtemelen daha riskli) hastaları seçer.

## 5. Kararlar (verildikçe buraya)
| Tarih | Karar | Kim | Parametre / commit |
|---|---|---|---|
| — | — | — | — |
