# VM komutları — Faz 1 (C1 / C2)

Güncelleme: 2026-11-19 · Tam liste ve açıklamalar: [`docs/faz1_c1_c2.md`](docs/faz1_c1_c2.md)

**Kopyala-yapıştır yok.** Bu dosyayı IntelliJ'de aç. Bir `bash` bloğunun solunda ▶ varsa tıklayınca o komut
çalışır; yoksa komutu terminale elle yaz. Komutların hepsi repo kökünden çalışır.

**Sonuçları gönderme:** her komut sonucu `KOPYALA BAŞ` … `KOPYALA SON` arasında basar. O bloğun fotoğrafını
çek. Ekrandan kaydıysa son bloğu yeniden bas:

```bash
bash tools/enclave.sh last
```

Hazır olanlar: `.env` (şifre + `SANDBOX_SOURCE=nabidh`, git dışı), IRIS bağlantısı, c1 / c2 eşlemesi (FAIL 0).

---

## 0 · Kodu güncelle

```bash
git pull --ff-only
```

## 1 · Ingest: IRIS → kanonik veri (~10 dk)

Notebook'lar IRIS'i değil bu adımın yazdığı `data/canonical/nabidh/` klasörünü okur. Önce bu.

```bash
bash tools/enclave.sh run ingest --cohorts c1 c2
```

- Beklenen: `success`, C1 ≈ 2.600 ve C2 ≈ 2.600 hasta. Bloğun fotoğrafını gönder (eşlenemeyen değerler orada).
- "SocialHistory birden çok kalem içeriyor (…)" ile durursa: fotoğrafı gönder. Filtre düzeltilip push edilir;
  sonra adım 0 ve 1 tekrar.

## 2 · Jupyter (inceleme)

Yeni terminal sekmesi aç (Terminal panelinde **+**). Önce notebook dosyalarını üret:

```bash
python3 tools/py2ipynb.py notebooks/00_data_profile.py notebooks/01_c1_c2_feasibility.py
```

Sunucuyu başlat. Token sabit (`sandbox`), bu yüzden IntelliJ'deki adres hiç değişmez:

```bash
python3 -m jupyterlab --no-browser --ip 127.0.0.1 --port 8888 --ServerApp.port_retries=0 --IdentityProvider.token=sandbox
```

IntelliJ'de:

1. `notebooks/00_data_profile.ipynb` dosyasını aç.
2. Üst çubuktaki sunucu menüsü → **External / Configured Server**. Eski token'lı adres varsa sil. Şunu yaz:
   `http://127.0.0.1:8888/?token=sandbox`
3. **Restart Kernel**, sonra **Run All**. Ardından aynısını `01_c1_c2_feasibility.ipynb` için yap.

Notlar:

- "Address already in use" hatası: eski sunucu açık. O sekmede Ctrl+C ile kapat, komutu tekrar çalıştır.
- Sunucunun terminal sekmesi açık kalır. İş bitince Ctrl+C. Pencereyi doğrudan kapatma, yoksa audit'te açık
  run kalır.
- Token yalnız bu VM'de, yalnız `127.0.0.1` üzerinden geçerli.
- Jupyter çalışmazsa tarayıcısız yol:
  `python3 -m IPython -i notebooks/01_c1_c2_feasibility.py`. Notebook çalışır, değişkenler istemde kalır.
  Grafikler `outputs/<run_id>/` altında PNG olarak durur.

## 3 · Resmi run'lar (audit + KOPYALA bloğu)

Jupyter'deki çalıştırma inceleme içindir. Gönderilecek sonuçlar şunlardan gelir; her birinin bloğunu
fotoğrafla:

```bash
bash tools/enclave.sh run nb0
```

```bash
bash tools/enclave.sh run nb1
```

```bash
bash tools/enclave.sh run kpi
```

Ayrıntı tabloları (sayımlar bastırılmış):

```bash
bash tools/enclave.sh show nb0 nb00/core_variable_completeness.csv
```

```bash
bash tools/enclave.sh show nb1 nb01/score_computability.csv
```

```bash
bash tools/enclave.sh show nb1 nb01/score_summary.csv
```

```bash
bash tools/enclave.sh show nb1 nb01/c1_detection_rate.csv
```

## 4 · Tablolar ve değerler (adapter sözlükleri için)

Şemadaki bütün tablolar. Database panelinde "LabResult…" gibi bir tablo görünüyor; birim sütunu var mı,
buradan anlaşılır:

```bash
bash tools/enclave.sh tables c1
```

```bash
bash tools/enclave.sh tables c2
```

Sigara kalemi:

```bash
bash tools/enclave.sh values c1.SocialHistory SocialHabitCategory_Code
```

```bash
bash tools/enclave.sh values c2.SocialHistory SocialHabitCategory_Description
```

Lab ve ölçüm birimleri (12 blok). HbA1c medyanı ~5–8 ise %, ~30–65 ise mmol/mol. Glukoz medyanı ~90–150 ise
mg/dL, ~5–8 ise mmol/L:

```bash
for s in c1 c2; do for k in 4548-4 1558-6 1521-4 39156-5 8302-2 3141-9; do bash tools/enclave.sh values $s.Observation ObservationValue --where "ObservationCode_Code = '$k'"; done; done
```

## 5 · Bitiş

- Jupyter sekmesinde Ctrl+C.
- Enclave'den yalnız KOPYALA blokları ve bastırılmış özet tablolar çıkar. `data/`, `.env`, snapshot'lar ve
  hasta kimliği içeren dosyalar çıkmaz.
