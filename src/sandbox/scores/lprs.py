"""Leicester Practice Risk Score (LPRS) — bel çevresi gerektirmeyen Leicester skoru.

Kaynak: Gray LJ, Davies MJ, Hiles S, Taub NA, Webb DR, Srinivasan BT, Khunti K. Detection of impaired
glucose regulation and/or type 2 diabetes mellitus, using primary care electronic data, in a multiethnic
UK community setting. Diabetologia 2012;55(4):959–966. doi:10.1007/s00125-011-2432-x

Rutin birinci basamak EHR verisi için geliştirildi; bel çevresi EHR'de rutin tutulmadığı için modele
alınmadı. Lojistik modelin doğrusal öngörücüsü, sabit terim yok → mutlak risk/olasılık DEĞİL, sıralama
skoru. Katsayılar ilk yazarın (L. J. Gray, Leicester Diabetes Centre) "The Leicester Diabetes Risk Scores"
sunumundaki "Automated score for GP databases" slaytından harfiyen alındı (slayt makaleye atıf veriyor):

    Risk Score = 0.0408359 × yaş + 0.1839942 (erkekse) + 0.7565977 (BME ise) + 0.0820698 × BMI
                 + 0.4770517 (T2DM aile öyküsü varsa) + 0.5498978 (antihipertansif ilaç kullanıyorsa)

[DOĞRULAMA BEKLİYOR] Katsayılar makalenin tam metniyle (paywall) henüz karşılaştırılmadı.

Mutlak bir "yüksek risk" eşiği bulunamadı: yazarlar skoru sıralama için kullandı — pratik başına en
yüksek %10 davet edildi (Let's Prevent Diabetes ve Walking Away from Diabetes; Gray et al. Diabetologia
2012, doi:10.1007/s00125-012-2725-8) ya da hedef duyarlılığa (ör. %80) göre eşik seçildi (aynı sunum). Eşik bu yüzden
`PARAMS["lprs_high_risk_threshold"]`; None → "Pending" [KARAR BEKLİYOR — D23].

Kodlama:
- yaş: yıl, sürekli. Geliştirme popülasyonu 40–75 yaş; aralık dışı hastalarda skor ekstrapolasyondur
  (kısıtlama uygulanmaz, LRA 2010 ile aynı).
- BME (Black and minority ethnic): beyaz dışı = 1. LRA 2010 ile aynı eşleme (`codelists.LRS_WHITE`).
  Etnisite kayıtsız → `lrs_unknown_ethnicity_as_missing` (D12).
- BMI: kg/m², sürekli.
- aile öyküsü: birinci derece akrabada diyabet (`phenotype` → `family_history`).
- antihipertansif: pencere içinde antihipertansif reçete (`phenotype` → `htn_med`); hipertansiyon
  TANISI bu modelde yok (LRA 2010'dan farkı).

Not: LPRS mevcut (tanı konmamış) IGR/T2D tespiti için geliştirilmiş kesitsel bir skordur; C3'teki
incident benchmark dış kullanım (off-label) olarak raporlanır.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import codelists
from ..config import PARAMS

COEF = {
    "age": 0.0408359,            # yıl başına
    "male": 0.1839942,
    "bme": 0.7565977,            # beyaz dışı
    "bmi": 0.0820698,            # kg/m² başına
    "family_history": 0.4770517,
    "antihypertensive": 0.5498978,
}
DEV_AGE_RANGE = (40, 75)         # geliştirme popülasyonu (bilgi amaçlı; kısıt uygulanmaz)


def bme_flag(ethnicity: pd.Series, p: dict = PARAMS) -> pd.Series:
    """Beyaz dışı = 1.0, beyaz = 0.0; kayıtsız → NaN (D12 açıksa)."""
    eth = ethnicity.astype("string").str.strip().str.lower()
    unknown = (eth.isna() | eth.isin(codelists.ETHNICITY_UNKNOWN)).fillna(True).astype(bool)
    white = eth.isin(codelists.LRS_WHITE).fillna(False).astype(bool)
    out = pd.Series(np.where(white, 0.0, 1.0), index=ethnicity.index, dtype=float)
    if p["lrs_unknown_ethnicity_as_missing"]:
        out = out.where(~unknown)
    return out


def score(snap: pd.DataFrame, p: dict = PARAMS) -> pd.DataFrame:
    """phenotype.core_snapshot → LPRS. Eksik girdi → NaN + lrs_missing nedeni.

    Çıktı sütunları LRA 2010 ile aynı adları taşır (`lrs_*`), böylece notebook'lar varyanttan bağımsız.
    Bileşenler (lrs_age, lrs_sex, …) skora katkıdır (katsayı × değer).
    """
    sex_ok = snap["sex"].isin(["Male", "Female"])
    bmi = pd.to_numeric(snap["bmi"], errors="coerce").astype(float)
    parts = {
        "lrs_age": pd.to_numeric(snap["age"], errors="coerce").astype(float) * COEF["age"],
        "lrs_sex": pd.Series(np.where(snap["sex"] == "Male", COEF["male"], 0.0), index=snap.index,
                             dtype=float).where(sex_ok),
        "lrs_ethnicity": bme_flag(snap["ethnicity"], p) * COEF["bme"],
        "lrs_bmi": bmi * COEF["bmi"],
        "lrs_fh": snap["family_history"].astype(bool).astype(float) * COEF["family_history"],
        "lrs_htn": snap["htn_med"].astype(bool).astype(float) * COEF["antihypertensive"],
    }
    x = pd.DataFrame(parts)
    reasons = pd.Series("", index=x.index, dtype=object)
    for col, why in [("lrs_age", "age;"), ("lrs_sex", "sex;"), ("lrs_ethnicity", "ethnicity;"),
                     ("lrs_bmi", "bmi_missing;")]:
        reasons = reasons + np.where(x[col].isna(), why, "")
    x["lrs_missing"] = reasons
    x["lrs_computable"] = reasons == ""
    x["lrs_score"] = x[list(parts)].sum(axis=1, min_count=len(parts)).where(x["lrs_computable"])
    x["lrs_category"] = pd.Series(pd.NA, index=x.index, dtype="string")   # yayımlanmış kategori yok
    thr = p["lprs_high_risk_threshold"]
    if thr is None:
        x["lrs_high_risk"] = pd.Series(pd.NA, index=x.index, dtype="boolean")
    else:
        x["lrs_high_risk"] = (x["lrs_score"] >= thr).astype("boolean").mask(~x["lrs_computable"])
    x["lrs_outside_dev_age"] = ~pd.to_numeric(snap["age"], errors="coerce").between(*DEV_AGE_RANGE)
    return x
