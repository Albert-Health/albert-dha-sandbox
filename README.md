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
  cohorts.py              pozitif havuz (C1/C2), C3 (v2 incident kuralları)
  audit.py                audit trail (run log, kod/veri hash) — KPI: Audit Trail %100
  sdc.py                  küçük hücre bastırma
notebooks/                .py (percent format) — Jupyter/VS Code'da hücre hücre açılır
tools/                    build_synthetic_cohorts.py, py2ipynb.py
tests/                    unittest (pytest gerekmez)
outputs/                  <run_id>/... + audit/audit_log.jsonl (git dışı)
archive/                  önceki prototip notebook ve raporlar
```

## Akış

| Adım | Notebook | Kohort | Çıktı / KPI |
|---|---|---|---|
| 0 | `00_data_profile.py` | C1, C2, C3 | şema doğrulama, tamlık, istenen-vs-gelen kod eşlemesi · *Data Completeness, Framework Match* |
| 1 | `01_c1_c2_feasibility.py` | C1, C2 | birlikte tamlık, C1–C2 seçilim etkisi, skor hesaplanabilirliği (kesitsel) |
| 2 | `02_c3_benchmark.py` | C3 | QDiabetes + LRS: C-index, AUROC, kalibrasyon, eşik metrikleri, recalibration · *klinik/teknik KPI'lar* |
| 3 | `03_uae_model.py` | C3 | koşullu — yalnızca recalibration yetersizse |

## Kurulum ve çalıştırma

```bash
python -m pip install -r requirements.txt        # enclave'de offline wheel ile
python -m unittest discover -s tests -v          # kural testleri

# Sentetik test verisiyle uçtan uca:
python tools/build_synthetic_cohorts.py          # data/synthetic/raw → data/canonical/synthetic/{c1,c2,c3}
python notebooks/00_data_profile.py

# Enclave'de: src/sandbox/io/adapters/nabidh.py içindeki MAPPING'i gerçek dosya/sütun adlarıyla doldur,
# kanonik veriyi data/canonical/nabidh/ altına yaz, notebook'larda SOURCE = "nabidh".
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
