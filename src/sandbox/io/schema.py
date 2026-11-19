"""Kanonik veri şeması, okuma/yazma ve doğrulama.

Kaynak formatı ne olursa olsun (NABIDH ham CSV, hasta-başı düz dosya, sentetik),
adapter'lar veriyi buradaki 6 uzun-format tabloya çevirir. Analiz kodu YALNIZCA
bu şemayı okur.

Dosya kuralları: UTF-8 CSV, ISO-8601 tarih (YYYY-MM-DD), kodlar text.
Konum: data/canonical/<source>/<cohort>/<table>.csv
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# tip: "str" | "date" | "float"
SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    # sütun: (tip, zorunlu)
    "patients": {
        "patient_id": ("str", True),
        "sex": ("str", True),                # Male / Female
        "date_of_birth": ("date", True),
        "ethnicity_raw": ("str", False),     # kaynaktaki en granüler kategori
        "nationality": ("str", False),
        "facility_id": ("str", False),
    },
    "conditions": {
        "patient_id": ("str", True),
        "code_system": ("str", True),        # ICD-10 / SNOMED
        "code": ("str", True),
        "description": ("str", False),
        "date": ("date", True),
    },
    "medications": {
        "patient_id": ("str", True),
        "atc_code": ("str", True),
        "drug_name": ("str", False),
        "date": ("date", True),
        "route": ("str", False),
    },
    "labs": {
        "patient_id": ("str", True),
        "loinc": ("str", True),
        "test_name": ("str", False),
        "value": ("float", True),
        "unit": ("str", False),
        "date": ("date", True),
    },
    "observations": {
        "patient_id": ("str", True),
        "concept": ("str", True),            # bmi, height_cm, weight_kg, waist_cm, smoking_status ...
        "code_system": ("str", False),
        "code": ("str", False),
        "value": ("str", True),              # sayısal veya kategorik (smoking) → str saklanır
        "unit": ("str", False),
        "date": ("date", True),
    },
    "encounters": {
        "patient_id": ("str", True),
        "encounter_id": ("str", False),
        "date": ("date", True),
        "facility_id": ("str", False),
        "encounter_type": ("str", False),
    },
}
TABLES = tuple(SCHEMA)
OPTIONAL_TABLES = ("encounters",)


@dataclass
class Dataset:
    """Bir kohortun kanonik tabloları."""
    source: str
    cohort: str
    tables: dict[str, pd.DataFrame]

    def __getitem__(self, name: str) -> pd.DataFrame:
        return self.tables[name]

    @property
    def n_patients(self) -> int:
        return self.tables["patients"]["patient_id"].nunique()


def cohort_dir(base: Path, source: str, cohort: str) -> Path:
    return Path(base) / source / cohort


def coerce(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Sütunları şema tiplerine çevirir; eksik opsiyonel sütunları boş ekler, fazlaları atar."""
    out = pd.DataFrame(index=df.index)
    for col, (typ, _req) in SCHEMA[table].items():
        s = df[col] if col in df.columns else pd.Series(pd.NA, index=df.index)
        if typ == "date":
            out[col] = pd.to_datetime(s, errors="coerce")
        elif typ == "float":
            out[col] = pd.to_numeric(s, errors="coerce")
        else:
            out[col] = s.astype("string").str.strip()
    return out.reset_index(drop=True)


def write_dataset(ds: Dataset, base: Path) -> Path:
    d = cohort_dir(base, ds.source, ds.cohort)
    d.mkdir(parents=True, exist_ok=True)
    for name, df in ds.tables.items():
        df = coerce(df, name)
        for col, (typ, _) in SCHEMA[name].items():
            if typ == "date":
                df[col] = df[col].dt.strftime("%Y-%m-%d")
        df.to_csv(d / f"{name}.csv", index=False, encoding="utf-8")
    return d


def require_cohorts(base: Path, source: str, cohorts, *, require_all: bool = True) -> list[str]:
    """Kanonik verisi olan kohortlar (`<base>/<source>/<kohort>/patients.csv`).

    require_all=True: biri eksikse hata; False: en az biri yeterli (NB0 — Faz 1'de C3 yok). Hata mesajı ne
    yapılacağını söyler: SANDBOX_SOURCE yanlış (varsayılan 'synthetic'; enclave'de 'nabidh') ya da veri henüz
    ingest edilmemiş. Böylece notebook ilk hücrede anlaşılır biçimde durur.
    """
    cohorts = list(cohorts)
    present = [c for c in cohorts if (cohort_dir(base, source, c) / "patients.csv").is_file()]
    missing = [c for c in cohorts if c not in present]
    if present and not (require_all and missing):
        return present
    base = Path(base)
    others = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name != source) if base.is_dir() else []
    raise FileNotFoundError(
        f"{base / source} altında {', '.join(missing)} kanonik verisi yok (SANDBOX_SOURCE={source!r}). "
        f"Kanonik verisi olan diğer kaynaklar: {', '.join(others) or 'yok'}.\n"
        f"  Kaynak yanlışsa (enclave'de 'nabidh'): terminalde `SANDBOX_SOURCE=nabidh python notebooks/<nb>.py`; "
        f"Jupyter'de en üste `%env SANDBOX_SOURCE=nabidh` hücresi ekleyip baştan çalıştır; "
        f"IntelliJ'de '(enclave)' run configuration'ları.\n"
        f"  Veri henüz yoksa önce: `python tools/ingest_nabidh.py --input iris` (docs/faz1_c1_c2.md).")


def read_dataset(base: Path, source: str, cohort: str) -> Dataset:
    d = cohort_dir(base, source, cohort)
    tables = {}
    for name in TABLES:
        p = d / f"{name}.csv"
        if not p.exists():
            if name in OPTIONAL_TABLES:
                tables[name] = coerce(pd.DataFrame(columns=list(SCHEMA[name])), name)
                continue
            raise FileNotFoundError(p)
        raw = pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8")
        tables[name] = coerce(raw, name)
    return Dataset(source=source, cohort=cohort, tables=tables)


# --------------------------------------------------------------------------
# Doğrulama
# --------------------------------------------------------------------------
def validate(ds: Dataset) -> pd.DataFrame:
    """Şema ve temel veri kalitesi kontrolleri. Her satır bir kontrol sonucudur.

    severity: ERROR (analizi durdurur) / WARN (raporlanır) / INFO
    """
    rows: list[dict] = []

    def add(table, check, severity, n_bad, detail=""):
        rows.append({"table": table, "check": check, "severity": severity,
                     "n_affected": int(n_bad), "detail": detail})

    pts = ds["patients"]
    pid_set = set(pts["patient_id"].dropna())
    add("patients", "duplicate patient_id", "ERROR" if pts["patient_id"].duplicated().any() else "INFO",
        pts["patient_id"].duplicated().sum())
    bad_sex = ~pts["sex"].isin(["Male", "Female"])
    add("patients", "sex not Male/Female", "WARN" if bad_sex.any() else "INFO", bad_sex.sum(),
        ", ".join(map(str, pts.loc[bad_sex, "sex"].dropna().unique()[:5])))

    for name, df in ds.tables.items():
        for col, (typ, req) in SCHEMA[name].items():
            if req:
                miss = df[col].isna()
                if name == "observations" and col == "date" and "concept" in df:
                    fh = miss & df["concept"].eq("family_history_dm").fillna(False).astype(bool)
                    add(name, "family history without date (date not used, D27)", "INFO", fh.sum())
                    miss &= ~fh
                add(name, f"missing required {col}", "ERROR" if miss.any() else "INFO", miss.sum())
        if name != "patients" and len(df):
            orphan = ~df["patient_id"].isin(pid_set)
            add(name, "patient_id not in patients", "WARN" if orphan.any() else "INFO", orphan.sum())
        if "date" in df.columns and len(df):
            future = df["date"] > pd.Timestamp.today()
            old = df["date"] < pd.Timestamp("1900-01-01")
            add(name, "implausible date", "WARN" if (future | old).any() else "INFO", (future | old).sum())

    labs = ds["labs"]
    if len(labs):
        neg = labs["value"] < 0
        add("labs", "negative lab value", "WARN" if neg.any() else "INFO", neg.sum())
        unit_mix = labs.groupby("loinc")["unit"].nunique()
        mixed = unit_mix[unit_mix > 1]
        add("labs", "multiple units per LOINC", "WARN" if len(mixed) else "INFO", len(mixed),
            ", ".join(mixed.index[:10]))

    if len(pts):
        dob = pts["date_of_birth"]
        bad = dob > pd.Timestamp.today()
        add("patients", "date_of_birth in future", "ERROR" if bad.any() else "INFO", bad.sum())

    return pd.DataFrame(rows)
