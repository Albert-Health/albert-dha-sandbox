# Model Card — QDiabetes-2018 Model A ve LRS'in UAE (NABIDH) değerlendirmesi

> Şablon. `{{...}}` alanları doldurulur; köşeli parantezli kaynak, değerin hangi çıktıdan geldiğini gösterir.
> Klinik bölümler medikal ekip tarafından yazılır ve imzalanır.

## 1. Model detayları
- Modeller: QDiabetes-2018 Model A (ClinRisk / Oxford; katsayılar CRAN `QDiabetes` 1.0-2), Leicester Risk Assessment (Gray et al. 2010)
- Varyant: {{qd_variant}}  [nb02/coverage.csv]
- Kollar: Kol 1 yayınlanmış · Kol 2a baseline recalibration · Kol 2b baseline + eğim  [nb02/recalibration_models.json]
- Kod sürümü: {{git_commit}} · kod hash {{code_sha256}}  [run_manifest.json]

## 2. Amaçlanan kullanım (KLİNİK — medikal ekip)
- Kullanım: {{intended_use}}
- Hedef popülasyon: UAE'de 25–84 yaş, başlangıçta diyabet ve prediyabeti olmayan yetişkinler
- Karar sınırı: DANIŞMA (advisory) — çıktı yalnızca insan değerlendirmesi içindir
- Kapsam dışı: klinik deployment, tedavi önerisi, laboratuvar değerlerinin girdi olarak kullanımı

## 3. Veri
- Kaynak: NABIDH, DHA Secure Data Enclave · Kohort akışı {{c3_funnel}}  [nb02/c3_funnel.json]
- Outcome: incident T2D (ADA 2024), horizon {{horizon_years}} yıl, washout {{washout_days}} gün

## 4. Performans (test parçası)
| Kol | C-index (95% CI) | AUROC@h (95% CI) | O:E | Kalibrasyon eğimi |
|---|---|---|---|---|
| {{rows}} |  |  |  |  |
[nb02/performance.csv]

## 5. Alt gruplar / fairness
{{subgroup_summary}}  [nb02/subgroups.csv, nb02/subgroup_oe.png]

## 6. Bilinen kısıtlar ve varsayımlar ([KARAR BEKLİYOR] olanlar dahil)
- İndirgenmiş Model A (7 prediktör = 0), Townsend = 0, sigara "current" eşlemesi, etnisite eşlemesi
- 10 yıl dışındaki horizon'lar için baseline survival varsayımı (Kol 1)
- LRS'in incident kullanımı dış kullanımdır (kesitsel tespit skoru)
- İki glisemik ölçüm şartı daha sık test edilen (daha riskli) hastaları seçer

## 7. Onay
| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Clinical / Domain Lead |  |  |  |
| Technical Lead |  |  |  |
