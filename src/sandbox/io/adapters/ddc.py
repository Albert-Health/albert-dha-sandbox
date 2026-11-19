"""Dubai Drug Code (DDC) → ATC: drug code or drug name in the Medication view → study drug classes.

The NABIDH Medication view has no ATC: C1 has DrugProduct_Code (DDC product code, e.g. "0005-379302-1171"), C2
only DrugProduct_Description (drug name). The DDC list has no ATC either; per product it has active ingredient
names ("METFORMIN HCL/SITAGLIPTIN"), route of administration and dosage form. Mapping:

  product → active ingredients → codelists.INGREDIENT_ATC (whole-word search) → ATC codes
  combination product → one ATC per active ingredient (one Medication row → several canonical rows)
  non-systemic route (eye drops, cream, nasal spray, inhaler, rectal, intra-articular) → no class
  (except insulin: codelists.INGREDIENT_ANY_ROUTE); the row's own route (Route_Description) is checked too

Without a code, the name: (1) if the start of the name matches a DDC trade name, those products' ATCs; failing
that, the brand's first word ("XIGDUO 5/1000" → DDC "XIGDUO XR 5MG/1000MG"), (2) the active ingredient names found
in the name. The union of both is taken. Reference: src/sandbox/reference/ddc.csv.gz
(tools/build_ddc_reference.py).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ... import codelists

REFERENCE_PATH = Path(__file__).resolve().parents[2] / "reference" / "ddc.csv.gz"

# Systemic routes in DDC ROUTE_OF_ADMIN (one is enough in a comma-separated list: "IM,INTRA-ARTICULAR" → IM)
SYSTEMIC_ROUTES = {
    "ORAL", "IV", "IV INFUSION", "IV BOLUS", "IM", "SC", "SC INFUSION", "SUBLINGUAL", "TRANSDERMAL",
    "PARENTERAL", "ENTERAL", "INTRAVENOUS", "INTRAMUSCULAR", "SUBCUTANEOUS",
}   # no BUCCAL: the list only has oromucosal hydrocortisone (local)
# Known errors in the DDC list: product code → why it is treated as having no class
REFERENCE_ERRATA = {
    "0235-345201-1021": "MMR vaccine; DDC lists SAXAGLIPTIN among its active ingredients",
}
# Words in free text (the row's route, drug name) that indicate non-systemic use
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
    """Code comparison: upper case, letters + digits only ("0005-379302-1171" = "00053793021171")."""
    return s.astype("string").str.upper().str.replace(r"[^0-9A-Z]", "", regex=True).replace("", pd.NA)


def _norm_text(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Z]+", " ", str(s).upper())).strip()


_LEADING_FORM_WORDS = {"TAB", "TABS", "TABLET", "TABLETS", "CAP", "CAPS", "CAPSULE", "CAPSULES", "INJ", "INJECTION",
                       "SYR", "SYRUP", "SUSP", "AMP", "VIAL"}


def _brand_stem(norm: str) -> str:
    """Normalised name → brand stem: leading form words are dropped, everything from the first word with a digit on
    is dropped ("TAB CRESTOR 10 MG" → "CRESTOR", "CONCOR AM 5MG 5MG" → "CONCOR AM")."""
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
    """Active ingredient text ("AMLODIPINE (AS BESYLATE)/VALSARTAN") → ATC codes (order kept, no duplicates).
    "/"-separated parts that are devices (insulin pump etc.) are skipped."""
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
    """DDC product route → is it systemic. Without a route / with "N/A" the dosage form decides."""
    r = "" if route is None or pd.isna(route) else str(route).upper()
    tokens = {re.sub(r"\s+", " ", t.replace(".", "")).strip() for t in re.split(r"[,&]| - ", r)}
    form = "" if dosage_form is None or pd.isna(dosage_form) else str(dosage_form).upper()
    if tokens & SYSTEMIC_ROUTES:
        return not LOCAL_FORM.search(form)          # "ORAL" + oromucosal paste (ADCORTYL IN ORABASE) → local
    if tokens - {"", "N/A", "MISCELLANEOUS"}:
        return False
    return bool(SYSTEMIC_TEXT.search(form)) and not LOCAL_TEXT.search(form)


def text_is_local(text) -> bool:
    """Does free text (row route or drug name) clearly say local use (with no systemic word)."""
    if text is None or pd.isna(text):
        return False
    t = str(text).upper()
    return bool(LOCAL_TEXT.search(t)) and not SYSTEMIC_TEXT.search(t)


def _systemic_filter(atcs: list[str], systemic: bool) -> list[str]:
    return atcs if systemic else [a for a in atcs if a in _ANY_ROUTE_ATC]


@lru_cache(maxsize=4)
def load_reference(path: Path | None = None) -> pd.DataFrame:
    """DDC reference + per product `atc_codes` (by the systemic rule) and `excluded_route` (active ingredient
    in a study class but the route is not systemic)."""
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
    # Trade name keys: full name ("CRESTOR 10MG") + brand stem ("CRESTOR"). A key that also belongs to a non-study
    # product (same name, another drug) is ambiguous → not used. The same brand with only a local route (eye
    # drops etc.) is not ambiguity; the row's own text (text_is_local) makes that distinction.
    kinds: dict[str, set[str]] = {}
    atc_by: dict[str, list[str]] = {}
    # Brand first word: rows often drop the suffix of the DDC name ("XIGDUO" for "XIGDUO XR 5MG/1000MG", "TOUJEO"
    # for "TOUJEO SOLOSTAR"). Same ambiguity rule over every product whose brand stem starts with that word; ATC =
    # the codes common to all its study products (not the union: "CONCOR" must not take CONCOR PLUS's thiazide).
    head_kinds: dict[str, set[str]] = {}
    head_atc: dict[str, list[str]] = {}
    for full, a, e in zip(ref["trade_key"], ref["atc_codes"], ref["excluded_route"]):
        kind = "study" if a else ("local" if e else "other")
        stem = _brand_stem(full)
        for k in {full, stem}:
            if len(k) < 4:
                continue
            kinds.setdefault(k, set()).add(kind)
            cur = atc_by.setdefault(k, [])
            cur.extend(x for x in a if x not in cur)
        head = stem.split()[0] if stem else ""
        if len(head) < 4:
            continue
        head_kinds.setdefault(head, set()).add(kind)
        if a:
            head_atc[head] = list(a) if head not in head_atc else [x for x in head_atc[head] if x in a]
    by_trade = {k: atc_by[k] for k, kd in kinds.items() if "study" in kd and "other" not in kd}
    by_head = {h: head_atc[h] for h, kd in head_kinds.items()
               if "study" in kd and "other" not in kd and head_atc.get(h)}
    return by_code, by_sci, by_trade, by_head


def lookup_code(code, row_route=None, path: Path | None = None) -> tuple[str, list[str]]:
    """DDC product code (or DDC scientific code) → (status, ATC list).
    status: "DDC code" · "DDC scientific code" · "DDC: not a study drug class" · "DDC: non-systemic route" ·
    "not a DDC code"."""
    by_code, by_sci, _, _ = _indexes(path)
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
    """Drug name (free text) → (status, ATC list). Trade name (DDC, start of the name) + active ingredients named.
    status: "name: trade name" · "name: brand first word" · "name: ingredient" · "name: trade name + ingredient" ·
    "name: brand first word + ingredient" · "name: non-systemic" · "name: no study drug class"."""
    if name is None or pd.isna(name) or not str(name).strip():
        return "no name", []
    _, _, by_trade, by_head = _indexes(path)
    norm = _norm_text(name)
    device = bool(_NOT_A_DRUG.search(str(name).upper()))
    trade: list[str] = by_trade.get(norm, [])
    trade_how = "trade name"
    words = _brand_stem(norm).split()
    for k in range(min(len(words), 6), 0, -1):          # longest brand stem first ("CONCOR PLUS" > "CONCOR")
        if trade:
            break
        trade = by_trade.get(" ".join(words[:k]), [])
    if not trade and words and not device:              # looser key: never for a device ("INSULIN PEN NEEDLES")
        trade, trade_how = list(by_head.get(words[0], [])), "brand first word"
    ingr = [] if device else ingredient_atc(str(name).replace("/", " "))
    atcs = trade + [a for a in ingr if a not in trade]
    if not atcs:
        return "name: no study drug class", []
    if text_is_local(name) or text_is_local(row_route):
        atcs = _systemic_filter(atcs, False)
        if not atcs:
            return "name: non-systemic", []
    how = "name: " + " + ".join(w for w, x in ((trade_how, trade), ("ingredient", ingr)) if x)
    return how, atcs
