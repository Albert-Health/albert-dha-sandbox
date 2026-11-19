"""Dubai Drug Code (DDC) → ATC: Medication view'ındaki ilaç kodu ya da ilaç adı → çalışma ilaç sınıfları.

NABIDH Medication view'ında ATC yok: C1'de DrugProduct_Code (DDC ürün kodu, ör. "0005-379302-1171"), C2'de
yalnız DrugProduct_Description (ilaç adı). DDC listesinde de ATC yok; ürün başına etken madde adları
("METFORMIN HCL/SITAGLIPTIN"), uygulama yolu ve dozaj formu var. Eşleme:

  ürün → etken maddeler → codelists.INGREDIENT_ATC (kelime sınırıyla arama) → ATC kodları
  kombinasyon ürünü → her etken madde ayrı ATC (bir Medication satırı → birden çok kanonik satır)
  yol sistemik değilse (göz damlası, krem, burun spreyi, inhaler, rektal, eklem içi) → sınıf yok
  (insülin hariç: codelists.INGREDIENT_ANY_ROUTE); satırın kendi yolu (Route_Description) da bakılır

Kod yoksa ad: (1) adın başı DDC ticari adıyla eşleşirse o ürünlerin ATC'leri, (2) adda geçen etken madde
adları. İkisinin birleşimi alınır. Referans: src/sandbox/reference/ddc.csv.gz (tools/build_ddc_reference.py).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ... import codelists

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "reference" / "ddc.csv.gz"

# DDC ROUTE_OF_ADMIN'deki sistemik yollar (virgülle ayrılmış listede biri yeterli: "IM,INTRA-ARTICULAR" → IM)
SYSTEMIC_ROUTES = {
    "ORAL", "IV", "IV INFUSION", "IV BOLUS", "IM", "SC", "SC INFUSION", "SUBLINGUAL", "TRANSDERMAL",
    "PARENTERAL", "ENTERAL", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS",
}   # BUCCAL yok: listede yalnız ağız içi hidrokortizon (yerel)
# DDC listesindeki bilinen hatalar: ürün kodu → neden sınıfsız sayıldığı
REFERENCE_ERRATA = {
    "0235-345201-1021": "MMR aşısı; DDC'de etken maddeler arasında SAXAGLIPTIN yazılı",
}
# Serbest metinde (satırın yolu, ilaç adı) sistemik olmayan kullanımı gösteren kelimeler
_LOCAL_WORDS = (r"TOPICAL|CUTANEOUS|DERMAL|EXTERNAL|CREAM|OINTMENT|GEL|LOTION|SHAMPOO|FOAM|OCULAR|OPHTHALMIC|"
                r"EYE|EAR|OTIC|DROPS|NASAL|INHALATION|INHALER|INHALED|NEBULI[SZ]ER|RECTAL|ENEMA|SUPPOSITOR(Y|IES)|"
                r"VAGINAL|INTRA-?ARTICULAR|INTRAVITREAL|INTRALESIONAL|MOUTHWASH|LOCAL")
LOCAL_TEXT = re.compile(rf"(?<![A-Z])({_LOCAL_WORDS})(?![A-Z])")
SYSTEMIC_TEXT = re.compile(r"(?<![A-Z])(ORAL|IV|IM|SC|INTRAVENOUS|INTRAMUSCULAR|SUBCUTANEOUS|TABLETS?|CAPSULES?|"
                           r"INJECTION|INFUSION|SUBLINGUAL|TRANSDERMAL|PO)(?![A-Z])")
LOCAL_FORM = re.compile(r"(?<![A-Z])(PASTE|MOUTHWASH|GARGLE|LOZENGES?|PELLETS?|OROMUCOSAL)(?![A-Z])")
_NOT_A_DRUG = re.compile(rf"(?<![A-Z])({codelists.INGREDIENT_NOT_A_DRUG})(?![A-Z])")
_INGREDIENT = re.compile(
    r"(?<![A-Z])(" + "|".join(re.escape(k) for k in sorted(codelists.INGREDIENT_ATC, key=len, reverse=True))
    + r")(?![A-Z])")
_ANY_ROUTE_ATC = {codelists.INGREDIENT_ATC[k] for k in codelists.INGREDIENT_ANY_ROUTE}


def norm_code(s: pd.Series) -> pd.Series:
    """Kod karşılaştırması: büyük harf, yalnız harf + rakam ("0005-379302-1171" = "00053793021171")."""
    return s.astype("string").str.upper().str.replace(r"[^0-9A-Z]", "", regex=True).replace("", pd.NA)


def _norm_text(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Z]+", " ", str(s).upper())).strip()


_LEADING_FORM_WORDS = {"TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES", "INJ", "INJECTION",
                       "SYR", "SYRUP", "SUSP", "AMP", "VIAL"}


def _brand_stem(norm: str) -> str:
    """Normalize ad → marka kökü: baştaki form kelimeleri atılır, ilk rakamlı kelimeden sonrası atılır
    ("TAB CRESTOR 10 MG" → "CRESTOR", "CONCOR AM 5MG 5MG" → "CONCOR AM")."""
    words = norm.split()
    while words and words[0] in _LEADING_FORM_WORDS:
        words = words[1:]
    stem = []
    for w in words:
        if any(ch.isdigit() for ch in w):
            break
        stem.append(w)
    return " ".join(stem)


def ingredient_atc(text) -> list[str]:
    """Etken madde metni ("AMLODIPINE (AS BESYLATE)/VALSARTAN") → ATC kodları (sıra korunur, tekrarsız).
    "/" ile ayrılan parçalardan cihaz olanlar (insülin pompası vb.) atlanır."""
    if text is None or pd.isna(text):
        return []
    out: list[str] = []
    for part in str(text).upper().split("/"):
        if _NOT_A_DRUG.search(part):
            continue
        for m in _INGREDIENT.finditer(part):
            atc = codelists.INGREDIENT_ATC[m.group(1)]
            if atc not in out:
                out.append(atc)
    return out


def route_is_systemic(route, dosage_form=None) -> bool:
    """DDC ürün yolu → sistemik mi. Yol yoksa / "N/A" ise dozaj formuna bakılır."""
    r = "" if route is None or pd.isna(route) else str(route).upper()
    tokens = {re.sub(r"\s+", " ", t.replace(".", "")).strip() for t in re.split(r"[,&]| - ", r)}
    form = "" if dosage_form is None or pd.isna(dosage_form) else str(dosage_form).upper()
    if tokens & SYSTEMIC_ROUTES:
        return not LOCAL_FORM.search(form)          # "ORAL" + ağız içi pasta (ADCORTYL IN ORABASE) → yerel
    if tokens - {"", "N/A", "MISCELLANEOUS"}:
        return False
    return bool(SYSTEMIC_TEXT.search(form)) and not LOCAL_TEXT.search(form)


def text_is_local(text) -> bool:
    """Serbest metin (satır yolu ya da ilaç adı) açıkça yerel kullanım mı (sistemik kelime yoksa)."""
    if text is None or pd.isna(text):
        return False
    t = str(text).upper()
    return bool(LOCAL_TEXT.search(t)) and not SYSTEMIC_TEXT.search(t)


def _systemic_filter(atcs: list[str], systemic: bool) -> list[str]:
    return atcs if systemic else [a for a in atcs if a in _ANY_ROUTE_ATC]


@lru_cache(maxsize=4)
def load_reference(path: Path | None = None) -> pd.DataFrame:
    """DDC referansı + ürün başına `atc_codes` (sistemik kurala göre) ve `excluded_route` (etken madde
    çalışma sınıfında ama yol sistemik değil)."""
    ref = pd.read_csv(path or REFERENCE_PATH, dtype="string", keep_default_na=False, na_values=[""])
    raw_atc = [[] if c in REFERENCE_ERRATA else ingredient_atc(i) for c, i in zip(ref["ddc_code"], ref["ingredients"])]
    systemic = [route_is_systemic(r, f) for r, f in zip(ref["route"], ref["dosage_form"])]
    ref["atc_codes"] = [_systemic_filter(a, s) for a, s in zip(raw_atc, systemic)]
    ref["excluded_route"] = [bool(a) and not b for a, b in zip(raw_atc, ref["atc_codes"])]
    ref["key"] = norm_code(ref["ddc_code"])
    ref["sci_key"] = norm_code(ref["scientific_code"])
    ref["trade_key"] = ref["trade_name"].map(_norm_text)
    return ref


@lru_cache(maxsize=4)
def _indexes(path: Path | None = None):
    ref = load_reference(path)
    by_code = dict(zip(ref["key"], zip(ref["atc_codes"], ref["excluded_route"])))
    by_sci = {}
    for k, a, e in zip(ref["sci_key"], ref["atc_codes"], ref["excluded_route"]):
        by_sci.setdefault(k, (a, e))
    # Ticari ad anahtarları: tam ad ("CRESTOR 10MG") + marka kökü ("CRESTOR"). Bir anahtar çalışma dışı bir
    # ürüne de aitse (aynı ad, başka ilaç) belirsizdir → kullanılmaz. Yalnız yolu yerel olan aynı marka
    # (göz damlası vb.) belirsizlik sayılmaz; o ayrımı satırın kendi metni (text_is_local) yapar.
    kinds: dict[str, set[str]] = {}
    atc_by: dict[str, list[str]] = {}
    for full, a, e in zip(ref["trade_key"], ref["atc_codes"], ref["excluded_route"]):
        kind = "study" if a else ("local" if e else "other")
        for k in {full, _brand_stem(full)}:
            if len(k) < 4:
                continue
            kinds.setdefault(k, set()).add(kind)
            cur = atc_by.setdefault(k, [])
            cur.extend(x for x in a if x not in cur)
    by_trade = {k: atc_by[k] for k, kd in kinds.items() if "study" in kd and "other" not in kd}
    return by_code, by_sci, by_trade


def lookup_code(code, row_route=None, path: Path | None = None) -> tuple[str, list[str]]:
    """DDC ürün kodu (ya da DDC bilimsel kodu) → (durum, ATC listesi).
    durum: "DDC code" · "DDC scientific code" · "DDC: not a study drug class" · "DDC: non-systemic route" ·
    "not a DDC code"."""
    by_code, by_sci, _ = _indexes(path)
    key = norm_code(pd.Series([code])).iloc[0]
    if pd.isna(key):
        return "not a DDC code", []
    hit, how = by_code.get(key), "DDC code"
    if hit is None:
        hit, how = by_sci.get(key), "DDC scientific code"
    if hit is None:
        return "not a DDC code", []
    atcs, excluded = hit
    if atcs and text_is_local(row_route):
        atcs, excluded = _systemic_filter(atcs, False), True
    if not atcs:
        return ("DDC: non-systemic route" if excluded else "DDC: not a study drug class"), []
    return how, list(atcs)


def lookup_name(name, row_route=None, path: Path | None = None) -> tuple[str, list[str]]:
    """İlaç adı (serbest metin) → (durum, ATC listesi). Ticari ad (DDC, adın başı) + adda geçen etken maddeler.
    durum: "name: trade name" · "name: ingredient" · "name: trade name + ingredient" · "name: non-systemic" ·
    "name: no study drug class"."""
    if name is None or pd.isna(name) or not str(name).strip():
        return "no name", []
    _, _, by_trade = _indexes(path)
    norm = _norm_text(name)
    trade: list[str] = by_trade.get(norm, [])
    words = _brand_stem(norm).split()
    for k in range(min(len(words), 6), 0, -1):          # en uzun marka kökü önce ("CONCOR PLUS" > "CONCOR")
        if trade:
            break
        trade = by_trade.get(" ".join(words[:k]), [])
    ingr = [] if _NOT_A_DRUG.search(str(name).upper()) else ingredient_atc(str(name).replace("/", " "))
    atcs = trade + [a for a in ingr if a not in trade]
    if not atcs:
        return "name: no study drug class", []
    if text_is_local(name) or text_is_local(row_route):
        atcs = _systemic_filter(atcs, False)
        if not atcs:
            return "name: non-systemic", []
    how = "name: " + " + ".join(w for w, x in (("trade name", trade), ("ingredient", ingr)) if x)
    return how, atcs
