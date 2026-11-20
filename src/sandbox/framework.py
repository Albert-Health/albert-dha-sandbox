"""Applicant Data Requirement Framework Match by variable: Match / Partial / Absent.

KPI & Graduation Framework (Universal KPI): did the 8 requested core variables arrive, and in the requested form?
NB0 reports it per cohort and per variable (`match_table`):

- Absent  — no patient has a usable value (the field, view or codes did not arrive).
- Partial — arrived, but not as requested:
    (a) more than `framework_derived_max_pct` of the records are not in the requested code system and were derived by
        the adapter (drug code / name → ATC, family history recognised from text);
    (b) a substitute field, or only some of the requested levels, came (ethnicity from the EthnicGroup field instead
        of nationality; smoking without an ex-smoker level);
    (c) only one half of a derived variable arrived (treated hypertension needs a diagnosis and a drug);
    (d) fewer than `framework_min_patient_pct` of the patients have a value (recorded variables only; a diagnosis
        flag such as CVD is present / absent by nature).
- Match   — arrived as requested.

How full a variable is stays with the Data Completeness KPI (≥ 90%); (d) only catches a variable that arrived for a
small part of the patients. The form of the delivery (native vs derived, view / column) comes from the adapter
(`nabidh.delivery_facts`, kept in <cohort>/ingest.json); a source without those facts (synthetic data) counts as
delivered as requested. The thresholds are [DECISION PENDING] (config.PARAMS framework_*).

Overall (`overall`): Match if every variable of every cohort matches and no requested code group is missing;
No match if nothing arrived; otherwise Partial.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import codelists, cohorts, phenotype, sdc
from .config import PARAMS
from .io import schema

SMOKING_LEVELS = {0: "never", 1: "ex", 2: "light", 3: "moderate", 4: "heavy"}
COLUMNS = ["cohort", "variable", "requested", "source_field", "route", "n_patients", "patients_with_value",
           "pct_patients", "status", "reason"]


def read_delivery(base: Path, source: str, cohort: str) -> dict:
    """The adapter's delivery facts for one cohort (<canonical>/<source>/<cohort>/ingest.json); {} if absent."""
    f = schema.cohort_dir(base, source, cohort) / "ingest.json"
    try:
        return dict(json.loads(f.read_text(encoding="utf-8")).get("delivery") or {})
    except (OSError, ValueError):
        return {}


def _pct(n: int, total: int, threshold: int) -> str:
    """Share as text; a count under the small-cell threshold shows no percentage (it could be turned back into the count)."""
    if not total:
        return "n/a"
    return f"<{threshold} patients" if 0 < n < threshold else f"{100 * n / total:.1f}%"


def _derived_pct(facts: dict, key: str) -> float | None:
    """Share (%) of the rows not in the requested code system; None without delivery facts."""
    f = (facts or {}).get(key) or {}
    rows = f.get("rows") or 0
    return 100.0 * (rows - f.get("as_requested_rows", 0)) / rows if rows else None


def _reference(ds, ids: pd.Index) -> pd.Series:
    try:
        end = cohorts.data_end_date(ds)
    except ValueError:                                  # no dated record at all
        end = pd.Timestamp.today().normalize()
    return pd.Series(end, index=ids)


def _cohort_rows(cohort: str, ds, facts: dict, p: dict) -> list[dict]:
    ids = pd.Index(ds["patients"]["patient_id"].dropna().unique())
    snap = phenotype.core_snapshot(ds, _reference(ds, ids), lookback_days=None, p=p)   # full history, all patients
    n = len(snap)
    thr, min_pct, tol = p["small_cell_threshold"], p["framework_min_patient_pct"], p["framework_derived_max_pct"]
    fields = (facts or {}).get("fields", {})
    rows: list[dict] = []

    def add(var: str, n_with: int, route: str, partial: list[str], absent: str = "no usable value",
            recorded: bool = True) -> None:
        partial = list(partial)
        if n_with == 0:
            status, why = "Absent", absent
        else:
            if recorded and n and 100 * n_with / n < min_pct:
                partial.append(f"values for only {_pct(n_with, n, thr)} of patients (< {min_pct}%)")
            status, why = ("Partial", "; ".join(partial)) if partial else ("Match", "")
        rows.append({"cohort": cohort, "variable": var, "requested": codelists.FRAMEWORK_REQUESTED[var],
                     "source_field": fields.get(var, ""), "route": route, "n_patients": n,
                     "patients_with_value": int(n_with), "pct_patients": round(100 * n_with / n, 1) if n else None,
                     "status": status, "reason": why})

    add("sex", int(snap["ok_sex"].sum()), "as_requested", [])
    add("age", int(snap["ok_age"].sum()), "as_requested", [])

    # Ethnicity: the requested source (PARAMS["ethnicity_source"]); the other field is a substitute
    src_col = codelists.ETHNICITY_SOURCE_COLUMN
    pts = ds["patients"].drop_duplicates("patient_id")
    got = {s: int(phenotype.ethnicity_recorded(pts[c]).sum()) if c in pts else 0 for s, c in src_col.items()}
    want = p["ethnicity_source"]
    other = next(s for s in src_col if s != want)
    if got[want]:
        add("ethnicity", got[want], "as_requested", [])
    elif got[other]:
        add("ethnicity", got[other], "substitute",
            [f"requested {src_col[want]} not delivered; only {src_col[other]} has values"])
    else:
        add("ethnicity", 0, "-", [], f"neither {src_col[want]} nor {src_col[other]} has a value")

    add("bmi", int(snap["ok_bmi"].sum()), "as_requested", [])

    cat = pd.to_numeric(snap["smoking_cat"], errors="coerce")
    short = [name for k, name in SMOKING_LEVELS.items() if int((cat == k).sum()) < thr]
    add("smoking", int(snap["ok_smoking"].sum()), "as_requested",
        [f"level seen in < {thr} patients: {', '.join(short)}"] if short else [])

    d = _derived_pct(facts, "family_history")
    far = d is not None and d > tol
    add("family_history", int(snap["family_history_recorded"].sum()), "derived" if far else "as_requested",
        [f"{d:.0f}% of the records not in the requested system ({facts['family_history']['requested_system']})"]
        if far else [])

    add("cvd", int(snap["cvd"].sum()), "as_requested", [], recorded=False)

    dx, med = int(snap["htn_dx"].sum()), int(snap["htn_med"].sum())
    d = _derived_pct(facts, "medications")
    far = d is not None and d > tol
    partial = []
    if dx == 0 < med:
        partial.append("no hypertension diagnosis arrived (drug only)")
    if med == 0 < dx:
        partial.append("no antihypertensive drug arrived (diagnosis only)")
    if far:
        partial.append(f"drug: {d:.0f}% of the rows not in the requested system ({facts['medications']['requested_system']})")
    add("hypertension", int(snap["htn_lrs"].sum()), "derived" if far else "as_requested", partial, recorded=False)
    return rows


def match_table(data: dict, delivery: dict | None = None, p: dict = PARAMS) -> pd.DataFrame:
    """data: {cohort: Dataset}; delivery: {cohort: adapter delivery facts}. One row per cohort × core variable."""
    delivery = delivery or {}
    rows = [r for c, ds in data.items() for r in _cohort_rows(c, ds, delivery.get(c) or {}, p)]
    return pd.DataFrame(rows, columns=COLUMNS)


def suppressed(table: pd.DataFrame, threshold: int | None = None) -> pd.DataFrame:
    """The table as it leaves the enclave: counts under the small-cell threshold → "<10", and the percentage with them
    ("<10 patients"); the percentage also where n_patients − count is under it ("suppressed (<10)", sdc.suppress_rates)."""
    threshold = threshold or PARAMS["small_cell_threshold"]
    n = pd.to_numeric(table["patients_with_value"], errors="coerce")
    out = sdc.suppress_rates(table, "patients_with_value", ["n_patients"], ["pct_patients"], threshold)
    out.loc[n.notna() & (n > 0) & (n < threshold), "pct_patients"] = f"<{threshold} patients"
    return sdc.suppress_small_counts(out, ["n_patients", "patients_with_value"], threshold)


def overall(table: pd.DataFrame, missing_groups=()) -> str:
    """Match / Partial / No match over all cohorts and variables (module docstring); missing_groups = requested code
    groups no patient has (NB0 framework_match.csv): any of them rules out Match."""
    if table.empty or (table["status"] == "Absent").all():
        return "No match"
    return "Match" if (table["status"] == "Match").all() and not list(missing_groups) else "Partial"


def non_match(table: pd.DataFrame) -> dict[str, dict[str, str]]:
    """{variable: {cohort: status}} for every variable that is not a Match in some cohort."""
    bad = table[table["status"] != "Match"]
    out: dict[str, dict[str, str]] = {}
    for var in codelists.CORE_VARIABLES:
        rows = bad[bad["variable"] == var]
        if len(rows):
            out[var] = dict(zip(rows["cohort"], rows["status"]))
    return out
