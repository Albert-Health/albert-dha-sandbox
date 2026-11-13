# Faz 1 — C1 / C2 hazırlık ve çalıştırma planı

Hazırlanma: 2026-11-13 · Hedef: DHA ofisi, enclave'de veri erişimi **Pazartesi 2026-11-16**

**Esas liste:** NABIDH'in "Data availability" sayfası (aşağıda §2). Kapsam ve hazırlık kararları bu
listeye göre verilir; sentetik veri yalnızca kodun uçtan uca çalıştığını göstermek içindir.

Etiketler: **[ENGEL]** Pazartesiden önce çözülmezse Faz 1 çalışmaz ya da yanlış sonuç verir ·
**[ÖNEMLİ]** · **[İYİ OLUR]** · **[KARAR BEKLİYOR]** medikal ekip · **[DHA]** enclave'de sorulacak

## 1. Fazlar

| Faz | Kohort | Ne | Kod |
|---|---|---|---|
| **Faz 1** | C1, C2 (T2DM + prediyabet) | Veri profili; QDiabetes-2018 A ve LRS'in hesaplanması | NB0, NB1, `kpi_report` (kısmi) |
| **Faz 2** | C3 (başlangıçta non-diyabetik) | Incident benchmark: Kol 1 / 2a / 2b, alt gruplar | NB2, `positive_control`, evidence package |
| Faz 3 | C3 | UAE modeli (koşullu) | — |

**Faz 1 neyi cevaplar, neyi cevaplamaz**
- Cevaplar: NABIDH verisiyle iki skor hesaplanabiliyor mu, hangi oranda, hangi değişken yüzünden
  hesaplanamıyor; tam kayıtlı hastalar (C1) rastgele hastalardan (C2) farklı mı; etnisite kategorileri
  QDiabetes / LRS'e nasıl eşleniyor; skorların betimleyici dağılımı.
- Cevaplamaz: skorlar UAE'de *doğru* mu. C1/C2'de herkes zaten pozitif vaka → ayrım gücü ve kalibrasyon
  yok; bu Faz 2'nin (C3) işi.
- C2 tamlık için temsilî örneklemdir; C1 seçim gereği tamdır. Tamlık KPI'larının Faz 1 değeri C2'den gelir.

## 2. Teslim edilecek veri — NABIDH Data availability

Hasta sayısı ve kohorta oranı. Kohort büyüklükleri: C1 = 2.600, C2 = 2.600 (Patient profile'dan teyit
edilecek), C3 = 1.000. Satır sayıları buraya alınmadı; < 10 hücreler bastırıldı.

| Kalem | Kod / kaynak | C1 | C2 | C3 |
|---|---|---|---|---|
| **Tanı** | | | | |
| Tip 2 diyabet | E11 | 1.221 (%47,0) | 1.408 (%54,2) | 322 (%32,2) |
| Prediyabet | R73 | 2.180 (%83,8) | 1.720 (%66,2) | 580 (%58,0) |
| Hipertansiyon | I10–I16 | 1.015 (%39,0) | 1.199 (%46,1) | 384 (%38,4) |
| Kardiyovasküler hastalık | I20–I25, I50, I6x, G45 | 507 (%19,5) | 447 (%17,2) | 208 (%20,8) |
| Obezite / BMI kodu | E66, Z68 | 557 (%21,4) | 313 (%12,0) | 160 (%16,0) |
| Sigara (tanı) | F17.2, Z72.0, Z87.891 | 15 (%0,6) | 15 (%0,6) | <10 |
| Diyabet aile öyküsü (tanı) | Z83.3 | 309 (%11,9) | 133 (%5,1) | 50 (%5,0) |
| Tip 1 diyabet (0 olmalı) | E10 | 0 | 0 | 0 |
| **Lab** (yalnız statü / outcome; model girdisi değil) | | | | |
| HbA1c | LOINC 4548-4 | 462 (%17,8) | 217 (%8,3) | 1.000 (%100) |
| Açlık glukozu | LOINC 1558-6 | 923 (%35,5) | 736 (%28,3) | 500 (%50,0) |
| OGTT 2 saat | LOINC 1521-4 | 17 (%0,7) | 30 (%1,2) | 31 (%3,1) |
| **Gözlem** | | | | |
| BMI | LOINC 39156-5 | 2.600 (%100) | 336 (%12,9) | 186 (%18,6) |
| Boy | LOINC 8302-2 | 2.600 (%100) | 2.471 (%95,0) | 976 (%97,6) |
| Kilo | LOINC 3141-9 (sandbox kodu) | 2.600 (%100) | 2.515 (%96,7) | 983 (%98,3) |
| **Diğer** | | | | |
| Sigara durumu | SocialHistory | 2.600 (%100) | 1.483 (%57,0) | 766 (%76,6) |
| Diyabet aile öyküsü | FamilyHistory | 2.600 (%100) | 419 (%16,1) | 168 (%16,8) |
| İlaç order'ları (çalışma ilaçları) | Medication | 1.557 (%59,9) | 1.513 (%58,2) | 496 (%49,6) |
| Encounter | Encounter | — | — | 1.000 (%100) |

**Listede olmayanlar:** bel çevresi · demografi ve uyruk (muhtemelen "Patient profile" sekmesinde —
teyit; etnik grup uyruktan türetilecek) · random glukoz, IFCC HbA1c · QDiabetes'in ek 7 prediktörü (statin "çalışma
ilaçları" içinde olabilir) · Townsend.

## 3. Skor girdileri → teslim kaynağı → durum

| Girdi | QDiabetes | LRS | Teslim kaynağı | C1 | C2 | Kod hazır mı |
|---|---|---|---|---|---|---|
| Cinsiyet, yaş | ✓ | ✓ | Patient profile | — | — | Evet |
| Etnik grup | ✓ | ✓ | Patient profile → **uyruk** (nationality) [KARAR: 2026-11-13] | ? | ? | Evet — uyruk → etnik grup → QDiabetes / LRS (`codelists.NATIONALITY_COUNTRIES`); eşleme içeriği D6 |
| BMI | ✓ | ✓ | BMI 39156-5 → yoksa boy + kilo → yoksa Z68 | %100 | doğrudan %12,9; boy/kilo ~%95 | Evet; birim kontrolü yok (A3) |
| Sigara | ✓ | — | SocialHistory'den çıkarılır (+ F17.2 / Z72.0 / Z87.891) | %100 | %57,0 | Evet — adapter SocialHistory'den çıkarıyor (A2) |
| Aile öyküsü | ✓ | ✓ | FamilyHistory'den çıkarılır (+ Z83.3) | %100 kayıt | %16,1 kayıt | Evet — adapter FamilyHistory'den çıkarıyor; pozitif = birinci derece akraba (A2) |
| KVH | ✓ | — | I20–I25, I50, I6x, G45 | %19,5 | %17,2 | Evet (kod listesi aynı) |
| Hipertansiyon | tanı **ve** ilaç | tanı **veya** ilaç | I10–I16 + Medication | %39,0 / %59,9 | %46,1 / %58,2 | Tanı evet; ilaç kodlaması bilinmiyor (A4) |
| Bel çevresi | — | ✓ | **Listede yok** | — | — | **LRS hesaplanamaz** (K-LRS) |
| Ek 7 prediktör | ✓ | — | Listede yok | — | — | İndirgenmiş model zaten varsayılan (D9) |
| Townsend | ✓ | — | Yok | — | — | 0 (D10) |

**Sonuçlar**
1. **LRS (Gray 2010) bu veriyle hesaplanamaz** — bel çevresi teslim edilmiyor. Faz 1'in en büyük
   açığı; K-LRS kararı gerekiyor.
2. **QDiabetes C1'de** (uyruk kayıtlıysa ve yaş 25–84 ise) neredeyse tüm hastalarda hesaplanabilir olmalı.
3. **QDiabetes C2'de** sigara kaydı %57. D8 kararıyla (kayıt yok = bilinmiyor) hesaplanabilirlik en fazla
   ~%57; kalanlar "smoking_missing" nedeniyle raporlanır.
4. **Aile öyküsü C2'de** yalnız %16 kayıtlı; kaydı olmayanların negatif sayılması (D17) hem tamlığı hem
   skor değerini belirler.
5. Teslim olay düzeyinde ve kaynak tipine göre (Patient, tanı, Observation, SocialHistory,
   FamilyHistory, Medication, Encounter) görünüyor → hasta başı düz dosya riski düşük. Sigara
   SocialHistory'den, aile öyküsü FamilyHistory'den çıkarılır (A2 — yapıldı).

## 4. Enclave'de çalıştırma akışı

```bash
# 0. Kurulum ve duman testi
python -m pip install --no-index --find-links wheels/ -r requirements.txt
python -m unittest discover -s tests -v

# 1. Ham veri: data/nabidh/raw/c1/, data/nabidh/raw/c2/ (DHA'nın verdiği dosyalar; dokunulmaz)
# 2. src/sandbox/io/adapters/nabidh.py → SOURCES'taki dosya/sütun adlarını gerçek adlarla değiştir
#    (tarih ISO değilse DATE_FORMAT, ayraç/kodlama CSV_OPTIONS)
# 3. Ham → kanonik + değer dağılımı raporu (outputs/<run_id>/ingest/<kohort>_value_counts.csv)
python tools/ingest_nabidh.py --cohorts c1 c2
#    "unmapped" değer varsa (sigara, aile öyküsü, uyruk, kod|birim) adapter sözlüklerini genişlet, 3'ü tekrarla
# 4. Veri profili
SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py
# 5. Fizibilite + QDiabetes + LRS
SANDBOX_SOURCE=nabidh python notebooks/01_c1_c2_feasibility.py
# 6. KPI özeti (Faz 1'de kısmi)
SANDBOX_SOURCE=nabidh python tools/kpi_report.py
```

Her adımdan sonra `outputs/<run_id>/run_manifest.json` → `"status": "success"`; NB0 şema kontrolünde ERROR = 0.

**Prova (sentetik, NABIDH biçiminde) — 2026-11-13'te çalıştırıldı:**

```bash
python tools/build_synthetic_cohorts.py
python tools/make_nabidh_dryrun.py        # → data/nabidh_dryrun/raw/<c1|c2|c3>/ (teslim listesine uygun dosyalar)
python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
SANDBOX_SOURCE=nabidh_dryrun python notebooks/00_data_profile.py      # NB1, NB2, kpi_report aynı
```

Sonuç: tüm run'lar `success`, şema ERROR = 0, eşlenemeyen değer yok. C1/C2'de 8 çekirdek değişken
sentetik veriyle hasta bazında birebir aynı (aile öyküsü Z83.3 olmadan yalnız FamilyHistory'den
okunduğunda da). QDiabetes hesaplanabilirliği değişmedi (C1 %95,7, C2 %81,8); LRS %0 — teslimde bel
çevresi olmadığı için beklenen. NB0 Framework Match "Eksik: waist_cm" (A5).

## 5. Kod — Pazartesiden önce

| # | İş | Etiket | Neden |
|---|---|---|---|
| A1 | `tools/ingest_nabidh.py`: ham → `data/canonical/<source>/{c1,c2,c3}`, audit'li, `schema.validate` + kaynak değer dağılımı raporu | **[YAPILDI 2026-11-13]** | — |
| A2 | Adapter teslim yapısına göre (`SOURCES`): Patient, tanı, Observation (lab + vital), SocialHistory → sigara, FamilyHistory → aile öyküsü (yalnız diyabet, birinci derece), Medication, Encounter (yalnız C3); kod sistemi (HL7 `I10`, `LN`, `SCT` …), BOM, gün-önce tarih desteği; `tools/make_nabidh_dryrun.py` ile prova; `tests/test_nabidh_adapter.py` | **[YAPILDI 2026-11-13]** | Enclave'de yalnızca `SOURCES`'taki dosya/sütun adları ve gerekirse değer sözlükleri güncellenecek |
| A3 | Boy / kilo birim kontrolü (m → cm, lb → kg) + NB0'a BMI / boy / kilo dağılımı ve birim tablosu | [ÖNEMLİ] | C2'de doğrudan BMI yalnız %12,9; geri kalanı boy/kilodan hesaplanacak. Boy metre gelirse 120–230 cm filtresi hepsini atar |
| A4 | Medication kodlaması: ATC değilse ilaç adı / yerel kod → ATC eşleme tablosu | [ÖNEMLİ] | Hipertansiyon tedavisi (QDiabetes) ve A10 bayrağı buna bağlı |
| A5 | NB0 Framework Match'in gerekli grup listesi NABIDH'e iletilen talep listesiyle eşleşmeli | [ÖNEMLİ] | Liste şu an bel çevresini de istiyor → otomatik "Not Met". Bel talep edildiyse bu doğru; edilmediyse listeden çıkmalı |
| A6 | `kpi.build` NB1 değerlerini kullansın (`nb1` parametresi gövdede yok) | [ÖNEMLİ] | Faz 1 KPI raporunda tamlık satırları boş kalır |
| A7 | LRS alternatifi — K-LRS kararına göre | [KARAR'a bağlı] | — |
| A8 | NB1'e etnisiteye göre skor dağılımı (Emirati / Gulf Arab / Güney Asya / diğer) | [İYİ OLUR] | Ana hipotezin (Emirati'de düşük tahmin) Faz 1'deki ilk betimleyici sinyali |
| A9 | ICD kodları kısaltılmış gelirse ("F17.2") sigara tanı eşlemesi | [İYİ OLUR] | Kod listesi tam kod bekliyor (F17210 …); etki küçük (~15 hasta) |
| A10 | NB0 `SANDBOX_PARAMS`'ı okusun; `SANDBOX_BOOTSTRAP_REPS` manifest'e yazılsın; `claude.md` / `docs/gap.md` adları kurallarla eşleşsin | [İYİ OLUR] | Audit tutarlılığı; Linux VM'de `claude.md` ≠ `CLAUDE.md` |

## 6. Kararlar — Faz 1'i etkileyenler (kayıt: `docs/gap.md` §5)

**[KARAR]** = 2026-11-13'te verildi ve config'e işlendi. Açık kalanlarla çıkan sonuçlar "varsayılan
parametrelerle, ön sonuç" olarak etiketlenmeli. Alternatifler duyarlılık çalıştırmasıyla: `SANDBOX_PARAMS='{...}'`.

| # | Karar | Parametre | Varsayılan | Faz 1 etkisi |
|---|---|---|---|---|
| **K-LRS** | Bel çevresi teslim edilmiyor → LRS ne olacak | (eklenecek) | — | (a) Faz 1'de "LRS hesaplanamaz" diye raporla · (b) bel gerektirmeyen Leicester varyantı: Leicester Practice Risk Score (Gray et al., Diabetologia 2012; rutin EHR verisi için geliştirildi — değişkenler ve katsayılar birincil makaleden doğrulanmalı) · (c) bel puanını 0 saymak / BMI'den türetmek — valide değil, önerilmez |
| D8 | Sigara kaydı yok = içmiyor mu | `qd_missing_smoking_as_non` | **False [KARAR]** — kayıt yok = bilinmiyor | C2'de QDiabetes en fazla ~%57 |
| D17 | Aile öyküsü kaydı yok = negatif mi | `c1_require_fh_record` | False — **enclave'de netleşecek** | C2'de yalnız %16 kayıt |
| D7 | Yoğunluksuz "current" sigara | `qd_smoking_current_category` | 3 (moderate) — açık | SocialHistory değerlerine bağlı |
| D6 | Uyruk → etnik grup → QDiabetes / LRS eşlemesinin içeriği. Kaynak = uyruk: [KARAR: 2026-11-13, ensargunesdogdu] | `ethnicity_source`, `codelists.NATIONALITY_COUNTRIES`, `NABIDH_TO_QDIABETES` | BAE / Körfez / Arap → "Other"; belirsiz uyruklar (İran, Afganistan, Türkiye, Sudan …) eşlenmedi → "Other" | Ingest raporundaki gerçek uyruk listesiyle tamamlanacak. Uyruk etnisite değildir [KISIT] |
| D9 | İndirgenmiş Model A (7 prediktör = 0) | `qd_force_reduced_model` | **True [KARAR]** | Kapsam dışı kalacak |
| D10 | Townsend = 0 | `qd_townsend` | **0.0 [KARAR]** | Kapsam dışı |
| D18 | KVH tanımı | `codelists.DX["cvd"]` | **NABIDH listesi [KARAR]** | I20–I25, I50, I6x, G45 (kod listesi zaten aynı) |
| D12 | LRS'de etnisite kayıtsız → hesaplanmaz | `lrs_unknown_ethnicity_as_missing` | True | K-LRS'e bağlı |
| K5 | LRS madde puanlarının birincil makaleden teyidi | `scores/lrs.py` | — | K-LRS'e bağlı |
| Yeni-1 | Yalnızca Z68 bandından gelen BMI skor girdisi sayılsın mı | (eklenecek) | Skorda kullanılıyor, tamlıkta "eksik" | Boy/kilo kapsamı yüksek → etkisi küçük olmalı |
| Yeni-2 | C1/C2 referans tarihi: veri sonu ("as currently recorded") mı, ilk tanı tarihi mi | (eklenecek) | veri sonu | Tanı sonrası kilo / tansiyon / ilaç değişimleri skorlara girer; yaş veri sonuna göre hesaplanır |
| D5 | QDiabetes risk eşiği | `qd_risk_threshold_pct` | **None [KARAR — şimdilik]** | Eşik KPI'ları "Pending" |

Faz 2 kararları: D1 washout **90 gün [KARAR]** · D2 horizon **3 yıl birincil, 5 yıl ikincil [KARAR — şimdilik]**
· D3 lookback **1 yıl, 2 yıl duyarlılık [KARAR]** · D16 **gerekmiyor [KARAR]**. Açık: D11 (3 yıl birincil
olduğundan Kol 1'de artık doğrudan kullanılıyor), D13–D15, D19, D20. C3 = 1.000 hasta (v2'de "no cap" idi) → neden ve tam eligible N [DHA].

## 7. DHA / NABIDH — Pazartesi sorulacak / teyit edilecek [DHA]

Data availability listesiyle cevaplananlar: teslim olay düzeyinde ve kaynak tipine göre; lab LOINC'leri
(4548-4, 1558-6, 1521-4); T1D = 0; encounter yalnız C3'te; C3 = 1.000.

**Skor girdileri**
- [ ] Patient profile: cinsiyet, doğum tarihi ve **uyruk** alanı — biçimi (ülke adı / ISO kodu /
      "UAE National"), kategori listesi, eksiklik oranı
- [ ] **Bel çevresi gerçekten yok mu?** Vital'ler içinde başka kodla olabilir (LOINC 8280-0 / 56086-2)
- [ ] SocialHistory: sigara değer sözlüğü (metin / kod; yoğunluk; midwakh, shisha)
- [ ] FamilyHistory: hangi hastalık (yalnız diyabet mi), akrabalık derecesi, negatif kayıt var mı
- [ ] Medication: kodlama (ATC / ilaç adı / yerel kod), "çalışma ilaçları" listesi, order mı dispense mi
- [ ] Boy / kilo birimleri; "Weight (sandbox code)" — kaynaktaki asıl kod neydi
- [ ] ICD-10 kod biçimi (noktalı mı, tam uzunlukta mı)

**C1 / C2 seçimi**
- [ ] C1 "complete case" tanımı: FamilyHistory / SocialHistory kaydı olması mı, pozitif kayıt mı
- [ ] C2 toplam N (2.600 mü), örnekleme yöntemi; C1 achievable N (cap öncesi); C1–C2 örtüşmesi
- [ ] Veri çekim tarihi (referans tarih için)

**Ortam**
- [ ] VM işletim sistemi, Python sürümü (≥ 3.10 gerekli), pip / conda, Jupyter, git
- [ ] Kod ve wheel'ler içeri nasıl giriyor (yükleme yolu, onay süreci); disk / RAM

**Çıktı çıkarma**
- [ ] Küçük hücre eşiği (bizde < 10), figür onayı, izinli formatlar, onaylayan kişi ve süre
- [ ] Hasta düzeyi ara dosyaların enclave içinde saklanma / silinme kuralı

## 8. Pazartesi götürülecekler

- [ ] Kod: etiketli commit'in `git archive` paketi + SHA-256 (commit hash'i not edilir; enclave'de git
      yoksa audit yine dosya bazında kod hash'i yazar)
- [ ] Offline wheel'ler, bağımlılıklarıyla, olası platform / Python sürümleri için. Örnek:
      `pip download -r requirements.txt -d wheels --only-binary=:all: --platform manylinux2014_x86_64 --python-version 3.11`
      (Windows VM ihtimaline karşı `--platform win_amd64` ile ikinci set)
- [ ] Bu belge ve karar tablosu (verilen kararlar işlenmiş olarak)
- [ ] Hasta verisi yok — sentetik dahil. Enclave'de duman testi için `tests/` fixture'ları yeterli

## 9. Pazartesi akşamı elde olması gerekenler (Faz 1 "tamam" tanımı)

- [ ] NB0 ve NB1 run'ları `status: success`, şema ERROR = 0, audit %100
- [ ] C1 ve C2: 8 çekirdek değişkenin tamlığı, QDiabetes hesaplanabilirlik %, eksiklik nedenleri
- [ ] LRS: K-LRS kararına göre ya hesaplanmış skor ya da gerekçeli "hesaplanamaz" satırı
- [ ] C1–C2 SMD tablosu (seçilim etkisi)
- [ ] Uyruk → etnik grup eşleme tablosu (NB1 `ethnicity_mapping.csv`) → medikal ekibe (D6)
- [ ] Ingest değer raporu (`ingest/<kohort>_value_counts.csv`) ve NB0 `unmapped_codes.csv` → eşleme
      sözlüklerinin güncellenmesi
- [ ] Enclave'den çıkacak özet tabloların küçük hücre kontrolü ve DHA onayı
