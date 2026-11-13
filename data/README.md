# data/

Bu klasördeki hiçbir veri dosyası git'e girmez.

- `synthetic/raw/` — sentetik test verisi (patients, encounters, conditions, medications, observations, labs). Ekip içinde ayrıca paylaşılır.
- `nabidh/raw/` — enclave'de DHA'nın verdiği dosyalar. Değiştirilmez; yalnızca okunur.
- `canonical/<source>/<c1|c2|c3>/` — adapter çıktısı (kanonik şema). Yeniden üretilebilir.
