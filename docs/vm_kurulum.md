# Enclave VM — kurulum ve ilk çalıştırma

DHA'nın masaüstü VM'inde (IntelliJ, GitHub dışında internet yok) projeyi ayağa kaldırma adımları. VM'i ve
paketleri DHA hazırlar (`docs/gap.md` K4); bu belge **bizim** VM'de yapacaklarımızdır. Analiz akışının
ayrıntısı: `docs/faz1_c1_c2_hazirlik.md` §4.

## 0. DHA'dan beklenen (teslimde kontrol et)

| Ne | Beklenen |
|---|---|
| Python | 3.11; `pip` ile `requirements.txt` + `requirements-explore.txt` kurulu (proje venv kurmaz) |
| IntelliJ IDEA Ultimate | Python, Jupyter, Database Tools eklentileri |
| IRIS JDBC sürücüsü | IntelliJ Database aracı için `intersystems-jdbc-*.jar` (VM'de indirilemez, DHA koymalı) |
| GitHub | HTTPS ile repo erişimi, **salt-okuma** token |
| IRIS | `jdbc:IRIS://dhasbxnbprddb01.dha.ae:51772/<NAMESPACE>`, salt-okuma kullanıcı + şifre |

Eksik paket VM'de sonradan kurulamaz — eksik varsa DHA'ya `requirements*.txt` ile tekrar kurdurulur.

## 1. Repoyu al

```bash
git clone https://github.com/Albert-Health/albert-dha-sandbox.git sandbox-git
```

- Klasör adı `sandbox-git` olmalı: run configuration'lar bu IntelliJ modül adına bakar.
- Token istenince şifre yerine token girilir. Token URL'ye, repoya, run configuration'a yazılmaz.

## 2. Ortam kontrolü (IRIS'siz)

```bash
cd sandbox-git
python tools/check_environment.py --github
```

FAIL yoksa paketler, sürücü, testler ve GitHub erişimi tamamdır. `[python]` satırı hangi Python'un
kullanıldığını gösterir — DHA'nın 3.11'i olmalı. Paket FAIL'i → DHA'ya ilet (çıktıdaki kurulum komutuyla).

## 3. IRIS bağlantı ayarları

Repo dışında, ev dizininde `~/.nabidh_iris` (yalnız sen okuyabilmelisin):

```bash
touch ~/.nabidh_iris && chmod 600 ~/.nabidh_iris
```

İçerik (`KEY=VALUE`):

```
NABIDH_IRIS_URL=jdbc:IRIS://dhasbxnbprddb01.dha.ae:51772/<NAMESPACE>
NABIDH_IRIS_USER=<kullanıcı>
NABIDH_IRIS_PASSWORD=<şifre>
```

Şifre satırı yazılmazsa araçlar terminalde sorar. Audit'e yalnız `host:port/NAMESPACE` ve kullanıcı girer.

```bash
python tools/check_environment.py --iris --github
```

`[iris]` grubu sürücüyü, TCP erişimini ve girişi; `[mapping]` grubu `SOURCES`'taki tablo/sütunların IRIS'te
olup olmadığını denetler. İlk seferde `[mapping]` WARN beklenir (adlar henüz yer tutucu — adım 5).

## 4. IntelliJ

1. *File → Open* → `sandbox-git`.
2. *Project Structure → SDKs → + → Add Python SDK → System Interpreter* → DHA'nın Python 3.11'i.
   *Project → SDK* ve *Modules → sandbox-git → Python* facet'i bu SDK.
3. *Modules → Sources*: `src/` Sources, `tests/` Test Sources; `data/`, `outputs/` Excluded.
4. Run configuration'lar (`.run/`) hazır: önce `0c · Check environment (enclave, IRIS + GitHub)`.
5. *Database → + → Data Source → InterSystems IRIS* (yoksa *Driver*'a DHA'nın jar'ını ekle) → aynı URL ve
   kullanıcı. Şifreyi IntelliJ'in kendi deposunda tut; proje dosyalarına yazılmasın.

## 5. Şemayı eşle (ilk gün)

1. Database aracında namespace'teki şemaları ve tabloları incele: Patient, tanı, Observation, SocialHistory,
   FamilyHistory, Medication, Encounter karşılıkları; C1 / C2 / C3 nasıl ayrılıyor (şema mı, filtre mi).
2. `src/sandbox/io/adapters/nabidh.py`:
   - `IRIS_COHORTS` → kohort başına şema adı
   - `SOURCES` → her kaynağın `table` ve sütun adları; tarih ISO değilse `date_format` (IRIS iç tarihi →
     `"horolog"`); gerekirse `query`
3. `python tools/check_environment.py --iris --cohorts c1 c2` → `[mapping]` PASS olana kadar tekrarla.

Yalnız adapter değişir (CLAUDE.md kural 7); analiz koduna dokunulmaz.

## 6. Çalıştır (Faz 1: C1 / C2)

```bash
python tools/ingest_nabidh.py --input iris --cohorts c1 c2   # → data/nabidh_iris/raw/ snapshot + data/canonical/nabidh/
SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py
SANDBOX_SOURCE=nabidh python notebooks/01_c1_c2_feasibility.py
python tools/kpi_report.py
```

- Ingest'in `*_value_counts.csv` raporunda "unmapped" değer varsa adapter sözlüklerini genişlet; IRIS'e
  tekrar gitmeden snapshot'tan: `python tools/ingest_nabidh.py --raw-root data/nabidh_iris/raw`.
- Her run `outputs/<run_id>/` altına yazar ve audit'lenir; manifest `status: success` olmalı.

## 7. Kurallar (VM'de de geçerli)

- Hasta verisi (`data/`, `outputs/`, snapshot'lar, ekran görüntüsü) git'e girmez — commit öncesi `git status`.
- Enclave'den çıkan tablolarda küçük hücreler bastırılmış olmalı (`sdc`, <10 → "<10"); hasta kimliği içeren
  dosya çıkmaz.
- `outputs/audit/audit_log.jsonl` elle düzenlenmez.
- Token salt-okuma: VM'de yapılan commit'ler (ör. adapter eşlemesi) push edilemez. Geri taşıma yolu DHA ile
  netleşmeli (`docs/faz1_c1_c2_hazirlik.md` §7).

## 8. Güncelleme

```bash
git pull
python tools/check_environment.py --iris --github
```

`requirements*.txt` değiştiyse yeni paketleri VM'de DHA kurar; kontrol script'i eksikleri FAIL/WARN olarak gösterir.
