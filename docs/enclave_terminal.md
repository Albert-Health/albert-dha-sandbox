# Enclave — terminal komutları (kopyala → yapıştır)

Enclave'deki her iş tek komutla yapılır: repo kökünde (VM'de `~/Desktop/albert-dha/albert-dha-sandbox`)
`bash tools/enclave.sh <komut>`. Kod blokları GitHub'da sağ üstteki kopyala düğmesiyle alınır ve terminale
yapıştırılır; yalnız `SEMA`, `SEMA.TABLO`, `SUTUN` gibi büyük harfli yer tutucular düzeltilir. Faz 1'in sıralı
yapılacaklar listesi: [`faz1_c1_c2.md`](faz1_c1_c2.md).

Her komut sonucunu iki işaret satırı arasında basar. Enclave dışına kopyalanan yalnız bu bloktur:

```text
----8<---- COPY START | enclave req R5 | 2026-11-18 10:00 UTC | commit 1c877f2 | python 3.11.9 | <run_id> ----8<----
...
----8<---- COPY END ----8<----
```

## Nasıl işler

```text
GitHub (bu sayfa) ──kopyala──▶ enclave terminali ──COPY bloğu──▶ ekip
        ▲                                                            │
        └──── git push ◀── adapter / kod düzeltmesi (enclave dışında) ◀┘
enclave'de: git pull --ff-only (salt-okuma token) → komutu tekrar çalıştır
```

- Kod enclave'e yalnız `git pull` ile girer; enclave'de dosya düzenlenmez. Adapter eşlemesi
  (`src/sandbox/io/adapters/nabidh.py`) bloklara bakılarak dışarıda yazılır, push edilir, enclave'de çekilir.
- Bloklar yalnız meta veri ve özet içerir: tablo / sütun adları, tipler, durumlar, sayımlar (< 10 → `<10`),
  değer şekilleri (`2023-01-05` → `9999-99-99`) ve en az 10 farklı hastada geçen kategorik değerler. Kimlik,
  ad, doğum tarihi, iletişim gibi sütunların değeri hiç basılmaz. Yine de kopyalamadan önce bloğa göz at;
  DHA'nın çıktı kuralları geçerli.
- `run` adımlarının tam ekran çıktısı bloğun üstünde kalır ve kopyalanmaz.
- Şifre ve token hiçbir bloğa, dosyaya ya da mesaja yapıştırılmaz.
- Her komut audit'lenir: `outputs/<run_id>/enclave/block.txt`. Blok ekrandan kaydıysa: [`last`](#6-faz-1i-çalıştır).

## 1. Repo ve güncelleme

Repo VM'de klonlu (2026-11-18). Token'ı gün boyu bellekte tutmak için (isteğe bağlı; diske yazılmaz):

```bash
git config --global credential.helper 'cache --timeout=43200'
```

Güncelle (her yeni düzeltmeden sonra, repo kökünde):

```bash
git pull --ff-only && git log -1 --format='%h %s (%cr)'
```

Yeni bir VM'de: `git clone https://github.com/Albert-Health/albert-dha-sandbox.git` (`Password` = salt-okuma
token), sonra `python3 -m pip install --user -r requirements.txt -r requirements-explore.txt` (internet
gerekir).

Komut listesi:

```bash
bash tools/enclave.sh help
```

### `git pull` yoksa: tek dosya (bundle)

VM GitHub'a çıkamıyorsa Faz 1 kodu tek bir dosyayla elle taşınır. Dosya `tools/enclave.py`, adımların
script'lerini (`ingest`, `nb0`, `nb1`, `kpi`) ve bunların import ettiği bütün `src/sandbox` modüllerini değiştirmeden, sıkıştırılmış
olarak taşır (yalnız ASCII; panodan kopyalarken `→`, `≥` bozulmaz). VM'deki eski `src/` ve `tools/`
kullanılmaz; repo yalnız `data/`, `outputs/`, `.env`, `~/.nabidh_iris` ve `src/sandbox/reference/ddc.csv.gz`
için okunur (DDC dosyasının SHA-256'sı kontrol edilir).

1. Dışarıda, commit'ten sonra: `python tools/build_bundle.py` → `dist/sandbox_bundle.py`. Çıktıdaki
   `file check` kodunu not et.
2. Dosyayı bir metin editöründe aç, hepsini seç, kopyala. VM'de repo içine yeni dosya `sandbox_bundle.py`
   olarak yapıştır ve kaydet.
3. VM'de, dosyanın olduğu klasörde kontrol et: `File check: OK (<kod>)` satırındaki kod 1. adımdakiyle aynı olmalı. Dosyanın
   son satırı üstündeki her satırın hash'idir; eksik ya da değişmiş bir kopya çalışmaz, yeniden kopyalanır.

```bash
python3 sandbox_bundle.py bundle-info
```

4. Adımlar: `bash tools/enclave.sh run …` ile aynı komutlar ve aynı COPY blokları. Başlıkta
   `commit <sha> bundle <id>` görünür; audit bundle'daki dosyaların hash'ini ve bundle id'sini yazar.

```bash
python3 sandbox_bundle.py run ingest --cohorts c1 c2
```

```bash
python3 sandbox_bundle.py run nb0
```

```bash
python3 sandbox_bundle.py run nb1
```

```bash
python3 sandbox_bundle.py run kpi
```

Diğer `enclave.sh` komutları da bundle'ın koduyla çalışır (`python3 sandbox_bundle.py mapping c1 c2`, `help`).
Bundle'da olmayan bir adım (`run nb2`) reddedilir; gerekirse dışarıda `--steps ingest nb0 nb1 kpi nb2` ile
yeniden üretilir. Gömülü kodu okumak için: `python3 sandbox_bundle.py bundle-extract /tmp/bundle_src`.

## 2. VM gereksinimleri (R1–R9)

Kaynak: "Data Exploration Environment – VM Requirements". Durumlar: **PASS** tamam · **WARN** eksik ama iş
durmaz · **FAIL** iş durur · INFO / SKIP bilgi. Bloğun son satırı özettir.

| R | Konu | PASS ne demek |
|---|---|---|
| R1 | Masaüstü | Ubuntu 22+, `graphical.target`, masaüstü paketleri kurulu |
| R2 | IntelliJ IDEA Ultimate | kurulu ve Ultimate (Community değil) |
| R3 | Eklentiler | Database Tools, Python, Jupyter klasörleri var |
| R4 | IRIS JDBC sürücüsü | `intersystems-jdbc*.jar` VM'de |
| R5 | Python ve paketler | Python ≥ 3.10, `requirements.txt` paketleri, `pip check`, unit testler |
| R6 | Git + GitHub | git var, `git ls-remote origin` başarılı, `data/` ve `outputs/` yazılabilir |
| R7 | Ağ | IRIS host'u DNS'te (opsiyonel), TCP 51772 açık |
| R8 | Salt-okuma IRIS kullanıcısı | giriş + `SELECT 1`, şemalar görünüyor, test sorgusu satır döndürüyor |
| R9 | Kaynaklar | ≥ 4 vCPU, ≥ 16 GB RAM, ≥ 250 GB boş disk |

Hepsi birden (tek tek: `req R5`, birkaç: `req R7 R8`; R5'te testleri atlamak için sona ` --quick`):

```bash
bash tools/enclave.sh req all
```

## 3. IRIS erişimini oluştur

**3.1 Bağlantı ayarı.** Namespace'i ve salt-okuma kullanıcıyı sorar; `~/.nabidh_iris`'e (repo dışında,
`chmod 600`) yazar. Şifre dosyaya yazılmaz.

```bash
bash tools/enclave.sh iris-setup
```

Sormadan, tek satırda (yer tutucuları düzelt):

```bash
bash tools/enclave.sh iris-setup --namespace NAMESPACE --user KULLANICI
```

Host DNS'te çözülmüyorsa IP ile (R7 DNS satırı WARN):

```bash
bash tools/enclave.sh iris-setup --url jdbc:IRIS://IP_ADRESI:51772/NAMESPACE --user KULLANICI
```

**3.2 Şifre (isteğe bağlı).** Yapılmazsa her komut şifreyi bir kez sorar. Kalıcı yol: repo kökünde git dışı
`.env` (`.gitignore`'da; `import sandbox` okur, `src/sandbox/envfile.py`). Bir kez yazılır, her terminal ve
Jupyter kernel'i kullanır; ortamdaki değer `.env`'i geçer, audit'e yalnız anahtar adları girer:

```bash
read -rs -p "IRIS şifresi: " p && echo && printf 'SANDBOX_SOURCE=nabidh\nNABIDH_IRIS_PASSWORD=%s\n' "$p" > .env && unset p && chmod 600 .env
```

İş bitince `rm .env`. Dosyasız yol: şifreyi yalnız açık terminal oturumunun belleğinde tut:

```bash
read -rs -p "IRIS şifresi: " NABIDH_IRIS_PASSWORD && echo && export NABIDH_IRIS_PASSWORD
```

İş bitince:

```bash
unset NABIDH_IRIS_PASSWORD
```

**3.3 Dene.**

```bash
bash tools/enclave.sh req R7 R8
```

## 4. IRIS'i keşfet (IntelliJ Database aracının yerine)

Amaç, adapter eşlemesi için şunları bulmak: NABIDH kaynaklarının (Patient, tanı, Observation, SocialHistory,
FamilyHistory, Medication, Encounter) hangi şema / tabloda olduğu, sütun adları, tarih biçimi, C1 / C2 / C3'ün
nasıl ayrıldığı ve cinsiyet, uyruk, sigara, aile öyküsü değer listeleri. IRIS'e yalnız `SELECT` gider.

Namespace'teki şemalar (sistem şemaları gizli; hepsi için sona ` --all`):

```bash
bash tools/enclave.sh schemas
```

Adında bir metin geçen tablo ve sütunlar (ör. `patient`, `diagnos`, `observ`, `social`, `family`, `medic`,
`encounter`, `cohort`, `smok`, `nation`):

```bash
bash tools/enclave.sh find patient
```

Bir şemanın tabloları ve satır sayıları (çok tablolu şemada sona ` --no-count` ya da ` --like Patient`):

```bash
bash tools/enclave.sh tables SEMA
```

Bir tablonun sütunları: tip, doluluk, en sık değer şekli, tür tahmini (tarih, kategori, sayı, kimlik?):

```bash
bash tools/enclave.sh columns SEMA.TABLO
```

Bir sütunun değerleri. Kategorik sütunda en az 10 farklı hastada geçen değerler; tarih ve ölçümde yüzdelikler
(tarih ay çözünürlüğünde); kimlik / ad / doğum tarihi sütununda yalnız şekil:

```bash
bash tools/enclave.sh values SEMA.TABLO SUTUN
```

Filtreyle (ör. yalnız BMI gözlemleri) — sona ekle: ` --where "Code = '39156-5'"`. Hasta anahtarı sütunu
otomatik bulunamazsa: ` --patient-col SUTUN`.

Bir sorgunun satır sayısı, satır okumadan (ör. kohort ayrımı, kod varlığı):

```bash
bash tools/enclave.sh count "SELECT DISTINCT PatientID FROM SEMA.TABLO WHERE KOSUL"
```

Şekil okuma: rakam → `9`, harf dizisi → `a`. `9999-99-99` ISO tarih, `99/99/9999` gün-önce tarih (adapter
`DATE_FORMAT`), `99999` ve sütun adı tarih gibiyse IRIS iç tarihi (`horolog`), `a99.9` ICD-10, `9999-9` LOINC.

## 5. Adapter eşlemesi

`SOURCES` (tablo + sütun adları) ve `IRIS_COHORTS` (kohort başına şema) IRIS'te tutuyor mu (satır okunmaz):

```bash
bash tools/enclave.sh mapping c1 c2
```

WARN varsa: bu bloğu ve §4'ün ilgili bloklarını gönder → `nabidh.py` dışarıda güncellenip push edilir →
[§1 güncelle](#1-repo-ve-güncelleme) → `mapping` tekrar. Hepsi PASS olunca §6.

## 6. Faz 1'i çalıştır

Sıra: ingest → NB0 → NB1 → KPI. Her `run`, adımın tam çıktısını ekranda gösterir (kopyalanmaz) ve en sonda
özet bloğu basar.

IRIS → snapshot (`data/nabidh_iris/raw/`) + kanonik veri (`data/canonical/nabidh/`):

```bash
bash tools/enclave.sh run ingest --cohorts c1 c2
```

Blokta "unmapped values" varsa onu gönder; sözlükler güncellenince IRIS'e gitmeden snapshot'tan tekrar:

```bash
bash tools/enclave.sh run ingest --snapshot --cohorts c1 c2
```

Veri profili (şema kontrolü, hacim, Framework Match, eşlenemeyen kodlar):

```bash
bash tools/enclave.sh run nb0
```

C1 / C2 fizibilite: skor hesaplanabilirliği, eksiklik nedenleri, C1 yakalama oranı, skor özetleri:

```bash
bash tools/enclave.sh run nb1
```

KPI tablosu:

```bash
bash tools/enclave.sh run kpi
```

Bir run'ın diğer tabloları (önce listeler; sonra dosya adını ekleyip bas):

```bash
bash tools/enclave.sh show nb1
```

```bash
bash tools/enclave.sh show nb1 nb01/ethnicity_mapping.csv
```

Son bloğu yeniden bas (ekrandan kaydıysa):

```bash
bash tools/enclave.sh last
```

Faz 2 (C3) aynı yoldan: `run ingest --cohorts c3`, sonra `run nb2` (hızlı deneme için sona
` --bootstrap-reps 100`).

## 7. Komut özeti

| Komut | Ne yapar |
|---|---|
| `req R1` … `req R9`, `req all` | VM gereksinimlerini dener |
| `iris-setup` | `~/.nabidh_iris`: bağlantı dizesi + kullanıcı (şifre yazılmaz) |
| `schemas` · `tables SEMA` · `columns SEMA.TABLO` | IRIS kataloğu |
| `values SEMA.TABLO SUTUN` · `find METIN` · `count "SELECT ..."` | değer dağılımı, arama, sayım |
| `mapping c1 c2` | adapter eşlemesi IRIS'te tutuyor mu |
| `run ingest\|nb0\|nb1\|nb2\|kpi` | adımı çalıştırır, özet bloğu basar |
| `show ADIM [DOSYA]` | bir run'ın çıktı tablosunu basar (sayımlar bastırılmış) |
| `last` | son bloğu yeniden basar |

Ortak seçenekler: `--max-rows N` (tablo satırı), `--iris-sqlite DIZIN` (prova, §9).

## 8. Sorun giderme

| Belirti | Ne yap |
|---|---|
| `Python >= 3.10 not found` ya da R5'te paket FAIL | DHA'nın kurduğu Python'u ver: komutun başına `SANDBOX_PYTHON=/tam/yol/python3 ` ekle. Eksik paket → DHA'ya `requirements.txt` ile ilet |
| R6: `could not read Username` | token önbellekte değil: §1'deki `git pull`'u bir kez çalıştırıp token'ı gir, R6'yı tekrarla |
| R7: TCP FAIL | firewall kuralı DHA'da (R7); DNS WARN ise §3.1'deki IP'li `iris-setup` |
| R8: giriş FAIL | kullanıcı / şifre / namespace: `iris-setup`'ı tekrar çalıştır; şifreyi §3.2 ile yeniden gir |
| R8: hiç şema görünmüyor | namespace yanlış ya da SELECT yetkisi yok → DHA (R8). `schemas --all` |
| `no such schema` / `No such table` | blok yakın adları önerir; `schemas`, `find` ile ara |
| `run` çıkış kodu ≠ 0 | blokta "Where" ve "Error" satırları var; hasta değeri içermiyorsa bloğu gönder |
| Blok ekrandan kaydı | `last` |

## 9. Yerelde prova (enclave dışında)

Aynı komutlar IRIS yerine SQLite prova verisiyle (sentetik veri NABIDH biçiminde):

```bash
python tools/build_synthetic_cohorts.py && python tools/make_nabidh_dryrun.py
bash tools/enclave.sh schemas --iris-sqlite data/nabidh_dryrun/iris
bash tools/enclave.sh mapping c1 c2 --iris-sqlite data/nabidh_dryrun/iris
bash tools/enclave.sh run ingest --source nabidh_dryrun_iris --iris-sqlite data/nabidh_dryrun/iris --cohorts c1 c2
bash tools/enclave.sh run nb1 --source nabidh_dryrun_iris
```

Kod: `tools/enclave.sh` (Python'u bulur), `tools/enclave.py` (komutlar), `src/sandbox/io/explore.py`
(IRIS kataloğu ve ifşa kuralları), testler `tests/test_enclave.py`.
