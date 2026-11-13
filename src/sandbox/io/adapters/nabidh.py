"""NABIDH (enclave) ham verisi → kanonik şema.

Format enclave'de netleşecek. Bu modül, kaynak dosyaları kanonik tablolara
sütun eşlemesiyle (MAPPING) çevirir. Pazartesi yapılacak iş: MAPPING'i gerçek
dosya/sütun adlarıyla doldurmak; kod değişikliği gerekmemeli.

İki olası teslim biçimi desteklenir:
1. Olay düzeyi tablolar (tanı, ilaç, lab, gözlem ayrı dosyalar) → MAPPING ile.
2. Lab ve gözlemler tek "measurements" dosyasında → split_measurements() LOINC'e göre ayırır.
(Hasta başı düz dosya gelirse ayrı bir flat adapter yazılacak.)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ... import codelists
from ..schema import Dataset, coerce
from .synthetic import read_raw_csv

# canonical_table -> {"file": kaynak dosya, "columns": {kanonik_sütun: kaynak_sütun}, "constants": {...}}
# Örnek değerler; enclave'de gerçek adlarla güncellenecek.
MAPPING: dict[str, dict] = {
    "patients": {"file": "patients.csv", "columns": {
        "patient_id": "patient_id", "sex": "sex", "date_of_birth": "date_of_birth",
        "ethnicity_raw": "ethnicity", "nationality": "nationality", "facility_id": "facility_id"}},
    "conditions": {"file": "diagnoses.csv", "columns": {
        "patient_id": "patient_id", "code_system": "code_system", "code": "code",
        "description": "description", "date": "diagnosis_date"}},
    "medications": {"file": "medications.csv", "columns": {
        "patient_id": "patient_id", "atc_code": "atc_code", "drug_name": "drug_name",
        "date": "prescription_date", "route": "route"}},
    "measurements": {"file": "measurements.csv", "columns": {
        "patient_id": "patient_id", "code": "loinc", "test_name": "name",
        "value": "value", "unit": "unit", "date": "date"}, "constants": {"code_system": "LOINC"}},
    "encounters": {"file": "encounters.csv", "columns": {
        "patient_id": "patient_id", "encounter_id": "encounter_id", "date": "encounter_date",
        "facility_id": "facility_id", "encounter_type": "encounter_type"}, "optional": True},
}

SEX_MAP = {"M": "Male", "MALE": "Male", "1": "Male", "F": "Female", "FEMALE": "Female", "2": "Female"}


def _apply(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    missing = [src for src in spec["columns"].values() if src not in df.columns]
    if missing:
        raise KeyError(f"{spec['file']}: kaynakta bulunmayan sütunlar: {missing}. "
                       f"Mevcut: {list(df.columns)}")
    out = pd.DataFrame({canon: df[src] for canon, src in spec["columns"].items()})
    for k, v in spec.get("constants", {}).items():
        out[k] = v
    return out


def split_measurements(m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Tek ölçüm tablosunu LOINC'e göre labs ve observations'a ayırır."""
    code = m["code"].astype("string").str.strip()
    is_lab = code.isin(codelists.LOINC_LAB.keys())
    labs = m[is_lab].rename(columns={"code": "loinc"})
    obs = m[~is_lab].copy()
    keys = list(zip(obs["code_system"].astype(str), code[~is_lab].astype(str)))
    obs["concept"] = [codelists.OBS_CODE_TO_CONCEPT.get(k, f"unmapped:{k[1]}") for k in keys]
    return labs, obs


def load(raw_dir: Path, cohort: str, mapping: dict | None = None) -> Dataset:
    mapping = mapping or MAPPING
    raw_dir = Path(raw_dir)
    t: dict[str, pd.DataFrame] = {}
    for name, spec in mapping.items():
        p = raw_dir / spec["file"]
        if not p.exists():
            if spec.get("optional"):
                continue
            raise FileNotFoundError(p)
        t[name] = _apply(read_raw_csv(p), spec)

    if "measurements" in t:
        labs, obs = split_measurements(t.pop("measurements"))
        t["labs"] = pd.concat([t.get("labs", pd.DataFrame()), labs], ignore_index=True)
        t["observations"] = pd.concat([t.get("observations", pd.DataFrame()), obs], ignore_index=True)

    pts = t["patients"]
    pts["sex"] = pts["sex"].astype("string").str.strip().str.upper().map(SEX_MAP).fillna(pts["sex"])

    tables = {n: coerce(t.get(n, pd.DataFrame()), n) for n in
              ["patients", "conditions", "medications", "labs", "observations", "encounters"]}
    return Dataset(source="nabidh", cohort=cohort, tables=tables)
