# data/

Bu klasördeki hiçbir veri dosyası git'e girmez.

- `nabidh_iris/raw/<c1|c2|c3>/` — enclave'de IRIS'ten okunan verinin snapshot'ı (`ingest_nabidh --input iris`).
  Sözlük düzeltmesinden sonra IRIS'e gitmeden yeniden ingest bunu okur (`--raw-root data/nabidh_iris/raw`).
- `nabidh/raw/<c1|c2|c3>/` — DHA dosya teslim ederse ham dosyalar. Değiştirilmez; yalnızca okunur.
- `canonical/<source>/<c1|c2|c3>/` — adapter çıktısı (kanonik şema). Yeniden üretilebilir.
- Yerel prova: `synthetic/raw/` (sentetik test verisi, ekip içinde ayrıca paylaşılır) ve `nabidh_dryrun/`
  (`tools/make_nabidh_dryrun.py`: sentetik veri HSAA view biçiminde, dosya + SQLite).
