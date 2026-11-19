"""NABIDH (enclave) ham verisi → kanonik şema.

Teslim yapısı (NABIDH "Data availability", 2026-11-13; enclave'de görülen hâli 2026-11-18): kohort başına
bir IRIS şeması (HSSBX namespace'i, *_HSAA), içinde HSAA view'ları — Patient (ID, Age, Gender_Code,
EthnicGroup_Description; doğum tarihi ve uyruk yok) · Diagnosis · Observation (lab + vital; birim yok) ·
SocialHistory · FamilyHistory · Medication · Encounter. Hasta anahtarı: Patient.ID = diğer view'larda Patient.
Ham dosyalar: data/nabidh/raw/<c1|c2|c3>/ (DHA'nın verdiği hâliyle; dokunulmaz).

İki girdi yolu, aynı eşleme:
- ham dosya  `load(raw_dir, kohort)`            her kaynağın `file`'ı okunur (data/nabidh/raw/<kohort>/)
- IRIS       `load_iris(conn, kohort)`          DHA'daki InterSystems IRIS'ten (io/iris.py) her kaynağın
             `table`'ı (ya da `query`'si) okunur; sonuç ham dosyadaki gibi metne çevrilir ve
             `snapshot_dir` verilirse aynı `file` adlarıyla CSV olarak yazılır → o klasör sonra
             ham dosya yolu ile birebir tekrar okunabilir (tekrarlanabilirlik, audit hash'i).
Sütun eşlemesi, filtre, tarih, değer sözlükleri ve işleyiciler iki yolda ortaktır.

Enclave'de yapılacak iş (kod değişikliği gerekmemeli):
1. SOURCES'taki dosya / tablo ve sütun adlarını gerçek adlarla değiştir. Aşağıdakiler örnek adlardır;
   tools/make_nabidh_dryrun.py prova verisini (CSV + IRIS yerine SQLite) bu adlarla üretir.
   IRIS: IntelliJ Database aracında şemaya bak; `table` = "<ŞEMA>.<Tablo>" ({schema} ve {cohort}
   yer tutucuları IRIS_COHORTS'tan doldurulur). Sütun adları büyük/küçük harf duyarsız eşlenir ve
   yalnızca eşlemede geçen sütunlar çekilir (kimlik bilgisi gibi fazlası gelmez). Birleştirme / filtre
   gerekirse kaynağa tam `query` yaz (yalnız SELECT; sütunları AS ile `columns` adlarına çevir).
2. Tarih biçimi ISO değilse DATE_FORMAT'ı ayarla (ör. "%d/%m/%Y"; IRIS iç tarih sayısı için
   "horolog" = 1840-12-31'den gün, "gün,saniye" de olur); ayraç / kodlama CSV_OPTIONS'ta.
3. tools/ingest_nabidh.py'yi çalıştır (IRIS için --input iris). outputs/<run_id>/ingest/<kohort>_value_counts.csv'de
   "unmapped" görünen değerler için SMOKING_VALUES, FH_STATUS_VALUES, FH_RELATION_DEGREE ve
   codelists.NATIONALITY_COUNTRIES'i genişlet; tekrar çalıştır.

Kaynak türleri (kind) → kanonik tablo:
  patients        → patients (cinsiyet SEX_MAP ile Male / Female)
  conditions      → conditions (kod sistemi ICD-10 / SNOMED olarak normalize)
  measurements    → labs + observations (codelists.LOINC_LAB'daki kodlar lab, diğerleri gözlem)
  medications     → medications; ATC yoksa DDC ürün kodu / ilaç adı → ATC (io/adapters/ddc.py,
                    src/sandbox/reference/ddc.csv.gz); kombinasyon → etken madde başına satır
  labs, observations, encounters → doğrudan
  smoking         → observations, concept = smoking_status; değer SMOKING_VALUES ile
                    never / ex / current / light / moderate / heavy / unknown
  family_history  → observations, concept = family_history_dm; değer positive / negative /
                    positive_non_first_degree / unknown (yalnız diyabet kayıtları)
Bir kanonik tabloyu birden çok kaynak besleyebilir (ör. Observation + SocialHistory → observations).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ... import codelists
from .. import iris
from . import ddc
from ..schema import SCHEMA, TABLES, Dataset, coerce
from .synthetic import read_raw_csv

CSV_OPTIONS = {"sep": ",", "encoding": "utf-8-sig"}
DATE_FORMAT: str | None = None          # None = ISO-8601 / pandas çıkarımı; ör. "%d/%m/%Y"; "horolog" (IRIS)
HOROLOG_EPOCH = pd.Timestamp("1840-12-31")   # IRIS $HOROLOG: gün 0

# Hasta view'ında doğum tarihi yok, yalnız yaş (Age, tam yıl) var. Doğum tarihi yaştan türetilir:
# AGE_REFERENCE_DATE − (Age + 0,5) yıl (yaşın verildiği gün yıl ortası varsayımı; hata ≤ ±6 ay).
# [KARAR BEKLİYOR] D24 — Age hangi tarihe göre (veri çekimi / view'ın oluşturulması / sorgu günü)? DHA'ya
# sorulacak; doğum yılı ya da tarihi verilebiliyorsa BirthDate sütunu tercih edilir (optional_columns).
# Geçici değer: view'ların ilk sorgulandığı gün (2026-11-18).
AGE_REFERENCE_DATE = "2026-11-18"

# IRIS'te kohort başına yer tutucular: `table` / `query` içindeki {schema} vb. buradan, {cohort} kohort adından.
# DHA enclave (namespace HSSBX, 2026-11-18): kohort başına bir HSAA şeması, içinde view'lar.
IRIS_COHORTS: dict[str, dict[str, str]] = {
    "c1": {"schema": "SBXV_ENCL447CCD80_HSAA"},
    "c2": {"schema": "SBXV_ENCL6F10EFBD_HSAA"},
    "c3": {"schema": "SBXV_ENCL94F43B4B_HSAA"},
}

# Kaynak tanımı:
#   file              kohort klasöründeki dosya adı (IRIS'te: snapshot dosyasının adı)
#   table             IRIS tablosu, ör. "{schema}.Patient" (IRIS_COHORTS yer tutucuları)
#   query             (isteğe bağlı) table yerine tam SELECT; sütunları `columns` adlarıyla döndürmeli
#   kind              yukarıdaki kaynak türlerinden biri
#   columns           {kanonik_ad: kaynak_sütun} — zorunlu; yoksa KeyError. Kaynak sütun bir liste de
#                     olabilir: kohortlar arasında ad değişiyorsa mevcut olan ilki alınır
#   optional_columns  {kanonik_ad: kaynak_sütun (ya da liste)} — varsa alınır
#   constants         {kanonik_ad: değer} — sütun yoksa veya boşsa bu değer
#   filter            {kaynak_sütun ya da kanonik_ad: [izinli değerler]} — büyük/küçük harf duyarsız seçim
#   optional          True → dosya / tablo yoksa atlanır (ör. encounter yalnız C3'te)
#   date_format       bu kaynak için DATE_FORMAT'ı ezer
#
# HSAA view'ları (2026-11-18, check_environment [mapping] çıktısı): hasta anahtarı Patient view'ında
# sayısal `ID`, diğer view'larda aynı değeri taşıyan `Patient` sütunu. Kohort farkları: C2'de
# SocialHabitCategory_Code yerine _Description var, Medication'da DrugProduct_Code yok; C1'de Encounter'a
# SELECT yetkisi yok (opsiyonel, atlanır). Kod sistemleri (ICD-10 / LOINC) ve değer sözlükleri henüz
# doğrulanmadı — enclave.sh values / columns ile bakılacak (docs/gap.md K3).
SOURCES: dict[str, dict] = {
    "patient_profile": {
        "file": "patients.csv", "table": "{schema}.Patient", "kind": "patients",
        "columns": {"patient_id": "ID", "sex": "Gender_Code", "age": "Age"},
        "optional_columns": {"ethnicity_raw": "EthnicGroup_Description", "nationality": "Nationality",
                             "date_of_birth": "BirthDate"},
    },
    "diagnoses": {
        "file": "diagnoses.csv", "table": "{schema}.Diagnosis", "kind": "conditions",
        "columns": {"patient_id": "Patient", "code": "Diagnosis_Code", "date": "DiagnosisDate"},
        "optional_columns": {"description": "Diagnosis_Description"},
        "constants": {"code_system": "ICD-10"},
    },
    "observations": {
        "file": "observations.csv", "table": "{schema}.Observation", "kind": "measurements",
        "columns": {"patient_id": "Patient", "code": "ObservationCode_Code", "value": "ObservationValue",
                    "date": "ObservationDate"},
        "optional_columns": {"test_name": "ObservationCode_Description"},     # birim sütunu yok
        "constants": {"code_system": "LOINC"},
    },
    "social_history": {
        "file": "social_history.csv", "table": "{schema}.SocialHistory", "kind": "smoking",
        "columns": {"patient_id": "Patient", "value": "SocialHabitQty_Description", "date": "EnteredOn"},
        "optional_columns": {"item": ["SocialHabitCategory_Code", "SocialHabitCategory_Description"]},
        # Kalemler (C1 ingest, 2026-11-19): ALCOHOL, Beverages, Cigarettes, "Cigarettes,Cigars", Cigars, Other,
        # Smoking, Unknown. Sigara = tütün içimi kalemleri; "Tobacco" prova verisi ve olası C2 adı için.
        # [KARAR BEKLİYOR] D7 — "Other" (shisha / midwakh olabilir) ve "Unknown" dışarıda; medikal ekip.
        # Filtre bir kohortun bütün satırlarını elerse ingest durur ve kaynaktaki kalemleri basar.
        "filter": {"item": ["Smoking", "Cigarettes", "Cigars", "Cigarettes,Cigars", "Tobacco"]},
    },
    "family_history": {
        "file": "family_history.csv", "table": "{schema}.FamilyHistory",
        "kind": "family_history",
        "columns": {"patient_id": "Patient", "date": "EnteredOn"},
        "optional_columns": {"condition": "Diagnosis_Code", "condition_text": "Diagnosis_Description",
                             "relation": "FamilyMember_Description"},
    },
    "medications": {
        "file": "medications.csv", "table": "{schema}.Medication", "kind": "medications",
        "columns": {"patient_id": "Patient", "date": "FromTime"},
        # atc_code ← DrugProduct_Code: ATC ya da DDC ürün kodu (C1); C2'de yok → ad (DrugProduct_Description)
        "optional_columns": {"atc_code": "DrugProduct_Code", "drug_name": "DrugProduct_Description",
                             "route": "Route_Description"},
    },
    "encounters": {
        "file": "encounters.csv", "table": "{schema}.Encounter", "kind": "encounters",
        "optional": True,
        "columns": {"patient_id": "Patient", "date": "EncounterStartDate"},
        "optional_columns": {"encounter_id": "ID", "encounter_type": "EncounterType"},
    },
}

SEX_MAP = {"M": "Male", "MALE": "Male", "1": "Male", "F": "Female", "FEMALE": "Female", "2": "Female"}

# Sigara değeri (küçük harf metin veya SNOMED kodu) → kanonik değer. Önce metin, sonra kod denenir.
# "yes" / "no" yalnızca kaynak (veya filter) sigaraya özgüyse anlamlıdır.
SMOKING_VALUES = {
    **{k: "never" for k in ["never", "never smoker", "never smoked", "never smoked tobacco", "non-smoker",
                            "non smoker", "nonsmoker", "non", "no", "lifetime non-smoker"]},
    **{k: "ex" for k in ["ex", "ex-smoker", "ex smoker", "former", "former smoker", "past smoker", "quit",
                         "quit smoking", "stopped smoking"]},
    **{k: "current" for k in ["current", "smoker", "current smoker", "yes", "current every day smoker",
                              "current some day smoker", "every day smoker", "some day smoker",
                              "occasional smoker", "smoker, current status unknown"]},
    **{k: "light" for k in ["light", "light smoker", "light tobacco smoker"]},
    **{k: "moderate" for k in ["moderate", "moderate smoker"]},
    **{k: "heavy" for k in ["heavy", "heavy smoker", "heavy tobacco smoker"]},
    **{k: "unknown" for k in ["unknown", "unknown if ever smoked", "not asked", "declined", "not known"]},
    # SNOMED (ONC sigara durumu değer seti)
    "266919005": "never",           # Never smoked tobacco
    "8517006": "ex",                # Ex-smoker
    "449868002": "current",         # Smokes tobacco daily
    "428041000124106": "current",   # Occasional tobacco smoker
    "77176002": "current",          # Smoker (current status unknown)
    "428061000124105": "light",     # Light tobacco smoker
    "428071000124103": "heavy",     # Heavy tobacco smoker
    "266927001": "unknown",         # Tobacco smoking consumption unknown
}

# Aile öyküsü durum değeri → positive / negative / unknown
FH_STATUS_VALUES = {
    **{k: "positive" for k in ["yes", "y", "true", "1", "positive", "pos", "present", "confirmed"]},
    **{k: "negative" for k in ["no", "n", "false", "0", "negative", "neg", "absent", "none", "denied",
                               "not present", "no known family history"]},
    **{k: "unknown" for k in ["unknown", "not known", "not asked", "unsure", "declined"]},
}
# Akrabalık → derece. QDiabetes ve LRS birinci derece akrabayı (anne, baba, kardeş, çocuk) sayar.
# İkinci derece → positive_non_first_degree (kayıt var, pozitif sayılmaz). Boş / bilinmeyen akrabalık → pozitif.
FH_RELATION_DEGREE = {
    **{k: "first" for k in ["mother", "father", "parent", "parents", "brother", "sister", "sibling", "siblings",
                            "son", "daughter", "child", "children", "first degree", "first-degree"]},
    **{k: "other" for k in ["grandmother", "grandfather", "grandparent", "aunt", "uncle", "cousin",
                            "niece", "nephew", "grandchild", "second degree", "second-degree"]},
}
FH_DIABETES_SNOMED = {"160303001", "73211009", "44054006", "46635009"}


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------
def _norm_text(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.lower()


def norm_code_system(s: pd.Series) -> pd.Series:
    """HL7 / FHIR / serbest kod sistemi adları → ICD-10 / SNOMED / LOINC / ATC."""
    u = s.astype("string").str.strip().str.upper()
    out = u.copy()
    out[u.str.contains("ICD", na=False) | u.isin(["I10", "I10C", "I10CM"])] = "ICD-10"
    out[u.str.contains("SNOMED", na=False) | u.isin(["SCT", "SNM", "SNOMEDCT"])] = "SNOMED"
    out[u.str.contains("LOINC", na=False) | u.isin(["LN"])] = "LOINC"
    out[u.str.contains("ATC", na=False)] = "ATC"
    return out


def _value_counts(source: str, field: str, s: pd.Series, top: int = 50) -> list[dict]:
    vc = s.astype("string").fillna("<missing>").str.slice(0, 80).value_counts().head(top)
    return [{"source": source, "field": field, "value": str(k), "n_rows": int(v)} for k, v in vc.items()]


def _labels(s: pd.Series, top: int = 15, k: int = 10) -> str:
    """Kategori etiketleri (ör. SocialHistory kalemi) ve satır sayıları; < k satırlık etiket adı basılmaz."""
    vc = s.astype("string").fillna("<boş>").str.slice(0, 40).value_counts()
    big, small = vc[vc >= k], vc[vc < k]
    out = ", ".join(f"{v} ({n})" for v, n in big.head(top).items())
    if len(big) > top:
        out += f", +{len(big) - top} etiket"
    if len(small):
        out += f"{', ' if out else ''}+{len(small)} etiket < {k} satır"
    return out or "yok"


def alternatives(src) -> list[str]:
    """Kaynak sütun tanımı (ad ya da ad listesi) → aday adlar."""
    return [src] if isinstance(src, str) else list(src)


def resolve_column(src, available) -> str | None:
    """Kaynak sütun tanımı → `available` içinde bulunan ilk aday (yoksa None)."""
    have = set(available)
    return next((c for c in alternatives(src) if c in have), None)


def label(src) -> str:
    return " | ".join(alternatives(src))


def filter_columns(spec: dict) -> dict:
    """filter anahtarı → kaynak sütun tanımı. Anahtar kanonik bir adsa (ör. "item") o adın kaynak sütunu."""
    names = {**spec.get("optional_columns", {}), **spec["columns"]}
    return {key: names.get(key, key) for key in (spec.get("filter") or {})}


def _select(df: pd.DataFrame, spec: dict, name: str, where: str | None = None) -> tuple[pd.DataFrame, dict]:
    cols, opt = spec["columns"], spec.get("optional_columns", {})
    got = {canon: resolve_column(src, df.columns) for canon, src in cols.items()}
    missing = [label(cols[c]) for c, src in got.items() if src is None]
    if missing:
        raise KeyError(f"{name} ({where or spec.get('file')}): kaynakta bulunmayan zorunlu sütunlar: {missing}. "
                       f"Mevcut: {list(df.columns)}")
    info = {"rows_read": int(len(df))}
    for key, fsrc in filter_columns(spec).items():
        src = resolve_column(fsrc, df.columns)
        if src is None:
            raise KeyError(f"{name}: filter sütunu yok: {label(fsrc)}")
        allowed = spec["filter"][key]
        keep = _norm_text(df[src]).isin([a.lower() for a in allowed]).fillna(False).astype(bool)
        info[f"filtered_out_by_{key}"] = int((~keep).sum())
        if len(df) and not keep.any():
            raise ValueError(f"{name}: filter {key} = {allowed} bütün satırları eledi. Kaynaktaki değerler: "
                             f"{_labels(df[src])}. SOURCES['{name}']['filter'] güncellenmeli.")
        if (~keep).any():
            info[f"filtered_out_values_{key}"] = _labels(df.loc[~keep, src])
        df = df[keep]
    out = pd.DataFrame({canon: df[src] for canon, src in got.items()})
    opt_got = {canon: resolve_column(src, df.columns) for canon, src in opt.items()}
    info["absent_optional_columns"] = [c for c, src in opt_got.items() if src is None]
    for canon, src in opt_got.items():
        if src is not None:
            out[canon] = df[src]
    for k, v in spec.get("constants", {}).items():
        out[k] = out[k].fillna(v) if k in out else v
    return out, info


def _parse_dates(df: pd.DataFrame, spec: dict, info: dict) -> pd.DataFrame:
    fmt = spec.get("date_format", DATE_FORMAT)
    for col in ("date", "date_of_birth"):
        if col not in df:
            continue
        raw = df[col].astype("string").str.strip()
        if fmt == "horolog":
            parsed = parse_horolog(raw)
        elif fmt:
            parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
        else:
            parsed = pd.to_datetime(raw, errors="coerce")
        info[f"unparseable_{col}"] = int((parsed.isna() & raw.notna() & (raw != "")).sum())
        df[col] = parsed
    return df


def parse_horolog(raw: pd.Series) -> pd.Series:
    """IRIS iç tarihi ($HOROLOG): "gün" ya da "gün,saniye" (gün 0 = 1840-12-31) → datetime."""
    parts = raw.astype("string").str.strip().str.split(",", n=1)
    day = pd.to_numeric(parts.str[0], errors="coerce")
    sec = pd.to_numeric(parts.str[1], errors="coerce").fillna(0)
    day = day.where(day.isna() | (day == day.round()))          # kesirli gün = geçersiz
    out = HOROLOG_EPOCH + pd.to_timedelta(day, unit="D") + pd.to_timedelta(sec, unit="s")
    return pd.Series(out, index=raw.index)


def _is_diabetes_condition(cond: pd.Series) -> pd.Series:
    text = _norm_text(cond)
    code = cond.astype("string").str.upper().str.replace(r"[.\s]", "", regex=True)
    hit = (code.str.match(r"^(E0[89]|E1[0-4])", na=False) | code.str.startswith("Z833", na=False)
           | cond.astype("string").str.strip().isin(FH_DIABETES_SNOMED) | text.str.contains("diabet", na=False))
    return hit.fillna(False).astype(bool)


# --------------------------------------------------------------------------
# Kaynak türü işleyicileri: (df, name, vc) → {kanonik_tablo: df}
# --------------------------------------------------------------------------
def dob_from_age(age: pd.Series, reference=AGE_REFERENCE_DATE) -> pd.Series:
    """Tam yıl yaş → yaklaşık doğum tarihi: reference − (yaş + 0,5) yıl. 0–120 dışı / sayı olmayan → NaT."""
    a = pd.to_numeric(age.astype("string").str.strip(), errors="coerce")
    a = a.where((a >= 0) & (a <= 120))
    out = pd.Timestamp(reference) - pd.to_timedelta((a + 0.5) * 365.25, unit="D")
    return pd.Series(out, index=age.index).dt.normalize()


def _h_patients(df, name, vc):
    vc += _value_counts(name, "sex", df["sex"])
    for col in ("nationality", "ethnicity_raw"):
        if col in df:
            vc += _value_counts(name, col, df[col], top=200)
    raw_sex = df["sex"].astype("string").str.strip()
    df["sex"] = raw_sex.str.upper().map(SEX_MAP).fillna(raw_sex)
    if "age" in df:
        derived = dob_from_age(df["age"], AGE_REFERENCE_DATE)
        given = df["date_of_birth"] if "date_of_birth" in df else pd.Series(pd.NaT, index=df.index)
        use = given.isna() & derived.notna()
        bad_age = df["age"].notna() & derived.isna()
        vc.append({"source": name, "field": "date_of_birth",
                   "value": f"derived from Age at {AGE_REFERENCE_DATE} (mid-year)", "n_rows": int(use.sum())})
        if bad_age.any():
            vc += _value_counts(name, "age not usable (non-numeric or outside 0-120)", df.loc[bad_age, "age"], top=20)
        df["date_of_birth"] = given.where(~use, derived)
    return {"patients": df}


def _h_conditions(df, name, vc):
    vc += _value_counts(name, "code_system", df["code_system"])
    df["code_system"] = norm_code_system(df["code_system"])
    return {"conditions": df}


def split_measurements(m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tek ölçüm tablosunu LOINC'e göre labs ve observations'a ayırır."""
    code = m["code"].astype("string").str.strip()
    system = norm_code_system(m["code_system"]) if "code_system" in m else pd.Series("LOINC", index=m.index)
    is_lab = code.isin(list(codelists.LOINC_LAB)).fillna(False).astype(bool)
    labs = m[is_lab].assign(code=code[is_lab]).rename(columns={"code": "loinc"})
    obs = m[~is_lab].assign(code=code[~is_lab], code_system=system[~is_lab])
    keys = list(zip(obs["code_system"].astype(str), obs["code"].astype(str)))
    obs["concept"] = [codelists.OBS_CODE_TO_CONCEPT.get(k, f"unmapped:{k[1]}") for k in keys]
    return labs, obs


def _h_measurements(df, name, vc):
    unit = df["unit"] if "unit" in df else pd.Series(pd.NA, index=df.index)
    vc += _value_counts(name, "code | unit", df["code"].astype("string") + " | " + unit.astype("string").fillna(""),
                        top=100)
    labs, obs = split_measurements(df)
    vc += _value_counts(name, "lab value non-numeric (raw)",
                        labs.loc[pd.to_numeric(labs["value"], errors="coerce").isna() & labs["value"].notna(), "value"],
                        top=20)
    return {"labs": labs, "observations": obs}


def _h_smoking(df, name, vc, item_filtered: bool = False):
    """item_filtered: SOURCES'ta kalem filtresi var → seçilen kalemlerin hepsi sigara sayılır. Yoksa birden çok
    kalem (ör. sigara + alkol) görülürse durur: hangi kalemin sigara olduğu bilinmez."""
    if "item" in df and not item_filtered and df["item"].nunique(dropna=True) > 1:
        raise ValueError(f"{name}: SocialHistory birden çok kalem içeriyor "
                         f"({sorted(df['item'].dropna().unique())[:10]}). "
                         f"SOURCES['{name}']['filter'] ile sigara kalemini seç.")
    if "item" in df:
        vc += _value_counts(name, "item", df["item"])
    key = _norm_text(df["value"])
    mapped = key.map(SMOKING_VALUES)
    code = df["code"].astype("string").str.strip() if "code" in df else pd.Series(pd.NA, index=df.index, dtype="string")
    mapped = mapped.fillna(code.map(SMOKING_VALUES))
    has_any = key.notna() | code.notna()
    value = mapped.astype(object).where(mapped.notna(), "unmapped:" + key.fillna(code).astype(object).astype(str))
    shown = key.fillna("<empty>").astype(str) + " → " + value.astype(str)
    if "item" in df:                                # birden çok kalemde değerin hangi kalemden geldiği
        shown = df["item"].astype("string").fillna("<boş>").astype(str) + " | " + shown
    vc += _value_counts(name, "value → canonical", shown)
    out = pd.DataFrame({"patient_id": df["patient_id"], "concept": "smoking_status",
                        "code_system": code.where(code.isna(), "SNOMED"), "code": code,
                        "value": value, "unit": pd.NA, "date": df["date"]})[has_any]
    return {"observations": out}


def _h_family_history(df, name, vc):
    cond_cols = [c for c in ("condition", "condition_text") if c in df]
    if cond_cols:                                   # kod ya da açıklama diyabet diyorsa diyabet kaydı
        is_dm = pd.Series(False, index=df.index)
        for c in cond_cols:
            is_dm |= _is_diabetes_condition(df[c])
        shown = df[cond_cols].astype("string").fillna("").agg(" | ".join, axis=1)
        vc += _value_counts(name, f"{' | '.join(cond_cols)} (non-diabetes, dropped)", shown[~is_dm], top=30)
        df = df[is_dm]
    if "status" in df:
        raw = _norm_text(df["status"])
        st = raw.map(FH_STATUS_VALUES)
        value = st.astype(object).where(st.notna(), "unmapped:" + raw.astype(object).astype(str))
        value = value.where(raw.notna(), "unknown")
        vc += _value_counts(name, "status → canonical", raw.fillna("<empty>").astype(str) + " → " + value.astype(str))
    else:
        value = pd.Series("positive", index=df.index, dtype=object)
    if "relation" in df:
        rel = _norm_text(df["relation"])
        deg = rel.map(FH_RELATION_DEGREE)
        label = deg.astype(object).where(deg.notna(), "unmapped (treated as first)")
        label = label.where(rel.notna(), "not recorded (treated as first)")
        vc += _value_counts(name, "relation → degree", rel.fillna("<empty>").astype(str) + " → " + label.astype(str))
        value = value.where(~((value == "positive") & deg.eq("other").fillna(False).astype(bool)),
                            "positive_non_first_degree")
    out = pd.DataFrame({"patient_id": df["patient_id"], "concept": "family_history_dm", "code_system": pd.NA,
                        "code": pd.NA, "value": value, "unit": pd.NA, "date": df["date"]})
    return {"observations": out}


ATC_LIKE = re.compile(r"^[A-Z]\d{2}([A-Z]{1,2}\d{0,2})?$")


def _resolve_drug(code, drug, route) -> tuple[str, list[str]]:
    """Tek ilaç kaydı → (yöntem, ATC listesi). Kod ATC biçimindeyse olduğu gibi; DDC ürün / bilimsel koduysa
    DDC referansından (kod tanınırsa son söz koddadır); kod yoksa ya da tanınmazsa ilaç adından."""
    if code is not None:
        if ATC_LIKE.match(code):
            return "ATC code", [code]
        how, atcs = ddc.lookup_code(code, route)
        if how != "not a DDC code":
            return how, atcs
        if drug is None:
            return "code not ATC/DDC, no name", []
        how, atcs = ddc.lookup_name(drug, route)
        return "code not ATC/DDC → " + how, atcs
    if drug is None:
        return "no code, no name", []
    return ddc.lookup_name(drug, route)


def _h_medications(df, name, vc):
    """İlaç → ATC (io/adapters/ddc.py). C1: DrugProduct_Code = DDC ürün kodu; C2: kod yok, DrugProduct_Description
    (ad) → DDC ticari adı + etken madde. Kombinasyon ürünü → etken madde başına bir satır. Çalışma ilaç sınıfına
    düşmeyen kayıt kanonik tabloya girmez (atc_code zorunlu); kaçının neden düştüğü value_counts'ta."""
    empty = pd.Series(pd.NA, index=df.index, dtype="string")
    code = (df["atc_code"] if "atc_code" in df else empty).astype("string").str.strip().str.upper().replace("", pd.NA)
    drug = (df["drug_name"] if "drug_name" in df else empty).astype("string").str.strip().replace("", pd.NA)
    route = (df["route"] if "route" in df else empty).astype("string").str.strip().replace("", pd.NA)
    keys = list(zip(*([None if pd.isna(x) else str(x) for x in s] for s in (code, drug, route))))
    cache = {k: _resolve_drug(*k) for k in set(keys)}
    how = pd.Series([cache[k][0] for k in keys], index=df.index, dtype="string")
    atcs = pd.Series([cache[k][1] for k in keys], index=df.index, dtype=object)
    n_atc = atcs.map(len)

    vc += _value_counts(name, "drug → ATC method", how)
    unknown = how.str.startswith("code not ATC/DDC").fillna(False).astype(bool)
    vc += _value_counts(name, "drug code not ATC/DDC", code[unknown], top=30)
    by_name = how.str.contains("name: ", regex=False).fillna(False).astype(bool)
    hit = by_name & (n_atc > 0)
    vc += _value_counts(name, "ATC ← drug_name (name match)", atcs[hit].str.join("+") + " ← " + drug[hit], top=50)
    vc += _value_counts(name, "drug_name without study drug class", drug[by_name & (n_atc == 0)], top=50)
    if (n_atc > 1).any():
        vc.append({"source": name, "field": "combination products (rows → several ATC rows)", "value": "<n rows>",
                   "n_rows": int((n_atc > 1).sum())})
    if (n_atc == 0).any():                          # atc_code zorunlu → sınıfsız kayıt kanonik tabloya girmez
        vc.append({"source": name, "field": "rows dropped: no study drug class", "value": "<no ATC>",
                   "n_rows": int((n_atc == 0).sum())})
    out = df.assign(atc_code=atcs).explode("atc_code")
    out = out[out["atc_code"].notna()].reset_index(drop=True)
    vc += _value_counts(name, "ATC (3 chars) after mapping", out["atc_code"].astype("string").str.slice(0, 3))
    return {"medications": out}


def _passthrough(table):
    return lambda df, name, vc: {table: df}


HANDLERS = {
    "patients": _h_patients, "conditions": _h_conditions, "measurements": _h_measurements,
    "smoking": _h_smoking, "family_history": _h_family_history, "medications": _h_medications,
    "labs": _passthrough("labs"), "observations": _passthrough("observations"),
    "encounters": _passthrough("encounters"),
}


# --------------------------------------------------------------------------
# Yükleme
# --------------------------------------------------------------------------
def load(raw_dir: Path, cohort: str, sources: dict | None = None) -> tuple[Dataset, dict]:
    """Ham dosya yolu: bir kohort klasörünü okur. Dönüş: (kanonik Dataset, rapor).

    Rapor: {"input": "files", "sources": {ad: {file, rows_read, rows_out, unparseable_*,
            absent_optional_columns, ...}}, "value_counts": [{source, field, value, n_rows}, ...]}
            — eşleme sözlüklerini genişletmek için.
    """
    raw_dir = Path(raw_dir)

    def read(name: str, spec: dict):
        p = raw_dir / spec["file"]
        if not p.exists():
            if spec.get("optional"):
                return None, {"file": spec["file"], "status": "absent (optional)"}
            raise FileNotFoundError(f"{name}: {p}")
        return read_raw_csv(p, **CSV_OPTIONS), {"file": spec["file"]}

    return _load(cohort, sources or SOURCES, read, "files")


def iris_query(conn, spec: dict, name: str, params: dict) -> str:
    """Kaynağın IRIS sorgusu: tam `query`, ya da `table`'dan yalnızca eşlemede geçen sütunları
    (büyük/küçük harf duyarsız) `columns` adlarıyla çeken SELECT."""
    try:
        if spec.get("query"):
            return spec["query"].format(**params)
        table = spec["table"].format(**params)
    except KeyError as e:
        raise KeyError(f"{name}: yer tutucu {e} IRIS_COHORTS'ta yok (mevcut: {sorted(params)})") from None
    have = iris.column_names(conn, table)
    by_lower = {c.lower(): c for c in have}
    missing = [label(src) for src in spec["columns"].values()
               if not any(c.lower() in by_lower for c in alternatives(src))]
    if missing:
        raise KeyError(f"{name} ({table}): tabloda bulunmayan zorunlu sütunlar: {missing}. Mevcut: {have}")
    wanted = [c for src in [*spec["columns"].values(), *spec.get("optional_columns", {}).values(),
                            *filter_columns(spec).values()] for c in alternatives(src)]
    select = [f"{iris.quote_ident(by_lower[c.lower()])} AS {iris.quote_ident(c)}"
              for c in dict.fromkeys(wanted) if c.lower() in by_lower]
    return f"SELECT {', '.join(select)} FROM {table}"


def load_iris(conn, cohort: str, sources: dict | None = None, cohort_params: dict | None = None,
              snapshot_dir: Path | None = None) -> tuple[Dataset, dict]:
    """IRIS yolu: DB-API bağlantısından (io/iris.connect) bir kohortu okur. Dönüş `load` ile aynı;
    rapordaki her kaynakta ayrıca çalıştırılan `query` ve sonucun `sha256`'sı (audit girdisi) bulunur.

    snapshot_dir: her kaynağın sonucu `file` adıyla CSV olarak yazılır — `load(snapshot_dir, kohort)`
    aynı Dataset'i verir. Eşleme sözlükleri değişince IRIS'e yeniden gitmeden tekrar ingest edilebilir.
    """
    params = {"cohort": cohort, **(IRIS_COHORTS.get(cohort, {}) if cohort_params is None else cohort_params)}
    snap = Path(snapshot_dir) if snapshot_dir else None
    if snap:
        snap.mkdir(parents=True, exist_ok=True)

    def read(name: str, spec: dict):
        try:
            sql = iris_query(conn, spec, name, params)
            df, text = iris.fetch(conn, sql)
        except (KeyError, ValueError):
            raise                                   # eşleme / sorgu hatası: opsiyonel kaynakta da sessiz geçme
        except Exception as e:                      # sürücü hatası (ör. tablo yok)
            if not spec.get("optional"):
                raise
            if snap and (snap / spec["file"]).exists():
                (snap / spec["file"]).unlink()      # önceki snapshot'tan kalan dosya karışmasın
            return None, {"status": "absent (optional)", "error": f"{type(e).__name__}: {str(e)[:300]}"}
        info = {"query": sql, "sha256": iris.sha256_text(text)}
        if snap:
            p = snap / spec["file"]
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            info["snapshot"] = str(p)
        return df, info

    return _load(cohort, sources or SOURCES, read, "iris")


def _load(cohort: str, sources: dict, read, input_kind: str) -> tuple[Dataset, dict]:
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    report: dict = {"cohort": cohort, "input": input_kind, "sources": {}, "value_counts": []}
    for name, spec in sources.items():
        raw, got = read(name, spec)
        if raw is None:
            report["sources"][name] = got
            continue
        df, info = _select(raw, spec, name, got.get("file") or "IRIS query")
        df = _parse_dates(df, spec, info)
        extra = {"item_filtered": bool(spec.get("filter"))} if spec["kind"] == "smoking" else {}
        produced = HANDLERS[spec["kind"]](df, name, report["value_counts"], **extra)
        info.update(got)
        info.update(status="read", rows_out={t: int(len(d)) for t, d in produced.items()})
        report["sources"][name] = info
        for t, d in produced.items():
            parts[t].append(d)

    tables = {}
    for t in TABLES:
        frames = [f for f in parts[t] if len(f)]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(SCHEMA[t]))
        tables[t] = coerce(df, t)
    return Dataset(source="nabidh", cohort=cohort, tables=tables), report
