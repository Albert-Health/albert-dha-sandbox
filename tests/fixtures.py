"""Small hand-made test dataset — the expected results of the cohort rules are known."""
from __future__ import annotations

import pandas as pd

from sandbox.io.schema import Dataset, coerce


def _df(rows, cols):
    return pd.DataFrame(rows, columns=cols)


def tiny_dataset() -> Dataset:
    """
    P01 C3 eligible: 2019 normal HbA1c, 2021 HbA1c 6.8 → incident (lab_hba1c)
    P02 C3 eligible: 2019 normal FPG, 2022 normal HbA1c → non-event, censored 2022
    P03 not C3: no measurement after index
    P04 not C3: 2018 R73 (prediabetes) before the normal value → prevalent
    P05 not C3: E10 (T1D) → excluded everywhere
    P06 not C3: aged 22 at index
    P07 C3 eligible but medication-only outcome: 2023 A10 → no event in the primary, event in the sensitivity
    P08 positive pool (T2DM, diagnosis), all 8 variables complete → C1 candidate
    P09 positive pool (prediabetes lab), no smoking record → not C1, C2 candidate
    P10 C3: 2018 A10, 2019 normal HbA1c → prevalent (medication) → excluded
    P11 C3 candidate: 2019-01-01 normal HbA1c, HbA1c 6.9 45 days later → excluded with the default 90-day
        washout (D1); incident with washout 0
    """
    # Nationality (PARAMS["ethnicity_source"] = "nationality") in different spellings: name, ISO3, ISO2, adjective
    pts = _df([
        ("P01", "Male", "1970-01-01", "Emirati", "United Arab Emirates", "F1"),
        ("P02", "Female", "1965-06-15", "Indian", "IND", "F1"),
        ("P03", "Male", "1960-01-01", "Pakistani", "Pakistan", "F2"),
        ("P04", "Female", "1975-01-01", "Filipino", "PH", "F2"),
        ("P05", "Male", "1980-01-01", "Emirati", "UAE", "F1"),
        ("P06", "Female", "1997-01-01", "Western", "British", "F3"),
        ("P07", "Male", "1955-01-01", "Not recorded", None, "F3"),
        ("P08", "Male", "1960-01-01", "Emirati", "United Arab Emirates", "F1"),
        ("P09", "Female", "1985-01-01", "Indian", "India", "F1"),
        ("P10", "Male", "1950-01-01", "Indian", "Iran", "F2"),
        ("P11", "Female", "1970-01-01", "Arab (non-Gulf)", "Egypt", "F2"),
    ], ["patient_id", "sex", "date_of_birth", "ethnicity_raw", "nationality", "facility_id"])

    labs = _df([
        ("P01", "4548-4", "HbA1c", 5.4, "%", "2019-03-01"),
        ("P01", "4548-4", "HbA1c", 6.8, "%", "2021-05-01"),
        ("P02", "1558-6", "FPG", 92, "mg/dL", "2019-04-01"),
        ("P02", "4548-4", "HbA1c", 5.5, "%", "2022-02-01"),
        ("P03", "4548-4", "HbA1c", 5.2, "%", "2020-01-01"),
        ("P04", "4548-4", "HbA1c", 5.3, "%", "2019-01-01"),
        ("P04", "4548-4", "HbA1c", 5.4, "%", "2020-01-01"),
        ("P05", "4548-4", "HbA1c", 5.3, "%", "2019-01-01"),
        ("P05", "4548-4", "HbA1c", 5.3, "%", "2020-01-01"),
        ("P06", "4548-4", "HbA1c", 5.1, "%", "2019-01-01"),
        ("P06", "4548-4", "HbA1c", 5.2, "%", "2020-01-01"),
        ("P07", "4548-4", "HbA1c", 5.6, "%", "2019-01-01"),
        ("P07", "4548-4", "HbA1c", 5.6, "%", "2024-01-01"),
        ("P09", "4548-4", "HbA1c", 6.0, "%", "2021-01-01"),
        ("P10", "4548-4", "HbA1c", 5.5, "%", "2019-01-01"),
        ("P10", "4548-4", "HbA1c", 5.6, "%", "2020-01-01"),
        ("P11", "4548-4", "HbA1c", 5.4, "%", "2019-01-01"),
        ("P11", "4548-4", "HbA1c", 6.9, "%", "2019-02-15"),
    ], ["patient_id", "loinc", "test_name", "value", "unit", "date"])

    cond = _df([
        ("P04", "ICD-10", "R73.03", "Prediabetes", "2018-06-01"),
        ("P05", "ICD-10", "E10.9", "T1D", "2021-01-01"),
        ("P08", "ICD-10", "E11.9", "T2D", "2020-01-01"),
        ("P08", "ICD-10", "I10", "HTN", "2019-01-01"),
        ("P02", "ICD-10", "Z83.3", "FH DM", "2018-01-01"),
    ], ["patient_id", "code_system", "code", "description", "date"])

    meds = _df([
        ("P07", "A10BA02", "Metformin", "2023-01-01", "Oral"),
        ("P08", "C09AA02", "Enalapril", "2019-02-01", "Oral"),
        ("P10", "A10BA02", "Metformin", "2018-06-01", "Oral"),
    ], ["patient_id", "atc_code", "drug_name", "date", "route"])

    obs = _df([
        ("P01", "bmi", "LOINC", "39156-5", "29.1", "kg/m2", "2019-02-01"),
        ("P02", "height_cm", "LOINC", "8302-2", "160", "cm", "2015-01-01"),
        ("P02", "weight_kg", "LOINC", "3141-9", "64", "kg", "2019-01-01"),
        ("P08", "bmi", "LOINC", "39156-5", "31.0", "kg/m2", "2020-01-01"),
        ("P08", "smoking_status", None, None, "ex", None, "2020-01-01"),
        ("P09", "bmi", "LOINC", "39156-5", "24.0", "kg/m2", "2021-01-01"),
        ("P01", "smoking_status", None, None, "never", None, "2019-02-01"),
    ], ["patient_id", "concept", "code_system", "code", "value", "unit", "date"])

    tables = {
        "patients": coerce(pts, "patients"),
        "labs": coerce(labs, "labs"),
        "conditions": coerce(cond, "conditions"),
        "medications": coerce(meds, "medications"),
        "observations": coerce(obs, "observations"),
        "encounters": coerce(pd.DataFrame(), "encounters"),
    }
    return Dataset(source="test", cohort="full", tables=tables)
