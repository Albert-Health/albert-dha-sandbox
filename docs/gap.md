# Açık işler, kararlar ve bilinen kısıtlar

Son güncelleme: 2026-11-14. Durum etiketleri: **[AÇIK]** yapılacak · **[KARAR BEKLİYOR]** medikal ekip /
danışman kararı · **[DIŞ]** DHA / NABIDH / DFF'ten bilgi · **[KISIT]** raporlanacak bilinen sınırlama.

## 1. Kod — kalan işler
| # | İş | Durum | Not |
|---|---|---|---|
| K1 | 100k sentetik veride uçtan uca çalıştırma (build → NB0 → NB1 → NB2 → KPI) | [AÇIK] | Mini veride geçti; 44k C3'te bootstrap süresi/bellek görülmedi |
| K2 | Eksik veri stratejisi: complete-case (mevcut) vs multiple imputation (QDiabetes orijinal yöntemi) | [AÇIK] + [KARAR BEKLİYOR] | Mini veride QDiabetes yalnızca %3 hastada hesaplanabiliyor; parametreli yapılmalı |
| K3 | NABIDH adapter MAPPING (`io/adapters/nabidh.py`) | [AÇIK] | Enclave'de dosya/sütun adları görülünce |
| K4 | Offline kurulum paketi (wheel'ler) | [AÇIK] + [DIŞ] | VM OS / Python sürümü bilinmiyor |
| K5 | Leicester katsayı / puanlarının birincil makalelerle teyidi | [AÇIK] | **LPRS (varsayılan, K-LRS):** katsayılar ilk yazarın (L. J. Gray) Leicester Diabetes Centre sunumundaki formülden alındı (Diabetologia 2012;55(4):959–66'ya atıflı); makale tam metni paywall'da — tablo/ekle karşılaştırılmalı. **LRA 2010** (artık yalnız karşılaştırma): madde puanları birincil tablodan teyit; kategoriler NHS Health Check belgesiyle doğrulandı |
| K6 | Evidence package şablonlarının doldurulması (`docs/evidence_package/filled/`) | [AÇIK] + [KARAR BEKLİYOR] | Doldurulana kadar KPI "Not Met" → graduation ön değerlendirmesi "Do Not Graduate" |
| K7 | Adım 3 / UAE modeli (`notebooks/03_uae_model.py`) = Study Flow 4. basamak | Koşullu | Yürütülürse NABIDH'ten yeni veri teslimi istenir. Keşif–sınama ayrımı, tanı-öncesi tampon, girdi çiti (app'te sorulabilir, lab yok); tüm popülasyona uygulanabilir olmalı |
| K8 | Sentetik veri üreticisi repoda yok | [KISIT] | 100k sentetik veri ekip içinde ayrı paylaşılıyor |

## 2. Medikal ekipten kararlar (config parametresiyle)
| # | Karar | Parametre | Varsayılan | Bağlam |
|---|---|---|---|---|
| D1 | Outcome washout (index sonrası N gün içindeki olay = prevalent, hasta çıkarılır) | `outcome_washout_days` | **90 [KARAR]** (v2: 0 → duyarlılık) | Sentetikte olayların %74'ü ≤30 gün |
| D2 | Birincil horizon 5 y mı 3 y mı | `horizon_years`, `horizon_years_fallback` | **3 / 5 [KARAR — şimdilik]** | Ayrıntılı bakılacak. Sentetikte takip medyanı 2,35 y; ≥5 y %20 |
| D3 | Prediktör penceresi (index öncesi; index sonrası ± gün) | `predictor_lookback_days` | **365 [KARAR]**; 730 duyarlılık | v2 iki sürüm: 12 vs 24 ay. Sentetikte index'te BMI %37, sigara %21 |
| D4 | Eksik veri yaklaşımı | (K2 ile eklenecek) | complete-case | Parametre türüne göre değişecek [KARAR — ayrıntı açık] |
| D5 | QDiabetes risk eşiği (sens/spec/PPV/alert rate) | `qd_risk_threshold_pct` | **None [KARAR — şimdilik]** | İlgili KPI'lar "Pending". C1'in birincil sorusu (QDiabetes duyarlılığı, NB1 §4) da eşik seçilene kadar "Pending" |
| D6 | Etnisite eşlemesi NABIDH → QDiabetes 9 kategori / LRS | `codelists` eşleme tabloları | Emirati, Gulf Arab, Arab → "Other" | Sentetikte "Other" eşlemesi tek başına ~2× düşük tahmin üretiyor |
| D7 | Yoğunluksuz "current" sigara kategorisi | `qd_smoking_current_category` | 3 (moderate) | Midwakh / shisha nasıl ele alınacak |
| D8 | Sigara kaydı yok = non-smoker mı | `qd_missing_smoking_as_non` | **False [KARAR]** | Kayıt yok = bilinmiyor |
| D9 | Kapsam dışı 7 Model A prediktörü = 0 (indirgenmiş model) | `qd_force_reduced_model` | **True [KARAR]** | Statin, steroid, atipik antipsikotik, şizofreni/bipolar, öğrenme güçlüğü, GDM, PCOS |
| D10 | Townsend = 0 | `qd_townsend` | **0.0 [KARAR]** | UAE'de karşılığı yok |
| D11 | 5 y risk için baseline ölçekleme S0(t) = S0(10)^(t/10) | `qd_baseline_time_scaling` | "power" | Yayınlanmış kodda yalnız 10 y baseline var — ayrıca [KISIT] |
| D12 | Leicester skorunda etnisite "Not recorded" → skor hesaplanmaz (LPRS ve LRA) | `lrs_unknown_ethnicity_as_missing` | True | — |
| D13 | Recalibration bölme yöntemi | `recal_split` | "temporal" | Temporal test parçasında 5 y AUROC hesaplanamıyor (≥5 y takipli kontrol yok) |
| D14 | Başlangıçta prediyabet: hariç (v2) / duyarlılıkta dahil | (eklenecek) | hariç | QDiabetes geliştirme popülasyonuyla uyum |
| D15 | Outcome için doğrulayıcı ikinci test; random glukoz ≥200 ve yalnız E11 tanısı olay mı | (eklenecek) | tek test; ikisi de olay | ADA ikinci test ister |
| D16 | Gebelik dönemi lab'ları dışlansın mı | — | **gerekmiyor [KARAR]** | Gebelik verisi yok |
| D17 | Aile öyküsü kaydı yok = negatif mi (C1 tamlık) | `c1_require_fh_record` | False | Enclave'de netleşecek |
| D18 | KVH tanımı (I50 ve tüm I60–I69 dahil mi) | `codelists.DX["cvd"]` | **NABIDH listesi [KARAR]** | I20–I25, I50, I6x, G45 |
| D19 | Adım 3'ü tetikleyecek "yeterli performans" | (eklenecek) | — | Veriye bakmadan önce yazılmalı |
| D20 | Fairness alt grupları ve kabul edilebilir fark | (eklenecek) | cinsiyet, yaş bandı, etnisite | — |
| D21 | Kod listelerinin klinik onayı; model card klinik bölümleri | — | — | Evidence package (Critical KPI) için şart |
| D23 | LPRS "yüksek risk" eşiği (skor ≥ x) | `lprs_high_risk_threshold` | **None** [KARAR BEKLİYOR] | LPRS sabit terimsiz doğrusal öngörücü; yayımlanmış mutlak eşik bulunamadı. Yazarlar sıralama kullandı: pratik başına en yüksek %10 (Let's Prevent / Walking Away) ya da hedef duyarlılık (ör. %80). Seçilene kadar C1 Leicester yakalama oranı ve C3 eşik metrikleri "Pending". Dağılım NB1 `score_summary.csv`'de (medyan, IQR) |
| D22 | C1/C2 duyarlılığında referans tarihi: veri sonu mu, statüyü belirleyen ilk kanıt (tanı) günü mü | `cohorts.positive_reference_dates` | NB1 §4 ikisini yan yana raporlar; birincil seçilmeli | Veri sonu: tanı sonrası kayıtlar (tedavi sonrası BMI, ilaç) skora girer, yaş veri sonuna göre. İlk kanıt: "tanıda yakalar mıydı" sorusuna uygun ama o gün kayıtlar daha seyrek → hesaplanabilirlik düşer |

## 3. Dış taraflar
**DHA / NABIDH [DIŞ]:** C3 teslimi takipte diyabet gelişen hastaları da içeriyor mu (v2 spec'e göre evet; NB2'nin duyarlılık / AUROC / kalibrasyonu buna dayanır — yalnız "gelişmeyenler" teslim edildiyse C3'ten yalnız özgüllük çıkar); veri sözlüğü ve dosya formatı; etnisite/uyruk kategori listesi; birimler;
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
- Leicester skorları (LPRS, LRA) kesitsel tespit skorlarıdır; C3'te incident benchmark'ı dış kullanımdır.
- LPRS (varsayılan, K-LRS) Leicester'da (UK, çok etnili) 40–75 yaşta geliştirildi: etnisite ikili (beyaz /
  BME) — UAE'de Emirati, Arap ve Güney Asyalı aynı katsayıyı alır; antihipertansif yalnız ilaç kaydından
  (HT tanısı girdi değil); sabit terimsiz doğrusal öngörücü → mutlak risk ve kalibrasyon yok; 40–75 dışı
  ekstrapolasyon (NB1 `lrs_outside_dev_age_pct`).
- C1/C2 yalnızca pozitif vaka içerir; buradan performans metriği çıkmaz.
- QDiabetes 5 y riski 10 y baseline'dan varsayımla türetiliyor (D11).
- İndirgenmiş Model A (D9) ve Townsend = 0 (D10) karşılaştırılabilirliği sınırlar.
- C3 iki glisemik ölçüm şartı daha sık test edilen (muhtemelen daha riskli) hastaları seçer.
- Etnik grup uyruktan türetiliyor (D6); uyruk etnisite değildir (ör. Hindistan kökenli İngiltere vatandaşı).

## 5. Kararlar (verildikçe buraya)
| Tarih | Karar | Kim | Parametre / commit |
|---|---|---|---|
| 2026-11-13 | D6: etnik grup NABIDH etnisite alanı yerine **uyruktan** (nationality) türetilir. Uyruk → grup eşlemesinin içeriği hâlâ medikal ekip onayında | ensargunesdogdu | `ethnicity_source = "nationality"`, `codelists.NATIONALITY_COUNTRIES` |
| 2026-11-13 | D1: outcome washout 90 gün (index sonrası ≤ 90 günde olay = prevalent, hasta çıkarılır); v2 (0 gün) duyarlılık | ensargunesdogdu | `outcome_washout_days = 90`; .run 4b (0 gün) |
| 2026-11-13 | D2: birincil horizon 3 yıl — şimdilik, ayrıntılı bakılacak; 5 yıl ikincil | ensargunesdogdu | `horizon_years = 3`, `horizon_years_fallback = 5` |
| 2026-11-13 | D3: prediktör penceresi 1 yıl birincil; 2 yıl ek kontrol (duyarlılık) | ensargunesdogdu | `predictor_lookback_days = 365`; `SANDBOX_PARAMS='{"predictor_lookback_days": 730}'`, .run 4c |
| 2026-11-13 | D4: eksik veri yaklaşımı parametrenin türüne göre değişecek (ayrıntı açık, K2) | ensargunesdogdu | — (şimdilik complete-case) |
| 2026-11-13 | D5: QDiabetes risk eşiği şimdilik varsayılan (yok) → eşik KPI'ları "Pending" | ensargunesdogdu | `qd_risk_threshold_pct = None` |
| 2026-11-13 | D8: sigara kaydı yok = bilinmiyor (non-smoker sayılmaz). Notlarda D7 başlığı altında yazılmıştı; içerik D8'e karşılık geliyor | ensargunesdogdu | `qd_missing_smoking_as_non = False` |
| 2026-11-13 | D9: kapsam dışı 7 Model A prediktörü kapsam dışı kalır (indirgenmiş model) | ensargunesdogdu | `qd_force_reduced_model = True` |
| 2026-11-13 | D10: Townsend kapsam dışı → 0 | ensargunesdogdu | `qd_townsend = 0.0` |
| 2026-11-13 | D16: gebelik verisi yok → dışlama kuralı gerekmiyor | ensargunesdogdu | — |
| 2026-11-13 | D18: KVH tanımı NABIDH Data availability listesindeki gibi (I20–I25, I50, I6x, G45) | ensargunesdogdu | `codelists.DX["cvd"]` (zaten aynı) |
| 2026-11-14 | K-LRS: NABIDH teslim listesinde bel çevresi yok → seçenek **(b)**: bel çevresi istemeyen **Leicester Practice Risk Score** (Gray LJ et al., Diabetologia 2012;55(4):959–966; yaş, cinsiyet, BME, BMI, aile öyküsü, antihipertansif ilaç) varsayılan. LRA 2010 (bel zorunlu) karşılaştırma için kalır; (c) bel puanı = 0 / BMI'den türetme valide değil, kullanılmaz. Eşik ayrı karar (D23). Kaynak: Slack #sandboxteam 2026-11-13 — ensargunesdogdu: "b seçeceği ile hazırlatıyorum kodu" (sic); Zeynep Pelin Polat 🙏 tepkisiyle onayladı | ensargunesdogdu + Zeynep Pelin Polat | `lrs_variant = "practice_2012"`, `scores/lprs.py`; NB0 Framework Match bel çevresini artık istemiyor (A5) |
| 2026-11-14 | Çalışma çerçevesi (anlatım kaydı): Study Flow 1 = C1, birincil amaç bilinen pozitiflerde QDiabetes / LRS'in "yüksek risk" deme oranı (duyarlılık) · 2 = C2, tamlık şartı olmadan değişkenlerin NABIDH'te varlığı · 3 = C3, diyabet gelişmeyenlerde "diyabet değil" deme kapasitesi + parametre ayarıyla (recalibration) iyileştirme · 4 = UAE'ye özgü, lab'sız model; sonuçlar kötüyse NABIDH'ten yeni veri teslimiyle | ensargunesdogdu | NB1 §4 `nb01/c1_detection_rate.csv` (`metrics.detection_rate`); D22 |
``
D1 - 90 Gün
D2 - 3 Yıl şimdilik ama bu konuya detaylı bir bakmak gerekiyor.
D3 - Bizim için bir yıl öncelikli, iki yıl ek olarak kontrol edeceğimiz bir mekanizma olabilir.
D4 - Her parametrenin türüne göre değişecek.
D5 - default neyse odur şu an için
D6 - Nationality kullanacağız.
D7 - Sigara statüsü olmayan bil``inmiyor olarak işaretlenecek. C2 ve C3 için C1 de hepsinde mevcut.
D8
D9 - Kapsam Dışı kalacak
D10- Out of scope
D16 - Gebelik olan veri yok.
D17 - Orada netleştireceğiz.
D18 - Selahattin screenshot'da mevcut
