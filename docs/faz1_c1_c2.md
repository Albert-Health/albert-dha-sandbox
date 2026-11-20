# Faz 1 — C1 / C2: enclave'de yapılacaklar

Güncelleme: 2026-11-19 · Açık işler ve kararların kaydı: [`gap.md`](gap.md) · Komutların ayrıntısı:
[`enclave_terminal.md`](enclave_terminal.md)

| Ortam | Değer |
|---|---|
| VM | DHA uzak masaüstü (XFCE, IntelliJ, Firefox). Repo: `~/Desktop/albert-dha/albert-dha-sandbox` |
| Python | `/usr/bin/python3`; paketler `--user` ile kuruldu (2026-11-18). Komutlarda `python3` |
| IRIS | `10.28.29.29:51772`, namespace `HSSBX`, salt-okuma kullanıcı; ayar `~/.nabidh_iris` (repo dışında) |
| C1 şeması | `SBXV_ENCL447CCD80_HSAA` |
| C2 şeması | `SBXV_ENCL94F43B4B_HSAA` |
| C3 şeması (Faz 2) | `SBXV_ENCL6F10EFBD_HSAA` (2026-11-19'a kadar kodda C2 ile yer değiştirmişti) |

**Çalışma döngüsü.** Her komut sonucunu `COPY START` … `COPY END` arasında basar. Bu bloğu ekibe
yapıştır. Adapter düzeltmesi VM dışında yapılır ve push edilir; VM'de `git pull --ff-only` ile alınıp komut
tekrarlanır. VM'de kod düzenlenmez. Bloklarda yalnız meta veri ve özet vardır. Yine de yapıştırmadan önce
göz at.

## Faz 1 neyi cevaplar

- **C1 (birincil):** QDiabetes-2018 A ve Leicester (LPRS, bel çevresiz) skorları, T2DM ya da prediyabetli
  olduğu bilinen hastaların yüzde kaçını "yüksek risk" buluyor (duyarlılık, `nb01/c1_detection_rate.csv`).
- **C2:** 8 çekirdek değişkenin NABIDH'te ne kadar dolu olduğu (tamlık).
- Ayrıca: skorlar hangi oranda hesaplanabiliyor ve neden hesaplanamıyor, C1 ile C2 farkı (SMD, seçilim
  etkisi), etnisite eşlemesi, skor dağılımı.
- **Cevaplamaz:** özgüllük, PPV, AUROC, kalibrasyon. C1/C2'de negatif vaka yok; bunlar Faz 2'de (C3).

## Yapılacaklar (sırayla)

### 0 · Başlat (~5 dk)

- [ ] Terminal, repo kökü:

  ```bash
  cd ~/Desktop/albert-dha/albert-dha-sandbox
  ```

- [ ] Kodu güncelle. İlk seferde VM'deki eski `nabidh.py` değişikliğini kenara al:

  ```bash
  git stash && git pull --ff-only && git log -1 --oneline
  ```

  Sonraki güncellemeler: `git pull --ff-only`.

- [ ] Bir kez: repo kökünde `.env` (git dışı, `.gitignore`'da). `import sandbox` onu okur; her terminal, notebook
  ve Jupyter kernel'i `SANDBOX_SOURCE=nabidh` ve IRIS şifresini buradan alır, `export` gerekmez. Şifre ekrana ve
  shell geçmişine yazılmaz; dosya varsa üzerine yazılır:

  ```bash
  read -rs -p "IRIS şifresi: " p && echo && printf 'SANDBOX_SOURCE=nabidh\nNABIDH_IRIS_PASSWORD=%s\n' "$p" > .env && unset p && chmod 600 .env
  ```

  Ortamda (komut satırında) verilen değer `.env`'i geçer. Audit'e yalnız anahtar adları yazılır. `.env` istemezsen
  eski yol: `read -rs -p "IRIS şifresi: " NABIDH_IRIS_PASSWORD && echo && export NABIDH_IRIS_PASSWORD` (her
  terminalde).

- [ ] Ortam + IRIS + eşleme kontrolü:

  ```bash
  python3 tools/check_environment.py --iris --quick
  ```

  Beklenen: FAIL yok. `[repo] .env` satırında `NABIDH_IRIS_PASSWORD, SANDBOX_SOURCE`. `[mapping]` c1 ve c2
  PASS. c1 encounters INFO: yetki yok, Faz 1'de gerekmiyor. WARN çıkarsa bloğu gönder.

- Tablo adlarında şema yerine kohort yazılır: `c1.Patient`, `c2.Observation` (şemalar adapter'daki
  `IRIS_COHORTS`'tan). Shell'de C1 / C2 değişkeni gerekmez.

### 1 · Değerlere bak — ingest'ten önce (~20 dk, K3)

Adapter sözlükleri tahmine dayanıyor. Bu adım onları gerçek değerlerle tamamlar. `values` yalnız ≥ 10
hastada geçen değerleri ya da yüzdelikleri basar.

**Tek komut (1a + 1c + 1d, c1 ve c2, tek COPY bloğu):** aşağıdaki `values` sorgularının hepsi (1c'de lab kodu /
birimi ve vital değerleri, 1d'de tanı / gözlem / aile öyküsü kodları ve dapagliflozin + metformin satırlarının ilaç kodu; diğer ilaç kodları ingest bloğunda). Bulunamayan
tablo ya da sütun tek satırda "not available" yazar, diğerleri çalışır. `git pull` yoksa paketle:

```bash
python3 sandbox_bundle.py checks            # = bash tools/enclave.sh checks; yalnız biri: checks 1c
```

- [ ] **1a · Sigara kalemi.** Ingest SocialHistory'de birden çok kalem görürse durur, çünkü hangisinin sigara
  olduğunu bilmez. Önce bunlar:

  ```bash
  bash tools/enclave.sh values c1.SocialHistory SocialHabitCategory_Code
  bash tools/enclave.sh values c2.SocialHistory SocialHabitCategory_Code
  bash tools/enclave.sh values c1.SocialHistory SocialHabitQty_Description
  bash tools/enclave.sh values c2.SocialHistory SocialHabitQty_Description
  ```

  Ne çıkar: SOURCES `social_history` filtresi, `SMOKING_VALUES`, yoğunluk (D7: midwakh, shisha?).

- [ ] **1b · Demografi:**

  ```bash
  for s in c1 c2; do for c in Gender_Code EthnicGroup_Description Age; do bash tools/enclave.sh values $s.Patient $c; done; done
  ```

  Ne çıkar: `SEX_MAP`; etnik grup listesi (adım 2 kararı için); yaş dağılımı (QDiabetes 25–84, LPRS 40–75).

- [ ] **1c · Lab ve ölçüm birimleri.** Lab'lar `LabResultItem` view'ında, birim sütunuyla (`ResultValueUnits`;
  C1 DDL'i 2026-11-19). Adapter `mmol/mol` (HbA1c) ve `mmol/L` (glukoz) birimlerini kendisi dönüştürür. Bakılacak:
  test kodları LOINC mi, birim boş mu. Vital'lerde (Observation) birim sütunu yok; birim değer aralığından anlaşılır:

  ```bash
  for s in c1 c2; do bash tools/enclave.sh values $s.LabResultItem TestItemCode_Code --top 40; bash tools/enclave.sh values $s.LabResultItem ResultValueUnits --top 30; done
  ```

  ```bash
  for s in c1 c2; do for k in 39156-5 8302-2 3141-9; do bash tools/enclave.sh values $s.Observation ObservationValue --where "ObservationCode_Code = '$k'"; done; done
  ```

  Ingest bloğunun `lab (LabResultItem …)` bölümü tür | birim başına p5 / medyan / p95 değerini (≥ 10 hastalı
  grupta) ve adı glisemik görünüp kodu tanınmayan testleri gösterir. Birim boşsa ya da şüpheliyse:

  | Kod | Medyan buysa | Birim |
  |---|---|---|
  | 4548-4 HbA1c | ~5–8 | % (kod bunu varsayıyor) |
  | 4548-4 HbA1c | ~30–65 | mmol/mol → adapter'da dönüşüm gerekir |
  | 1558-6 açlık glukozu, 1521-4 OGTT | ~90–150 | mg/dL (kod bunu varsayıyor) |
  | 1558-6 açlık glukozu, 1521-4 OGTT | ~5–8 | mmol/L → dönüşüm gerekir |
  | 8302-2 boy | ~150–180 | cm (~1,5–1,8 ise metre) |
  | 3141-9 kilo | ~60–100 | kg |
  | 39156-5 BMI | ~25–32 | kg/m² |

  Bu kontrol neden kritik: glukoz mmol/L gelip birim sütunu boşsa kod onu mg/dL sanır. O zaman lab kanıtı
  "normal" çıkar ve C1'deki T2DM / prediyabet ayrımı bozulur.

- [ ] **1d · Kodlar: tanı, gözlem, aile öyküsü, ilaç:**

  ```bash
  for s in c1 c2; do bash tools/enclave.sh values $s.Diagnosis Diagnosis_Code --top 40; bash tools/enclave.sh values $s.Observation ObservationCode_Code --top 40; bash tools/enclave.sh values $s.FamilyHistory FamilyMember_Description; bash tools/enclave.sh values $s.FamilyHistory Diagnosis_Code; done
  ```

  Ne çıkar: Diagnosis_Code gerçekten ICD-10 mu, noktalı mı (`a99.9`); ObservationCode_Code LOINC mi
  (`9999-9`); `FH_RELATION_DEGREE`. Bu sorgular `checks` bloğunun 1d bölümünde de var.

  Sonuç (VM `checks`, 2026-11-20):
  - Diagnosis_Code ICD-10-CM, noktalı. C1'de birkaç kod noktayla bitiyor (`E11.9.`). C2'de birkaç hücrede
    virgülle 2–3 kod var. Adapter bu hücreleri böler, sondaki noktayı siler ve ingest bloğunun `diagnoses`
    bölümünde sayar.
  - ObservationCode_Code LOINC; yalnız 3141-9, 8302-2 ve 39156-5 geliyor.
  - FamilyMember: Father, Mother, Brother, Sister, Child, Parent. Hepsi birinci derece ve sözlükte var.
  - FamilyHistory.Diagnosis_Code: SNOMED, Z83.3, "Diabetes" metni ve yerel numaralar (60376773, 2, 82680 …).
    Yerel numaralar açıklama metninden tanınıyor. Ingest bloğu bunları `text only: Diagnosis_Code` satırlarında
    listeler.

  İlaç için ayrı komut gerekmez, ingest bloğunun **"drug → ATC"** bölümü yeterli (adım 3). C1 ve C2'de
  `DrugProduct_Code` var (VM ingest 2026-11-19: C2'de DDC ürün kodu 21.099, bilimsel kod 3.127 satır). Daha önce
  "C2'de kod yok" diye yazılan durum C3'e aitti: C2 ve C3 şemaları 1.1.0'dan önce yer değiştirmişti. Yalnız C3 ad
  yoluyla eşlenir: DDC ticari adı (marka kökü, ör. `CRESTOR 10 MG` → rosuvastatin) ya da adda geçen etken madde
  (K12). Kod biçimleri bloktaki `drug code format` satırlarında sayılır:

  | Biçim | Örnek | Ne yapılır |
  |---|---|---|
  | DDC ürün kodu | `9999-999999-9999` (tiresiz de olur) | DDC listesinden |
  | DDC bilimsel kod | `999999-999` | DDC listesinden |
  | 6 hane | `166101` | DDC bilimsel kodunun ilk 6 hanesi (etken madde + doz, form eki yok). Gruptaki ürünlerin hepsi aynı sınıftaysa koddan eşlenir. Sistemik ve yerel formlar karışıksa adla eşlenir |
  | `VMP<id>,<doz>,<form>` | `VMP4763,750 MG,TI` | Referansı yok, adla eşlenir |
  | Hep sıfır | `0000-000000-0000` | Boş kod sayılır, adla eşlenir |
  | ATC | `a99aa99` | Olduğu gibi |

  Kodu tanınan ama çalışma sınıfı olmayan satırlar blokta DDC etken maddesiyle listelenir (≥ 10 satır). Bunlar
  `DDC: not a study drug class` ve `DDC: non-systemic route` satırlarıdır. Kod sınıfsız, ad sınıflı çıkarsa iki
  durum var:
  - Ad bir çalışma ilacıyla başlıyorsa kod yanlış sayılır ve adın ATC'si kullanılır. Bu, ad ticari ad ya da marka
    olduğunda ya da ilk sayıdan önceki kelimelerde etken madde geçtiğinde olur, ör. `DAPAGLIFLOZIN 5 MG-METFORMIN
    …`. Satırlar `DDC code without study class → name used` olarak sayılır. Bu bir eşleme kuralıdır, klinik karar
    değildir. VM ingest 1.3.0'da C1 ve C2'de 134'er Xigduo XR 5/1000 satırı DDC'de kolekalsiferol kodu taşıyordu;
    A10 kanıtı bu yüzden düşüyordu.
  - Ad çalışma ilacını yalnız sonradan anıyorsa kod geçerli kalır, ör. `PANADOL 500 MG, TAKES METFORMIN`. Satırlar
    `name has one (code kept)` olarak sayılır.
  - Kodu yerel yollu bir çalışma ilacı olan satırlarda (göz damlası vb.) kod her zaman geçerlidir.

- [ ] **1e · Tarih biçimleri ve doluluk** (şekil `9999-99-99` = ISO):

  ```bash
  for t in Patient Diagnosis Observation LabResultItem SocialHistory FamilyHistory Medication; do bash tools/enclave.sh columns c1.$t; done
  ```

- [ ] **Blokları gönder → adapter güncellenir, push edilir → VM'de `git pull --ff-only`.**

### 2 · Karar: etnisite kaynağı (D6, medikal ekip)

Durum: view'larda uyruk sütunu yok. Varsayılan `ethnicity_source = "nationality"` (2026-11-13 kararı) ile
herkesin etnisitesi boş kalır. Sonuç: QDiabetes herkesi beyaz referans ("WhiteNA") sayar, LPRS hiç
hesaplanmaz. Bu durumda C1 Leicester duyarlılığı çıkmaz.

- [ ] Seçenek (a): `EthnicGroup_Description` kullanılır (`ethnicity_source = "ethnicity"`). 1b'deki değerlerin
  QDiabetes kategorisine ve LPRS beyaz / BME ayrımına eşlenmesini medikal ekip onaylar.
- [ ] Seçenek (b): DHA'dan uyruk sütunu istenir. Adapter hazır: `Nationality` sütunu gelince otomatik okunur.
- Karar gelene kadar iki yol da denenebilir. Varsayılan değişmez; ikinci run duyarlılık olarak audit'e
  girer (adım 5).

### 3 · Ingest: IRIS → snapshot + kanonik veri (~10 dk)

- [ ] Çalıştır:

  ```bash
  bash tools/enclave.sh run ingest --cohorts c1 c2
  ```

  Beklenen: `success`. C1 ≈ 2.600, C2 ≈ 2.600 hasta (Data availability). Blokta bakılacaklar: `unmapped
  values`, düşen satırlar (diyabet dışı aile öyküsü, kullanılamayan yaş), `unparseable_*` tarihler ve
  **"drug → ATC" bölümü** (K12):
  - `drug → ATC method`: C1'de çoğunluk `DDC code` olmalı; `code not ATC/DDC` çoksa kod biçimi farklıdır
    (`drug code not ATC/DDC` satırlarındaki örneklere bak).
  - `DDC: not a study drug class` ve `rows dropped` normaldir (antibiyotik, vitamin vb. çalışma sınıfı değil).
  - C2: `ATC ← drug_name` eşleşmeleri doğru mu; `drug_name without study drug class` listesinde bilinen bir
    diyabet / tansiyon / statin / steroid / antipsikotik markası varsa bloğu gönder (eşleme genişletilir).

- [ ] Eşlenemeyen değer varsa bloğu gönder. Sözlük güncellenip `git pull` yapılınca IRIS'e gitmeden
  snapshot'tan tekrarla:

  ```bash
  bash tools/enclave.sh run ingest --snapshot --cohorts c1 c2
  ```

### 4 · NB0: veri profili

- [ ] Çalıştır:

  ```bash
  bash tools/enclave.sh run nb0
  ```

  Bakılacaklar: şema ERROR = 0, hacim, Framework Match (değişken bazında Match / Partial / Absent: `nb00/framework_variables.csv`; kod-grubu tablosu `framework_match.csv` yanında), eşlenemeyen kodlar.
  Blokta ayrıca: `nb00/demographics.csv` (yaş medyan / IQR, `age_outside_25_84_n` / `_pct` = QDiabetes yaş
  aralığı 25 ≤ yaş < 85 dışında kalanlar — QDiabetes bunlarda hesaplanmaz; `age_missing_n`, `male_pct`) ve
  `nb00/facility_representation.csv` (adapter tesis eşlemiyor → tablo yerine tek satır not; DHA sorusu).
  Ayrıntı için:

  ```bash
  bash tools/enclave.sh show nb0 nb00/core_variable_completeness.csv
  ```

  ```bash
  bash tools/enclave.sh show nb0 nb00/ethnicity_categories.csv
  ```

### 5 · NB1: C1 / C2 fizibilite

- [ ] Çalıştır:

  ```bash
  bash tools/enclave.sh run nb1
  ```

  Blokta: C1–C2 seçilim etkisi (`nb01/selection_effect_smd.csv` kısa biçim: variable, c1, c2, smd, `|smd|>0.1`;
  c1 / c2 = ortalama, ikili değişkende pay 0–1), skor hesaplanabilirliği, eksiklik nedenleri, C1 yakalama oranı,
  skor özeti, birlikte tamlık. Yakalama oranı eşik seçilene kadar "Pending" kalır: QDiabetes için D5, LPRS için
  D23. Medikal ekip eşiği dağılıma bakarak seçer; dağılım `score_summary` içinde. Ayrıntı için:

  ```bash
  bash tools/enclave.sh show nb1 nb01/ethnicity_mapping.csv
  ```

- [ ] D6 kararı gelmediyse, etnisite alanıyla duyarlılık run'ı:

  ```bash
  SANDBOX_PARAMS='{"ethnicity_source": "ethnicity"}' bash tools/enclave.sh run nb1
  ```

- Tamlık tablolarını okuma (`completeness_by_variable`, `joint_completeness`, `ethnicity_source_compare`; NB0'da
  `core_variable_completeness`, `joint_completeness`):
  - `measure`: `recorded` = değer kayıtta var (cinsiyet, yaş, etnisite, BMI, sigara). `present_absent` = KVH,
    hipertansiyon ve (D17 `c1_require_fh_record` False iken) aile öyküsü: kayıt yoksa "yok" sayılır, bu yüzden
    %100 tanım gereğidir, doluluk ölçmez; `meets_90` bu satırlarda `-`. KPI'ın en düşük değeri yine bunları %100
    sayar.
  - `family_history_recorded`: aile öyküsünün gerçek doluluğu (FamilyHistory kaydı ya da Z83.3).
  - `meets_90`: `recorded` değişken için tamlık ≥ %90.
  - Birlikte tamlık: `joint_core7` = etnisite hariç 7 değişken, `joint_core8` = core-7 + etnisite. core-7 etnisite
    kaynağına bağlı değildir; `ethnicity_source_compare` core-8'i iki kaynakla (uyruk / EthnicGroup) yan yana verir.
  - Sayı < 10 → "<10"; sayısı ya da eksik sayısı < 10 olan oran "suppressed (<10)". Bloktaki her oran için aynı
    kural (sigara kaynağı, eksiklik nedenleri, hesaplanabilirlik, demografi, KPI değerleri); SMD tablosunda gizli
    payın SMD'si de gizlenir, `|smd|>0.1` bayrağı kalır. < 10 değer üzerinden medyan / çeyrek de gizlenir.

### 6 · KPI (Faz 1'de kısmi)

- [ ] Çalıştır:

  ```bash
  bash tools/enclave.sh run kpi
  ```

- Faz 1'de NB1'den dolan satırlar: Joint Completeness (QDiabetes / LRS; C1 ve C2 için % ve N, skor
  hesaplanabilirliği notta) ve Sensitivity (C1 yakalama oranı; eşik yoksa Pending, C1–C2 seçilim etkisi notta).
  Sensitivity hedefe (≥ %70) göre Met / Not Met diye değerlendirilmez; birincil skor ve referans tarihi önceden
  belirlenmedi. Specificity, NPV / PPV, AUROC, C-Index, kalibrasyon ve uyarı oranı Faz 2'de (C3, NB2) dolar.
- Data Completeness for Required Variables: değer ve Met kararı değişmedi (8 çekirdek değişkenin en düşüğü, NB0).
  Not (blokta ayrı satır): en zayıf değişken, etnisite hariç en zayıf değişken ("Without ethnicity"), birlikte
  tamlık core-7 (% ve N) ve tanım gereği %100 olan `present_absent` değişkenler.

### 7 · Jupyter'de inceleme (isteğe bağlı)

- [ ] Notebook'ları üret ve aç:

  ```bash
  python3 tools/py2ipynb.py notebooks/00_data_profile.py notebooks/01_c1_c2_feasibility.py
  python3 -m jupyterlab --no-browser --ip 127.0.0.1 --port 8888 --ServerApp.port_retries=0 --IdentityProvider.token=sandbox
  ```

- VM'de tarayıcı açılmıyor ve IntelliJ'in kendi (Managed) sunucusu "Could not find Jupyter notebook session
  factory" veriyor (2026-11-19). Çalışan yol: sunucuyu yukarıdaki gibi terminalde başlat; IntelliJ'de notebook
  üst çubuğu → sunucu menüsü → Configured / External Server: `http://127.0.0.1:8888/?token=sandbox` (token sabit,
  yalnız 127.0.0.1; adres bir kez yazılır). Terminal açık kalır; iş bitince Ctrl+C (açık run'lar audit'te kapanır).
- Notebook'lar IRIS'i değil, ingest'in yazdığı `data/canonical/nabidh/` klasörünü okur; önce adım 3 yapılmış
  olmalı.
- `SANDBOX_SOURCE` `.env`'den gelir (adım 0). `.env` yoksa sunucuyu `SANDBOX_SOURCE=nabidh python3 -m jupyterlab …`
  ile başlat ya da en üste `%env SANDBOX_SOURCE=nabidh` hücresi ekle.
- Jupyter da çalışmazsa tarayıcısız: `python3 -m IPython -i notebooks/01_c1_c2_feasibility.py` (notebook çalışır,
  değişkenler istemde kalır; grafikler `outputs/<run_id>/` altında PNG).
- Kaynak `.py` dosyasıdır; `.ipynb`'de yapılan değişiklik yeniden üretilince kaybolur.

### 8 · Çıktı çıkarma

- [ ] Enclave'den yalnız `COPY` blokları ve küçük hücreleri bastırılmış (< 10 → "<10") özet tablolar
  çıkar. DHA'nın onayı gerekir.
- `data/`, snapshot'lar, hasta kimliği içeren dosyalar ve ekran görüntüleri çıkmaz.

## Gün içinde sorulacaklar

**DHA / NABIDH**
- [ ] `Patient.Age` hangi güne göre hesaplandı? Doğum yılı ya da tarihi verilebilir mi? (D24)
- [ ] Uyruk sütunu verilebilir mi? (D6)
- [ ] Observation (vital: BMI, boy, kilo) için birim sütunu verilebilir mi? (Lab birimi LabResultItem'da var.)
- [ ] LabResultItem.TestItemCode_Code LOINC mi? C2 / C3 şemalarında da LabResultItem var mı?
- [ ] C1 / C2 `DrugProduct_Code` içindeki 6 haneli ve `VMP<id>,<doz>,<form>` kodlar hangi sistemden geliyor? C3
  Medication'da kod sütunu verilebilir mi? (K12)
- [ ] C1 "complete case" tanımı nedir? C2'nin N'i ve örnekleme yöntemi nedir? C1 ile C2 örtüşüyor mu?
- [ ] Veri çekim tarihi nedir? (Referans tarihi "veri sonu" için, D22.)
- [ ] Çıktı çıkarma kuralları: küçük hücre eşiği, figür onayı, izinli formatlar.
- [ ] C1 Encounter view'ı için SELECT yetkisi (Faz 1'de gerekmiyor).
- [ ] Faz 2 için: C3 teslimi takipte diyabet gelişen hastaları da içeriyor mu?

**Medikal ekip**
- [ ] D6: etnisite kaynağı ve eşlemesi (adım 2).
- [ ] D5: QDiabetes eşiği. D23: LPRS eşiği. C1 duyarlılığı bu ikisine bağlı.
- [ ] D22: birincil referans tarihi (veri sonu mu, ilk kanıt günü mü).
- [ ] D7: yoğunluğu belirtilmemiş "current" sigara. D17: aile öyküsü kaydı olmaması negatif mi sayılır?
- [ ] D26: ilaç sınıfı sınırları — lurasidon / ziprasidon atipik antipsikotik sayılsın mı; obezite GLP-1'i
  (Saxenda, Wegovy) diyabet ilacı sayılsın mı.

## Faz 1 "tamam" tanımı

- [ ] Ingest, NB0 ve NB1 run'ları `success`; şema ERROR = 0; audit %100.
- [ ] Değer raporlarında (ingest, NB0 `unmapped_codes`) eşlenemeyen önemli değer kalmadı.
- [ ] C1 ve C2: 8 çekirdek değişkenin tamlığı, QDiabetes ve LPRS hesaplanabilirliği, eksiklik nedenleri.
- [ ] C1 yakalama oranı: eşikler (D5, D23) seçildiyse oranlar, seçilmediyse "Pending" ile birlikte dağılım.
- [ ] C1–C2 SMD tablosu (seçilim etkisi).
- [ ] Etnisite eşleme tablosu medikal ekibe iletildi (D6).
- [ ] Enclave'den çıkan tabloların küçük hücre kontrolü yapıldı ve DHA onayı alındı.

## Başvuru: skor girdileri ve kaynakları (HSAA view'ları)

| Girdi | QDiabetes | LPRS | View / sütun | Not |
|---|---|---|---|---|
| Cinsiyet | ✓ | ✓ | Patient.Gender_Code | `SEX_MAP` değerlerle teyit (1b) |
| Yaş | ✓ | ✓ | Patient.Age | Doğum tarihi yok → yaştan yaklaşık türetilir (D24, ±6 ay) |
| Etnik grup | ✓ | ✓ (beyaz / BME) | Patient.EthnicGroup_Description | Uyruk yok → D6 |
| BMI | ✓ | ✓ | Observation 39156-5 → boy 8302-2 + kilo 3141-9 → Z68 | Birim yok (1c) |
| Sigara | ✓ | — | SocialHistory (kalem + Qty) + F17.2 / Z72.0 / Z87.891 | Kalem filtresi (1a) |
| Aile öyküsü (diyabet) | ✓ | ✓ | FamilyHistory (Diagnosis_Code / _Description, FamilyMember) + Z83.3 | Yalnız birinci derece pozitif |
| KVH | ✓ | — | Diagnosis I20–I25, I50, I6x, G45 | — |
| Hipertansiyon | tanı ve ilaç | yalnız ilaç | Diagnosis I10–I16 + Medication (DDC → ATC) | C1 / C2 DDC kodundan; kod tanınmazsa ve C3'te addan (1d, K12) |
| Statin, kortikosteroid, atipik antipsikotik | ✓ | — | Medication (DDC → ATC: C10AA, H02AB, N05AH / AX / AL) | Yalnız sistemik yol; D26 |
| Glisemik lab (yalnız statü, model girdisi değil) | — | — | LabResultItem 4548-4, 1558-6, 1521-4 (TestItemCode_Code) | Birim `ResultValueUnits`; LOINC teyit (1c) |

NABIDH Data availability listesindeki hasta sayıları ve oranları (C1 = 2.600, C2 = 2.600, C3 = 1.000):

| Kalem | Kod / kaynak | C1 | C2 | C3 |
|---|---|---|---|---|
| Tip 2 diyabet | E11 | 1.221 (%47,0) | 1.408 (%54,2) | 322 (%32,2) |
| Prediyabet | R73 | 2.180 (%83,8) | 1.720 (%66,2) | 580 (%58,0) |
| Hipertansiyon | I10–I16 | 1.015 (%39,0) | 1.199 (%46,1) | 384 (%38,4) |
| KVH | I20–I25, I50, I6x, G45 | 507 (%19,5) | 447 (%17,2) | 208 (%20,8) |
| Obezite / BMI kodu | E66, Z68 | 557 (%21,4) | 313 (%12,0) | 160 (%16,0) |
| Sigara (tanı) | F17.2, Z72.0, Z87.891 | 15 (%0,6) | 15 (%0,6) | <10 |
| Diyabet aile öyküsü (tanı) | Z83.3 | 309 (%11,9) | 133 (%5,1) | 50 (%5,0) |
| Tip 1 diyabet (0 olmalı) | E10 | 0 | 0 | 0 |
| HbA1c | LOINC 4548-4 | 462 (%17,8) | 217 (%8,3) | 1.000 (%100) |
| Açlık glukozu | LOINC 1558-6 | 923 (%35,5) | 736 (%28,3) | 500 (%50,0) |
| OGTT 2 saat | LOINC 1521-4 | 17 (%0,7) | 30 (%1,2) | 31 (%3,1) |
| BMI | LOINC 39156-5 | 2.600 (%100) | 336 (%12,9) | 186 (%18,6) |
| Boy | LOINC 8302-2 | 2.600 (%100) | 2.471 (%95,0) | 976 (%97,6) |
| Kilo | LOINC 3141-9 | 2.600 (%100) | 2.515 (%96,7) | 983 (%98,3) |
| Sigara durumu | SocialHistory | 2.600 (%100) | 1.483 (%57,0) | 766 (%76,6) |
| Diyabet aile öyküsü | FamilyHistory | 2.600 (%100) | 419 (%16,1) | 168 (%16,8) |
| İlaç order'ları | Medication | 1.557 (%59,9) | 1.513 (%58,2) | 496 (%49,6) |
| Encounter | Encounter | — | — | 1.000 (%100) |

Beklentiler: C2'de sigara kaydı %57 (D8: kayıt yok = bilinmiyor). Bu yüzden C2'de QDiabetes en fazla
yaklaşık %57 hastada hesaplanabilir. Aile öyküsü C2'de yalnız %16 kayıtlı; kaydı olmayanların nasıl
sayılacağı D17'ye bağlı. Bel çevresi teslim edilmiyor, bu yüzden Leicester skoru LPRS (K-LRS).
