# AGENTS.md — Albert Health × DHA Health Data Sandbox (S-2025-Y4B7N9)

Bu dosya ekip ve kodlama asistanları için projenin çalışma kurallarıdır. Her oturumda önce bunu, sonra
`docs/gap.md`'yi oku.

## Proje ne yapıyor
QDiabetes-2018 Model A ve Leicester Risk Score'un (LRS) UAE nüfusunda (NABIDH verisi, DHA Secure
Data Enclave) değerlendirilmesi; gerekirse UAE'ye özgü invaziv olmayan model.

| Adım | Study Flow | Kohort | Ne | Kod |
|---|---|---|---|---|
| 0 | — | C1, C2, C3 | Veri profili, şema doğrulama, tamlık, istenen-vs-gelen kodlar | `notebooks/00_data_profile.py` |
| 1 | 1. ve 2. basamak | C1, C2 (yalnız T2DM + prediyabet) | **C1 birincil amaç:** bilinen pozitiflerde skorların yakalama oranı (duyarlılık). **C2:** tamlık. Ayrıca C1–C2 seçilim etkisi, skor hesaplanabilirliği. Negatif vaka yok → **yalnız duyarlılık; özgüllük/ayrım/kalibrasyon YOK** | `notebooks/01_c1_c2_feasibility.py` |
| 2 | 3. basamak | C3 (başlangıçta non-diyabetik) | Incident benchmark: QDiabetes + LRS, Kol 1 (olduğu gibi) vs Kol 2 (recalibration) | `notebooks/02_c3_benchmark.py` |
| 3 | 4. basamak | yeni NABIDH teslimi | UAE'ye özgü model (lab'sız) — **koşullu**, yalnızca önceden tanımlı performans eşiği tetiklerse; yürütülürse NABIDH'ten yeni veri istenir | (yok) |

Kaynak spesifikasyonlar (Claude Project "Sandbox Experiment" içinde): MVP Dataset v1.0, Interim Data
Assessment (C1/C2), Non-Diabetic Cohort Data Specification v2 (C3), Study Flow Overview,
KPI & Graduation Framework (Precoh/DFF v4 → Albert V2.0).

## Kesin kurallar (ihlal etme)
1. **Hasta verisi git'e girmez.** `data/` ve `outputs/` git dışı. Gerçek veya sentetik CSV,
   hasta düzeyi tablo, ekran görüntüsü commit'lenmez. Commit öncesi `git status` kontrol et.
2. **Enclave = offline.** Bağımlılıklar yalnızca `numpy`, `pandas`, `matplotlib` (Python ≥ 3.10).
   scipy / sklearn / lifelines / statsmodels EKLEME. Ağ çağrısı (HTTP, telemetri, indirme) yazma.
   Tek istisna: `src/sandbox/io/iris.py` DHA içindeki InterSystems IRIS'e yalnızca SELECT için bağlanır;
   sürücü (`intersystems-irispython`, yedek `pyodbc`) yalnızca orada ve tembel import edilir — testler ve
   analiz kodu sürücüsüz çalışır. Bağlantı şifresi git'e, run configuration'a, audit'e girmez; yerelde git
   dışı `.env` (repo kökü, `.gitignore`) ya da `~/.nabidh_iris`'te durabilir. `.env`'i `import sandbox` yükler
   (`envfile.py`; ortamdaki değer kazanır, audit'e yalnız anahtar adları).
   Kod hem pandas 2.x hem 3.x ile çalışmalı (ör. `Series.reset_index(names=)` pandas 2'de yok).
   Kurulum tek mekanizma: projenin Python'una `requirements.txt` (proje) + `requirements-explore.txt` (keşif;
   kod import etmez) bir kez kurulur — VM'de `/usr/bin/python3`'e `--user` ile (2026-11-18); proje venv
   kurmaz. Komutlar ve run configuration'lar Python yolu yazmaz (`python` / IntelliJ proje SDK'sı).
3. **Lab değerleri asla model girdisi değildir.** Yalnızca uygunluk / outcome tanımında kullanılır.
4. **Her çalıştırma audit'lenir** (KPI: Audit Trail %100, Critical). Notebook/araçlar `audit.Run`
   açar; tüm çıktılar `run.save_table / save_figure / save_json / register_output` ile yazılır;
   girdi dosyaları `run.add_inputs` ile hash'lenir; `run.finish()` ile kapanır. `outputs/` dışına
   yazma. `outputs/audit/audit_log.jsonl` append-only — elle düzenleme, silme.
5. **Parametreler tek yerde:** `src/sandbox/config.py → PARAMS`. Notebook içinde sabit eşik/pencere
   yazma. Duyarlılık çalıştırmaları `SANDBOX_PARAMS='{"key": value}'` ortam değişkeniyle (audit'e girer).
6. **Klinik kararlar kodlama asistanının/geliştiricinin değildir.** `[DECISION PENDING]` işaretli parametrelerin
   varsayılanını medikal ekip onayı olmadan değiştirme. Karar gelince: config'i güncelle, yorumdaki
   işareti `[DECIDED: <tarih>, <kim>]` yap, `docs/gap.md` §5 "Kararlar" bölümüne işle.
7. **Kaynak formatı yalnızca adapter'da.** Analiz kodu sadece kanonik şemayı okur
   (`src/sandbox/io/schema.py`). NABIDH formatı / IRIS şeması değişirse yalnızca `io/adapters/nabidh.py`
   (SOURCES, IRIS_COHORTS ve değer sözlükleri) değişir. Ham dosya ve IRIS aynı SOURCES eşlemesinden geçer.
8. **Çıktı ifşa kontrolü:** enclave'den çıkacak tablolarda sayımlar `sdc.suppress_small_counts`
   ile (<10 → "<10"). Hasta kimliği içeren dosya enclave dışına çıkmaz.
9. **Push yok:** commit serbest, `git push` yalnızca kullanıcı isteyince.

## Kod düzeni
```
src/sandbox/
  config.py            PARAMS + yollar
  envfile.py           git dışı .env → os.environ (import sandbox'ta; şifre, SANDBOX_SOURCE)
  codelists.py         ICD-10 / SNOMED / ATC / LOINC + etken madde → ATC + uyruk → etnik grup → QDiabetes / LRS
  io/schema.py         kanonik şema (6 tablo), okuma/yazma, validate()
  io/adapters/         synthetic.py, nabidh.py (SOURCES: Patient, tanı, Observation, LabResultItem, SocialHistory,
                       FamilyHistory, Medication, Encounter → kanonik; load = ham dosya, load_iris = IRIS),
                       ddc.py (Dubai Drug Code ürün kodu / ilaç adı → etken madde → ATC; yerel yol sayılmaz)
  reference/ddc.csv.gz DHA DDC listesinin sade hâli (tools/build_ddc_reference.py; hasta verisi değil)
  io/iris.py           IRIS bağlantısı (jdbc:IRIS:// dizesi, ~/.nabidh_iris), SELECT koruması, sorgu → metin
                       tablosu; prova için SQLite stand-in
  io/explore.py        terminalden IRIS keşfi (INFORMATION_SCHEMA / SQLite): şema, tablo, sütun profili, değer
                       dağılımı; ifşa kuralları (hassas ad / kimlik gibi sütunda değer yok, değer ≥ 10 hastada)
  phenotype.py         glisemik olaylar, DM/prediyabet kanıtı, 8 çekirdek değişken snapshot
  breakdowns.py        C1/C2 kırılımları: tedavi edilen HT (tanı / ilaç / ikisi), QDiabetes sigara seviyesi, vital
                       makul aralık dışı (aralıklar phenotype.VITAL_PLAUSIBLE_RANGE)
  cohorts.py           positive_pool, build_c1_c2, build_c3 (v2 kuralları + washout)
  scores/              qdiabetes2018a.py (CRAN QDiabetes 1.0-2 katsayıları), lrs.py (Leicester varyant
                       seçici `lrs_variant` + LRA 2010), lprs.py (Leicester Practice Risk Score 2012,
                       bel çevresiz — varsayılan, K-LRS)
  metrics.py           C-index, zaman-bağımlı AUROC (IPCW), KM, kalibrasyon, eşik metrikleri, C1 yakalama oranı (Wilson), bootstrap
  recalibration.py     Kol 2: baseline survival yeniden tahmini (cinsiyete göre)
  kpi.py               KPI Framework satırları + actual/met + markdown rapor
  audit.py, sdc.py
notebooks/*.py         percent format (# %%). .ipynb türetilir (tools/py2ipynb.py), commit'lenmez
tools/                 check_environment, ingest_nabidh, make_nabidh_dryrun, build_synthetic_cohorts, kpi_report,
                       build_evidence_package, build_ddc_reference, positive_control, py2ipynb, enclave.sh + enclave.py
                       (terminal-only enclave: req R1–R9, iris-setup, schemas/tables/columns/values, checks, mapping, run (all = Faz 1 zinciri);
                       çıktı COPY bloğu), build_bundle (git pull'suz VM için enclave + Faz 1 adımları tek dosyada,
                       dist/sandbox_bundle.py)
docs/                  gap.md (açık işler + kararlar), faz1_c1_c2.md (Faz 1 enclave yapılacaklar listesi),
                       enclave_terminal.md (komut rehberi), evidence_package/ şablonları
tests/                 unittest (pytest yok)
logs/enclave/          VM'den taşınan COPY blokları, günde bir dosya (<UTC tarih>.log); logs/archive/ eski elle kopyalar
.run/                  IntelliJ run configuration'ları (repoda)
```
Notebook başlığı her zaman aynı ROOT bloğuyla başlar (cwd'den yukarı `src/sandbox` arar).
Kod, yorumlar ve program çıktısı (print, hata mesajı, rapor / tablo başlığı, COPY bloğu) İngilizce;
dokümanlar (`docs/*.md`, `README.md`, `VM_KOMUTLAR.md`) Türkçe kalabilir, ama alıntıladıkları çıktı koddaki
İngilizce metinle aynı olmalı.

## Çalıştırma
```bash
# python = paketlerin kurulu olduğu Python (bu makinede: .venv/bin/python)
python -m pip install -r requirements.txt -r requirements-explore.txt   # bir kez (VM'de: python3 -m pip install --user …)
python tools/check_environment.py              # ortam kontrolü (VM'de: --iris --github); FAIL → çıkış 1
python -m unittest discover -s tests -v
python tools/build_synthetic_cohorts.py        # data/synthetic/raw → data/canonical/synthetic/{c1,c2,c3}
python notebooks/00_data_profile.py
python notebooks/01_c1_c2_feasibility.py
python notebooks/02_c3_benchmark.py            # SANDBOX_BOOTSTRAP_REPS=100 ile hızlı
python tools/kpi_report.py
python tools/build_evidence_package.py
# NABIDH adapter provası: make_nabidh_dryrun → ingest_nabidh --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
#   → SANDBOX_SOURCE=nabidh_dryrun ile NB0/NB1/NB2
#   IRIS yolu provası: ingest_nabidh --input iris --iris-sqlite data/nabidh_dryrun/iris --source nabidh_dryrun_iris
# Enclave: tools/ingest_nabidh.py --input iris (IRIS → data/nabidh_iris/raw/<kohort> snapshot → data/canonical/nabidh/)
#   ya da ham dosyadan (data/nabidh/raw/<kohort>); sonra SANDBOX_SOURCE=nabidh
# Enclave: repo kökünde bash tools/enclave.sh <komut> (docs/faz1_c1_c2.md, docs/enclave_terminal.md). Bloğa (COPY
#   START/END) yalnız meta veri / özet girer; yeni komut eklerken bu kuralı koru, tests/test_enclave.py'ye vaka ekle
# git pull yoksa: python tools/build_bundle.py (commit'ten sonra) → dist/sandbox_bundle.py elle VM'e →
#   python3 sandbox_bundle.py bundle-info → run ingest --cohorts c1 c2 / run nb0 / nb1 / kpi (docs/enclave_terminal.md §1)
# Her blok (yalnız COPY START … END, ekran çıktısı değil) repo kökünde logs/enclave/<UTC tarih>.log'a eklenir; VM'de
#   commit'lenmez — dosya elle kopyalanıp Mac'teki repoda aynı adla commit'lenir. logs/archive/ = eski elle kopyalar
```

## Değişiklik yaparken
- Kohort / outcome / prediktör kuralı değişirse: `tests/` altına el yapımı vaka ekle (tests/fixtures.py).
- Adapter / ingest davranışı değişirse `io/adapters/nabidh.py → INGEST_VERSION`'ı artır ve kaydına bir satır ekle
  (MAJOR kanonik şema · MINOR eşleme / sözlük / işleyici · PATCH yalnız rapor). Sürüm her COPY başlığında,
  ingest özetinde, audit'te ve kanonik `<kohort>/ingest.json`'da görünür; NB blokları okudukları sürümü basar.
- Skorlayıcı değişirse: `tests/test_scores.py` referans vektörleri (CRAN QDiabetes README değerleri) geçmeli.
- Metrik eklerken: küçük, elle doğrulanabilir örnekle test (sansürsüzde C-index = AUROC gibi).
- Uçtan uca: build → NB0 → NB1 → NB2 → kpi_report hatasız; her run manifest'i `status: success`.
- Commit mesajı: ne + neden; tek konu. Hasta verisi yok.
