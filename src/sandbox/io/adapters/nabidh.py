"""NABIDH (enclave) ham verisi → kanonik şema.

Teslim yapısı (NABIDH "Data availability", 2026-11-13): kohort başına olay düzeyi kaynaklar —
Patient profile · tanı (ICD-10) · Observation (lab + vital, LOINC) · SocialHistory (sigara) ·
FamilyHistory (diyabet aile öyküsü) · Medication (çalışma ilaçları) · Encounter (yalnız C3).
Ham dosyalar: data/nabidh/raw/<c1|c2|c3>/ (DHA'nın verdiği hâliyle; dokunulmaz).

Enclave'de yapılacak iş (kod değişikliği gerekmemeli):
1. SOURCES'taki dosya ve sütun adlarını gerçek adlarla değiştir. Aşağıdakiler örnek adlardır;
   tools/make_nabidh_dryrun.py prova verisini bu adlarla üretir.
2. Tarih biçimi ISO değilse DATE_FORMAT'ı ayarla (ör. "%d/%m/%Y"); ayraç / kodlama CSV_OPTIONS'ta.
3. tools/ingest_nabidh.py'yi çalıştır. outputs/<run_id>/ingest/<kohort>_value_counts.csv'de
   "unmapped" görünen değerler için SMOKING_VALUES, FH_STATUS_VALUES, FH_RELATION_DEGREE ve
   codelists.NATIONALITY_COUNTRIES'i genişlet; tekrar çalıştır.

Kaynak türleri (kind) → kanonik tablo:
  patients        → patients (cinsiyet SEX_MAP ile Male / Female)
  conditions      → conditions (kod sistemi ICD-10 / SNOMED olarak normalize)
  measurements    → labs + observations (codelists.LOINC_LAB'daki kodlar lab, diğerleri gözlem)
  labs, observations, medications, encounters → doğrudan
  smoking         → observations, concept = smoking_status; değer SMOKING_VALUES ile
                    never / ex / current / light / moderate / heavy / unknown
  family_history  → observations, concept = family_history_dm; değer positive / negative /
                    positive_non_first_degree / unknown (yalnız diyabet kayıtları)
Bir kanonik tabloyu birden çok kaynak besleyebilir (ör. Observation + SocialHistory → observations).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ... import codelists
from ..schema import SCHEMA, TABLES, Dataset, coerce
from .synthetic import read_raw_csv

CSV_OPTIONS = {"sep": ",", "encoding": "utf-8-sig"}
DATE_FORMAT: str | None = None          # None = ISO-8601 / pandas çıkarımı; ör. "%d/%m/%Y"

# Kaynak tanımı:
#   file              kohort klasöründeki dosya adı
#   kind              yukarıdaki kaynak türlerinden biri
#   columns           {kanonik_ad: kaynak_sütun} — zorunlu; yoksa KeyError
#   optional_columns  {kanonik_ad: kaynak_sütun} — varsa alınır
#   constants         {kanonik_ad: değer} — sütun yoksa veya boşsa bu değer
#   filter            {kaynak_sütun: [izinli değerler]} — büyük/küçük harf duyarsız satır seçimi
#   optional          True → dosya yoksa atlanır (ör. encounter yalnız C3'te)
#   date_format       bu kaynak için DATE_FORMAT'ı ezer
SOURCES: dict[str, dict] = {
    "patient_profile": {
        "file": "patients.csv", "kind": "patients",
        "columns": {"patient_id": "patient_id", "sex": "sex", "date_of_birth": "date_of_birth",
                    "nationality": "nationality"},
        "optional_columns": {"ethnicity_raw": "ethnicity", "facility_id": "facility_id"},
    },
    "diagnoses": {
        "file": "diagnoses.csv", "kind": "conditions",
        "columns": {"patient_id": "patient_id", "code": "code", "date": "diagnosis_date"},
        "optional_columns": {"code_system": "code_system", "description": "description"},
        "constants": {"code_system": "ICD-10"},
    },
    "observations": {
        "file": "observations.csv", "kind": "measurements",
        "columns": {"patient_id": "patient_id", "code": "loinc", "value": "value", "date": "date"},
        "optional_columns": {"test_name": "name", "unit": "unit", "code_system": "code_system"},
        "constants": {"code_system": "LOINC"},
    },
    "social_history": {
        "file": "social_history.csv", "kind": "smoking",
        "columns": {"patient_id": "patient_id", "value": "value", "date": "date"},
        "optional_columns": {"code": "code", "item": "item"},
        # SocialHistory sigara dışı kalemler de içeriyorsa: {"item": ["Tobacco smoking status"]}
        "filter": None,
    },
    "family_history": {
        "file": "family_history.csv", "kind": "family_history",
        "columns": {"patient_id": "patient_id", "date": "date"},
        "optional_columns": {"condition": "condition", "status": "status", "relation": "relation"},
    },
    "medications": {
        "file": "medications.csv", "kind": "medications",
        "columns": {"patient_id": "patient_id", "atc_code": "atc_code", "date": "prescription_date"},
        "optional_columns": {"drug_name": "drug_name", "route": "route"},
    },
    "encounters": {
        "file": "encounters.csv", "kind": "encounters", "optional": True,
        "columns": {"patient_id": "patient_id", "date": "encounter_date"},
        "optional_columns": {"encounter_id": "encounter_id", "facility_id": "facility_id",
                             "encounter_type": "encounter_type"},
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


def _select(df: pd.DataFrame, spec: dict, name: str) -> tuple[pd.DataFrame, dict]:
    cols, opt = spec["columns"], spec.get("optional_columns", {})
    missing = [src for src in cols.values() if src not in df.columns]
    if missing:
        raise KeyError(f"{name} ({spec['file']}): kaynakta bulunmayan zorunlu sütunlar: {missing}. "
                       f"Mevcut: {list(df.columns)}")
    info = {"rows_read": int(len(df))}
    for src, allowed in (spec.get("filter") or {}).items():
        if src not in df.columns:
            raise KeyError(f"{name}: filter sütunu yok: {src}")
        keep = _norm_text(df[src]).isin([a.lower() for a in allowed]).fillna(False).astype(bool)
        info[f"filtered_out_by_{src}"] = int((~keep).sum())
        df = df[keep]
    out = pd.DataFrame({canon: df[src] for canon, src in cols.items()})
    info["absent_optional_columns"] = [c for c, src in opt.items() if src not in df.columns]
    for canon, src in opt.items():
        if src in df.columns:
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
        parsed = pd.to_datetime(raw, format=fmt, errors="coerce") if fmt else pd.to_datetime(raw, errors="coerce")
        info[f"unparseable_{col}"] = int((parsed.isna() & raw.notna() & (raw != "")).sum())
        df[col] = parsed
    return df


def _is_diabetes_condition(cond: pd.Series) -> pd.Series:
    text = _norm_text(cond)
    code = cond.astype("string").str.upper().str.replace(r"[.\s]", "", regex=True)
    hit = (code.str.match(r"^(E0[89]|E1[0-4])", na=False) | code.str.startswith("Z833", na=False)
           | cond.astype("string").str.strip().isin(FH_DIABETES_SNOMED) | text.str.contains("diabet", na=False))
    return hit.fillna(False).astype(bool)


# --------------------------------------------------------------------------
# Kaynak türü işleyicileri: (df, name, vc) → {kanonik_tablo: df}
# --------------------------------------------------------------------------
def _h_patients(df, name, vc):
    vc += _value_counts(name, "sex", df["sex"])
    for col in ("nationality", "ethnicity_raw"):
        if col in df:
            vc += _value_counts(name, col, df[col], top=200)
    raw_sex = df["sex"].astype("string").str.strip()
    df["sex"] = raw_sex.str.upper().map(SEX_MAP).fillna(raw_sex)
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


def _h_smoking(df, name, vc):
    if "item" in df and df["item"].nunique(dropna=True) > 1:
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
    vc += _value_counts(name, "value → canonical",
                        key.fillna("<empty>").astype(str) + " → " + value.astype(str))
    out = pd.DataFrame({"patient_id": df["patient_id"], "concept": "smoking_status",
                        "code_system": code.where(code.isna(), "SNOMED"), "code": code,
                        "value": value, "unit": pd.NA, "date": df["date"]})[has_any]
    return {"observations": out}


def _h_family_history(df, name, vc):
    if "condition" in df:
        is_dm = _is_diabetes_condition(df["condition"])
        vc += _value_counts(name, "condition (non-diabetes, dropped)", df.loc[~is_dm, "condition"], top=30)
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


def _h_medications(df, name, vc):
    code = df["atc_code"].astype("string").str.strip().str.upper()
    not_atc = ~code.str.match(r"^[A-Z]\d{2}([A-Z]{1,2}\d{0,2})?$", na=False)
    vc += _value_counts(name, "atc_code not ATC-like", code[not_atc], top=30)
    vc += _value_counts(name, "atc_code prefix", code.str.slice(0, 3))
    df["atc_code"] = code
    return {"medications": df}


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
    """Bir kohort klasörünü okur. Dönüş: (kanonik Dataset, rapor).

    Rapor: {"sources": {ad: {file, rows_read, rows_out, unparseable_*, absent_optional_columns, ...}},
            "value_counts": [{source, field, value, n_rows}, ...]} — eşleme sözlüklerini genişletmek için.
    """
    sources = sources or SOURCES
    raw_dir = Path(raw_dir)
    parts: dict[str, list[pd.DataFrame]] = {t: [] for t in TABLES}
    report: dict = {"cohort": cohort, "sources": {}, "value_counts": []}
    for name, spec in sources.items():
        p = raw_dir / spec["file"]
        if not p.exists():
            if spec.get("optional"):
                report["sources"][name] = {"file": spec["file"], "status": "absent (optional)"}
                continue
            raise FileNotFoundError(f"{name}: {p}")
        df, info = _select(read_raw_csv(p, **CSV_OPTIONS), spec, name)
        df = _parse_dates(df, spec, info)
        produced = HANDLERS[spec["kind"]](df, name, report["value_counts"])
        info.update(file=spec["file"], status="read",
                    rows_out={t: int(len(d)) for t, d in produced.items()})
        report["sources"][name] = info
        for t, d in produced.items():
            parts[t].append(d)

    tables = {}
    for t in TABLES:
        frames = [f for f in parts[t] if len(f)]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(SCHEMA[t]))
        tables[t] = coerce(df, t)
    return Dataset(source="nabidh", cohort=cohort, tables=tables), report
