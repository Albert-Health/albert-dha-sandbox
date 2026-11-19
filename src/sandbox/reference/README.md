# Referans tabloları (hasta verisi değil)

| Dosya | Kaynak | İçerik | Üretim |
|---|---|---|---|
| `ddc.csv.gz` | DHA Dubai Drug Code (DDC) listesi, dışa aktarım 2026-11-16 (33.584 ürün; etkin + kaldırılmış) | `ddc_code`, `scientific_code`, `trade_name`, `ingredients` (etken madde adları), `dosage_form`, `route`, `status`; fiyat / üretici / ruhsat sahibi atıldı | `python tools/build_ddc_reference.py <DDC .xlsx>` |

DDC listesinde ATC yok. İlaç sınıfı çalışma anında belirlenir: `codelists.INGREDIENT_ATC` (etken madde → ATC) +
`io/adapters/ddc.py` (yol kuralı, ticari ad araması). Eşleme kuralı değişince bu dosyayı yeniden üretmek gerekmez;
yalnız yeni bir DDC listesi gelince (enclave dışında) yeniden üret ve commit'le. Aynı girdi aynı dosyayı verir.
