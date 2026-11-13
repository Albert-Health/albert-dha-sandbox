# Albert Health × DHA Health Data Sandbox — Analiz Kodu

Başvuru: **S-2025-Y4B7N9** · QDiabetes-2018 (Model A) ve Leicester Risk Score'un UAE (NABIDH) verisinde değerlendirilmesi.

> Bu kod yalnızca DHA Secure Data Enclave içinde gerçek veriyle çalıştırılır. Repoda **hiçbir hasta verisi yoktur** (gerçek veya sentetik); `data/` ve `outputs/` git dışıdır.

## Yapı

```
data/
  synthetic/raw/          sentetik test verisi (git dışı)
  nabidh/raw/             enclave'de DHA'nın verdiği dosyalar (git dışı, dokunulmaz)
  canonical/<source>/<c1|c2|c3>/   adapter çıktısı — kanonik şema (git dışı)
src/sandbox/
  config.py               tüm parametreler (lookback, horizon, eşikler, cap, seed)
  codelists.py            ICD-10 / SNOMED / ATC / LOINC listeleri
  io/schema.py            kanonik şema, okuma/yazma, doğrulama
  io/adapters/            synthetic.py, nabidh.py (kaynak → kanonik)
  phenotype.py            glisemik ölçümler, DM/prediyabet kanıtı, 8 çekirdek değişken snapshot
  cohorts.py              pozitif havuz (C1/C2), C3 (v2 incident kuralları, washout)
  scores/qdiabetes2018a.py  QDiabetes-2018 Model A (CRAN QDiabetes 1.0-2 katsayıları; referans testli)
  scores/lrs.py           Leicester Risk Assessment (0–47 puan, ≥16 yüksek risk)
  metrics.py              KM, Harrell C, IPCW zaman-bağımlı AUROC, O:E, kalibrasyon, eşik metrikleri, bootstrap
  recalibration.py        Kol 2: cinsiyete göre katmanlı baseline (+eğim) recalibration
  kpi.py                  KPI tablosu + graduation ön değerlendirmesi
  audit.py                audit trail (run log, kod/veri hash) — KPI: Audit Trail %100
  sdc.py                  küçük hücre bastırma
notebooks/                .py (percent format) — Jupyter/VS Code'da hücre hücre açılır
tools/                    ingest_nabidh.py (NABIDH ham → kanonik), make_nabidh_dryrun.py (prova verisi),
                          build_synthetic_cohorts.py, kpi_report.py, build_evidence_package.py,
                          positive_control.py, py2ipynb.py
docs/evidence_package/    model card, validasyon, veri kalite, kohort türetme şablonları
tests/                    unittest (pytest gerekmez)
outputs/                  <run_id>/... + audit/audit_log.jsonl (git dışı)
archive/                  önceki prototip notebook ve raporlar
```

## Akış

| Adım | Notebook | Kohort | Çıktı / KPI |
|---|---|---|---|
| — | `tools/ingest_nabidh.py` | C1, C2, C3 | NABIDH ham → kanonik şema, şema kontrolü, kaynak değer dağılımları (eşleme sözlükleri için) |
| 0 | `00_data_profile.py` | C1, C2, C3 | şema doğrulama, tamlık, istenen-vs-gelen kod eşlemesi · *Data Completeness, Framework Match* |
| 1 | `01_c1_c2_feasibility.py` | C1, C2 | birlikte tamlık, C1–C2 seçilim etkisi, skor hesaplanabilirliği (kesitsel) |
| 2 | `02_c3_benchmark.py` | C3 | QDiabetes + LRS: C-index, AUROC, kalibrasyon, eşik metrikleri, recalibration · *klinik/teknik KPI'lar* |
| 3 | `03_uae_model.py` | C3 | koşullu — yalnızca recalibration yetersizse (henüz yok) |
| — | `tools/kpi_report.py` | — | KPI tablosu + iki haftalık rapor (`outputs/<run_id>/kpi/kpi_report.md`) |
| — | `tools/build_evidence_package.py` | — | evidence package klasörü + hash listesi + kontrol listesi |
| — | `tools/positive_control.py` | C3 | bilinen etnisite etkisi enjekte → NB2 alt-grup O:E yakalıyor mu? |

Ortam değişkenleri (hepsi audit manifest'ine yazılır): `SANDBOX_SOURCE` (synthetic / nabidh / synthetic_pc),
`SANDBOX_PARAMS` (JSON, config override — duyarlılık analizleri), `SANDBOX_BOOTSTRAP_REPS`.

## Parametreler ve kararlar (`src/sandbox/config.py`; kayıt: `docs/gap.md` §5)

| Parametre | Değer | Konu |
|---|---|---|
| `outcome_washout_days` | 90 **[KARAR]** | index'e ≤ 90 gün olay = prevalent; 0 = v2 duyarlılığı |
| `horizon_years` / `_fallback` | 3 / 5 **[KARAR — şimdilik]** | birincil / ikincil horizon |
| `predictor_lookback_days` | 365 **[KARAR]** | prediktör penceresi; 730 duyarlılık (.run 4c) |
| `qd_force_reduced_model` | True **[KARAR]** | 7 Model A prediktörü = 0 (kapsam dışı) |
| `qd_townsend` | 0.0 **[KARAR]** | kapsam dışı |
| `qd_smoking_current_category` | 3 (moderate) | yoğunluksuz "current" sigara [karar bekliyor] |
| `qd_missing_smoking_as_non` | False **[KARAR]** | sigara kaydı yok = bilinmiyor |
| `qd_baseline_time_scaling` | power | 10 y dışı horizon için S0(t)=S0(10)^(t/10) (Kol 1) [karar bekliyor] |
| `qd_risk_threshold_pct` | None **[KARAR — şimdilik]** | sens/spec/PPV/alert rate eşiği; KPI'lar "Pending" |
| `lrs_unknown_ethnicity_as_missing` | True | etnisite kayıtsızsa LRS hesaplanmaz |
| `ethnicity_source` | nationality | **[KARAR: 2026-11-13]** etnik grup uyruktan türetilir |
| `codelists.NATIONALITY_COUNTRIES` → `NABIDH_TO_QDIABETES` | BAE/Körfez/Arap → Other | uyruk → etnik grup → QDiabetes eşlemesi |
| LRS madde puanları | Gray 2010 | birincil makaleden teyit |

## Kurulum ve çalıştırma

```bash
python -m pip install -r requirements.txt        # enclave'de offline wheel ile
python -m unittest discover -s tests -v          # kural testleri

# Sentetik test verisiyle uçtan uca:
python tools/build_synthetic_cohorts.py          # data/synthetic/raw → data/canonical/synthetic/{c1,c2,c3}
python notebooks/00_data_profile.py

# NABIDH adapter provası (sentetik veri NABIDH teslim biçiminde):
python tools/make_nabidh_dryrun.py
python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun
SANDBOX_SOURCE=nabidh_dryrun python notebooks/00_data_profile.py

# Enclave'de: ham dosyalar data/nabidh/raw/<c1|c2|c3>/ altına; src/sandbox/io/adapters/nabidh.py içindeki
# SOURCES'ta dosya/sütun adlarını gerçek adlarla değiştir, sonra:
python tools/ingest_nabidh.py                    # → data/canonical/nabidh/ + outputs/<run_id>/ingest/
SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py
python tools/py2ipynb.py notebooks/00_data_profile.py   # istenirse .ipynb üretir
```

## IntelliJ IDEA ile çalışma

1. **Python ortamı (bir kez):** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt jupyter ipykernel`
2. **SDK (bir kez):** *File → Project Structure → SDKs → + → Add Python SDK → Virtualenv → Existing* → `.venv/bin/python`.
   Ardından *Modules → sandbox-git → + → Python* facet'ini ekleyip bu SDK'yı seç.
3. **Kaynak klasörleri:** `src/` Sources, `tests/` Test Sources; `data/`, `outputs/`, `.venv/`, `archive/` Excluded olmalı
   (*Project Structure → Modules → Sources*).
4. **Run configuration'lar** `.run/` klasöründe hazır ve repoda; sağ üstteki listeden seçilir:
   - `0 · Tests (unittest)` — kural testleri
   - `1 · Build synthetic C1-C2-C3` — `data/synthetic/raw` → `data/canonical/synthetic/`
   - `2 · NB0 Data profile` — çıktılar `outputs/<run_id>/nb00/`
   - `3 · NB1 C1-C2 feasibility`, `4 · NB2 C3 benchmark` (`4b` = washout 90 gün duyarlılığı)
   - `5 · KPI report`, `6 · Evidence package`
   - `7 · Positive control`, `7b · NB2 on positive-control data`
   - `9 · Generate .ipynb from notebooks` — `notebooks/00_data_profile.ipynb` üretir; IntelliJ'de Jupyter olarak açılır
     (kernel: `.venv`). Kaynak her zaman `.py` dosyasıdır; `.ipynb` git'e girmez.

Not: Notebook'lar `ROOT/src`'yi kendisi `sys.path`'e ekler; working directory proje kökü olmalı (run config'lerde ayarlı).

## Kanonik şema (özet)

Uzun format, kohort başına 6 tablo, UTF-8 CSV, ISO-8601 tarih, kodlar text:
`patients`, `conditions`, `medications`, `labs`, `observations` (concept: bmi, height_cm, weight_kg, waist_cm, smoking_status …), `encounters`. Ayrıntı: `src/sandbox/io/schema.py`.

## İlkeler

- **Offline:** yalnızca numpy, pandas, matplotlib. Ağ çağrısı yok.
- **Audit:** her çalıştırma `outputs/audit/audit_log.jsonl`'a ve `outputs/<run_id>/run_manifest.json`'a kod hash'i, girdi hash'leri, parametreler ve tüm çıktıların hash'iyle yazılır.
- **Lab değerleri yalnızca outcome / uygunluk tanımında** kullanılır, asla model girdisi değildir.
- Parametreler tek yerde: `src/sandbox/config.py`.
