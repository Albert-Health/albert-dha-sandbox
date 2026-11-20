"""Canonical data schema, reading/writing and validation.

Whatever the source format (NABIDH raw CSV, one-row-per-patient flat file, synthetic),
the adapters turn the data into the 6 long-format tables defined here. Analysis code reads
ONLY this schema.

File rules: UTF-8 CSV, ISO-8601 dates (YYYY-MM-DD), codes as text.
Location: data/canonical/<source>/<cohort>/<table>.csv
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# type: "str" | "date" | "float"
SCHEMA: dict[str, dict[str, tuple[str, bool]]] = {
    # column: (type, required)
    "patients": {
        "patient_id": ("str", True),
        "sex": ("str", True),                # Male / Female
        "date_of_birth": ("date", True),
        "ethnicity_raw": ("str", False),     # most granular category in the source
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
        "value": ("str", True),              # numeric or categorical (smoking) → stored as str
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
# Days that look like a source system's default rather than a real date (1970-01-01 = Unix epoch). validate() counts
# them per table and date column (WARN); the rows are kept — whether to drop them is a medical team decision.
PLACEHOLDER_DATES = ("1970-01-01", "1900-01-01")


@dataclass
class Dataset:
    """The canonical tables of one cohort."""
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
    """Casts columns to the schema types; adds missing optional columns as empty, drops extra ones."""
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
    """Cohorts that have canonical data (`<base>/<source>/<cohort>/patients.csv`).

    require_all=True: error if any is missing; False: at least one is enough (NB0 — no C3 in Phase 1). The error
    message says what to do: SANDBOX_SOURCE is wrong (default 'synthetic'; 'nabidh' in the enclave) or the data
    has not been ingested yet. So a notebook stops in its first cell with a clear message.
    """
    cohorts = list(cohorts)
    present = [c for c in cohorts if (cohort_dir(base, source, c) / "patients.csv").is_file()]
    missing = [c for c in cohorts if c not in present]
    if present and not (require_all and missing):
        return present
    base = Path(base)
    others = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name != source) if base.is_dir() else []
    raise FileNotFoundError(
        f"No canonical data for {', '.join(missing)} under {base / source} (SANDBOX_SOURCE={source!r}). "
        f"Other sources with canonical data: {', '.join(others) or 'none'}.\n"
        f"  If the source is wrong ('nabidh' in the enclave): in a terminal "
        f"`SANDBOX_SOURCE=nabidh python notebooks/<nb>.py`; "
        f"in Jupyter add a `%env SANDBOX_SOURCE=nabidh` cell at the top and run from the start; "
        f"in IntelliJ the '(enclave)' run configurations.\n"
        f"  If there is no data yet, first: `python tools/ingest_nabidh.py --input iris` (docs/faz1_c1_c2.md).")


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
# Validation
# --------------------------------------------------------------------------
def validate(ds: Dataset) -> pd.DataFrame:
    """Schema and basic data quality checks. Each row is one check result.

    severity: ERROR (stops the analysis) / WARN (reported) / INFO
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
                    sm = miss & df["concept"].eq("smoking_status").fillna(False).astype(bool)
                    add(name, "smoking record without date (used only if all agree, D28)", "INFO", sm.sum())
                    miss &= ~(fh | sm)
                add(name, f"missing required {col}", "ERROR" if miss.any() else "INFO", miss.sum())
        if name != "patients" and len(df):
            orphan = ~df["patient_id"].isin(pid_set)
            add(name, "patient_id not in patients", "WARN" if orphan.any() else "INFO", orphan.sum())
        if "date" in df.columns and len(df):
            future = df["date"] > pd.Timestamp.today()
            old = df["date"] < pd.Timestamp("1900-01-01")
            add(name, "implausible date", "WARN" if (future | old).any() else "INFO", (future | old).sum())
        for col in [c for c, (typ, _) in SCHEMA[name].items() if typ == "date"]:
            if col in df.columns and len(df):
                day = pd.to_datetime(df[col], errors="coerce").dt.normalize()
                for ph in PLACEHOLDER_DATES:
                    n = int((day == pd.Timestamp(ph)).sum())
                    add(name, f"{col} exactly {ph} (placeholder? counted, kept)", "WARN" if n else "INFO", n)

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
