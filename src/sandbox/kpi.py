"""DFF Health Data Sandbox KPI table (KPI & Graduation Framework v4 / Albert V2.0).

Fills the Actual / Met values from the `kpi_values.json` outputs of NB0 / NB1 / NB2, the audit log and the
latest evidence package checklist. Phase 1 (C1 / C2, NB1): joint completeness and score computability per cohort,
the C1 detection rate in known positives (sensitivity only — C1 / C2 have no negatives) and the C1–C2 selection
effect. Phase 2 (C3, NB2) adds its own joint completeness and the threshold / discrimination / calibration KPIs. Graduation rule: any Critical KPI
Not Met → Do Not Graduate; otherwise a non-critical Met rate ≥80% Graduate, 50–79% Graduate with Mitigation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import sdc
from .config import AUDIT_DIR, OUTPUT_DIR, PARAMS

KPI_ROWS = [
    # kpi, category, owner, target, critical
    ("Audit Trail Completeness", "Governance (Universal)", "Sandbox/DFF", "100%", True),
    ("Evidence Package Completeness", "Governance (Universal)", "Sandbox/DFF", "Complete", True),
    ("Data Security / No-Incident", "Governance (Universal)", "Sandbox/DFF", "0 incidents", True),
    ("Applicant Data Requirement Framework Match", "Universal", "Applicant", "Match", False),
    ("Data Completeness for Required Variables", "Data", "DHA", ">= 90%", False),
    ("Joint Completeness - LRS", "Data / Feasibility", "Applicant", "Report % and N", False),
    ("Joint Completeness - QDiabetes", "Data / Feasibility", "Applicant", "Report % and N", False),
    ("Sensitivity (Recall, positive class)", "Clinical", "Applicant", ">= 70%", False),
    ("Specificity", "Clinical", "Applicant", ">= 70%", False),
    ("NPV & PPV", "Clinical", "Applicant", "Documented", False),
    ("AUROC", "Technical", "Applicant", ">= 0.75", False),
    ("C-Index", "Technical", "Applicant", "0.55-0.90", False),
    ("Precision / Recall / F1", "Technical", "Applicant", "Documented", False),
    ("Recalibration Slope / O:E", "Technical", "Applicant", "Documented", False),
    ("Alert Rate per 1,000 Patients", "Operational", "Applicant", "Pending NABIDH", False),
]


def latest_run(prefix: str, source: str | None = None, base: Path = OUTPUT_DIR) -> Path | None:
    """Latest successfully finished run folder whose name contains prefix (by manifest started_utc).
    If source is given, only runs on that data source (synthetic / nabidh / synthetic_pc)."""
    best, best_ts = None, ""
    for m in base.glob(f"*{prefix}*/run_manifest.json"):
        rec = json.loads(m.read_text(encoding="utf-8"))
        rec_source = rec.get("source") or "synthetic"     # runs from before the source field were synthetic
        if source is not None and rec_source != source:
            continue
        if rec.get("status") == "success" and rec.get("started_utc", "") > best_ts:
            best, best_ts = m.parent, rec["started_utc"]
    return best


def _load(run_dir: Path | None, rel: str) -> dict:
    if run_dir is None or not (run_dir / rel).exists():
        return {}
    return json.loads((run_dir / rel).read_text(encoding="utf-8"))


def audit_completeness(log: Path = AUDIT_DIR / "audit_log.jsonl", running=()) -> dict:
    """Share of audit runs that were closed. `running`: run ids still in progress (the enclave run that started the
    KPI step, SANDBOX_PARENT_RUN) — not counted, as they close after this step."""
    starts, ends = set(), set()
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("event") == "run_start":
                starts.add(ev["run_id"])
            elif ev.get("event") == "run_end":
                ends.add(ev["run_id"])
    starts -= set(running)
    pct = 100.0 * len(starts & ends) / len(starts) if starts else float("nan")
    return {"runs": len(starts), "closed": len(starts & ends), "pct": pct, "open": sorted(starts - ends)}


def _fmt(x, nd=3):
    if x is None or (isinstance(x, float) and x != x):
        return None
    return round(x, nd) if isinstance(x, float) else x


def _pct(x) -> str | None:
    x = _fmt(x, 1)
    return None if x is None else f"{x}%"


def _cohort_pcts(pcts: dict, ns: dict | None = None, n_key: str | None = None) -> str:
    """{"c1": 62.5, "c2": 40.0} (+ NB1 joint_n) → "C1 62.5% (N=125/200); C2 40.0% (N=<10/20)"; counts < 10
    suppressed."""
    out = []
    for c, v in (pcts or {}).items():
        if _pct(v) is None:
            continue
        n = (ns or {}).get(c)
        out.append(f"{c.upper()} {_pct(v)}" + (f" (N={sdc.fmt_count(n[n_key])}/{sdc.fmt_count(n['n'])})"
                                                 if n and n_key else ""))
    return "; ".join(out)


# NB1 c1_detection_pct keys are "<reference>|<score>" (cohorts.POSITIVE_REFERENCES × qdiabetes / lrs)
def _c1_detection(nb1: dict) -> str:
    det = {k: v for k, v in (nb1.get("c1_detection_pct") or {}).items() if _pct(v) is not None}
    parts = []
    for score, name in (("qdiabetes", "QDiabetes"), ("lrs", nb1.get("lrs_label", "LRS"))):
        got = [f"{k.split('|')[0]} {_pct(v)}" for k, v in det.items() if k.split("|")[-1] == score]
        if got:
            parts.append(f"{name}: " + ", ".join(got))
    return ("C1 " + "; ".join(parts)) if parts else ""


def _selection_effect(nb1: dict) -> str:
    smd = _fmt(nb1.get("selection_effect_max_abs_smd"))
    if smd is None:
        return ""
    imb = nb1.get("selection_effect_imbalanced_vars") or []
    return (f"C1–C2 selection effect: max |SMD| {smd}"
            + (f"; |SMD| > 0.1: {', '.join(imb[:8])}" if imb else "; no variable with |SMD| > 0.1"))


def _safe_pct(pct, k, n) -> str:
    """A rate as text, unless its count or (n − count) is under the small-cell threshold (sdc.suppress_rates)."""
    t = PARAMS["small_cell_threshold"]
    if any(0 < x < t for x in (k, n - k)):
        return f"suppressed (<{t})"
    return _pct(pct) or "—"


def _completeness_note(nb0: dict) -> str:
    """Data Completeness note: the weakest variable, the weakest of the other 7 (without ethnicity), joint core-7 and
    the present / absent variables (100% by definition). The KPI value itself stays the minimum over the 8."""
    parts = []
    weakest, mins = nb0.get("data_completeness_weakest") or {}, nb0.get("data_completeness_min_core8_pct") or {}
    if weakest:
        parts.append("Weakest variable: " + "; ".join(
            f"{c.upper()} {v}" + (f" {_pct(mins[c])}" if c in mins else "") for c, v in weakest.items()))
    wo = nb0.get("data_completeness_without_ethnicity") or {}
    if wo:
        parts.append("Without ethnicity (weakest of the other 7): " + "; ".join(
            f"{c.upper()} {r['variable']} {_safe_pct(r['pct'], r['complete_n'], r['n'])}" for c, r in wo.items()))
    j7 = nb0.get("joint_core7") or {}
    if j7:
        parts.append("Joint core-7 (all but ethnicity): " + "; ".join(
            f"{c.upper()} {_safe_pct(r['pct'], r['core7_n'], r['n'])} "
            f"(N={sdc.fmt_count(r['core7_n'])}/{sdc.fmt_count(r['n'])})" for c, r in j7.items()))
    pa = nb0.get("completeness_present_absent")
    if pa:
        parts.append(f"Present / absent, 100% by definition (not a fill rate): {', '.join(pa)}")
    return " · ".join(parts)


FRAMEWORK_MET = {"Match": "Met", "Partial": "Partial", "No match": "Not Met"}


def _framework_match(nb0: dict) -> tuple[str, str, str, str]:
    """NB0 kpi_values → (actual, met, source, notes) of the Framework Match row. Match = every requested variable
    arrived as requested; Partial = something arrived, not all as requested (framework.py); No match = nothing
    arrived. "Partial" is neither Met nor Not Met: graduation() leaves it out of the evaluated KPIs [decision pending]."""
    source = "NB0 nb00/kpi_values.json"
    status = nb0.get("framework_status")
    if status is None:               # NB0 run from before the Match / Partial split: code groups only
        return ("Match" if nb0["framework_match"] else "Missing: " + ", ".join(nb0["framework_missing_groups"][:6]),
                "Met" if nb0["framework_match"] else "Not Met", source, "")
    bad = nb0.get("framework_variables") or {}
    notes = [f"{v}: " + ", ".join(f"{c.upper()} {s}" for c, s in by_cohort.items()) for v, by_cohort in bad.items()]
    if nb0.get("framework_missing_groups"):
        notes.append("requested code groups not received: " + ", ".join(nb0["framework_missing_groups"][:6]))
    if status == "Partial":
        notes.append("Partial is not counted as Met or Not Met in the graduation rate [decision pending]")
    return (status + (": " + ", ".join(bad) if bad and status != "Match" else ""),
            FRAMEWORK_MET.get(status, "Pending"), source, " · ".join(notes))


NB2_ONLY = ["Specificity", "NPV & PPV", "AUROC", "C-Index", "Precision / Recall / F1", "Recalibration Slope / O:E",
            "Alert Rate per 1,000 Patients"]


def build(nb0: dict, nb1: dict, nb2: dict, evidence: dict, audit: dict, p: dict = PARAMS) -> pd.DataFrame:
    rows = {k: {"kpi": k, "category": c, "owner": o, "target": t, "critical": cr,
                "actual": None, "met": "Pending", "source": "", "notes": ""} for k, c, o, t, cr in KPI_ROWS}

    def set_(k, actual, met, source, notes=""):
        rows[k].update(actual=actual, met=met, source=source, notes=notes)

    if audit.get("runs"):
        set_("Audit Trail Completeness", f"{audit['pct']:.1f}% ({audit['closed']}/{audit['runs']} runs)",
             "Met" if audit["pct"] >= 100 else "Not Met", "outputs/audit/audit_log.jsonl",
             "Open runs: " + ", ".join(audit["open"][:5]) if audit["open"] else "")
    if evidence:
        set_("Evidence Package Completeness", f"{evidence['complete_sections']}/{evidence['total_sections']} sections",
             "Met" if evidence["complete"] else "Not Met", evidence.get("path", ""),
             "'Not Met' until the templates are filled in and signed" if not evidence["complete"] else "")
    set_("Data Security / No-Incident", f"{p['security_incidents']} incidents", "Met" if p["security_incidents"] == 0 else "Not Met",
         "config.security_incidents (manual)", "Manually confirmed from the enclave incident log")

    if nb0:
        fw = _framework_match(nb0)
        set_("Applicant Data Requirement Framework Match", *fw)
        dc = nb0["data_completeness_min_core8_pct"]
        set_("Data Completeness for Required Variables", "; ".join(f"{c.upper()} {v:.1f}%" for c, v in dc.items()),
             "Met" if all(v >= 90 for v in dc.values()) else "Not Met", "NB0",
             _completeness_note(nb0))

    lname = (nb2 or nb1).get("lrs_label", "LRS")
    lvariant = (nb2 or nb1).get("lrs_variant")
    joint = {"Joint Completeness - QDiabetes": ("joint_core8_pct", "core8_n", "qd_computable_pct", "qdiabetes",
                                                "Definition: 8 core variables"
                                                + (f" ({nb2['qd_variant']})" if nb2.get("qd_variant") else "")
                                                + " [awaiting confirmation with DFF]"),
             "Joint Completeness - LRS": ("joint_lrs_pct", "lrs_n", "lrs_computable_pct", "lrs",
                                          f"Variant: {lname} [K-LRS]" + ("" if lvariant == "assessment_2010"
                                                                         else " — no waist circumference needed"))}
    for k, (pct_key, n_key, comp_key, nb2_key, definition) in joint.items():
        parts, srcs, notes = [], [], []
        if nb1 and _cohort_pcts(nb1.get(pct_key)):
            parts.append(_cohort_pcts(nb1.get(pct_key), nb1.get("joint_n"), n_key))
            srcs.append("NB1 (C1/C2)")
            if _cohort_pcts(nb1.get(comp_key)):
                notes.append("Score computable: " + _cohort_pcts(nb1.get(comp_key)))
        if nb2:
            parts.append(f"C3 {nb2[f'joint_completeness_{nb2_key}_pct']}% "
                         f"(N={sdc.fmt_count(nb2[f'joint_completeness_{nb2_key}_n'])}/{sdc.fmt_count(nb2['c3_eligible_n'])})")
            srcs.append("NB2 (C3 base)")
        if parts:
            set_(k, "; ".join(parts), "Reported", " + ".join(srcs), " · ".join([definition, *notes]))

    c1_det, sel = (_c1_detection(nb1), _selection_effect(nb1)) if nb1 else ("", "")
    if nb1:
        sens_k = "Sensitivity (Recall, positive class)"
        if c1_det:
            set_(sens_k, c1_det, "Reported", "NB1 (C1 known positives)",
                 " · ".join(x for x in [
                     "Detection rate among C1 patients with a computable score (sensitivity only; C1/C2 have no "
                     "negatives). Not judged against the target: primary score / reference date not pre-specified "
                     "[decision pending]", sel] if x))
        else:
            set_(sens_k, None, "Pending", "NB1 (C1 known positives)",
                 " · ".join(x for x in [
                     "C1 detection rate: threshold not pre-specified (qd_risk_threshold_pct / "
                     "lprs_high_risk_threshold) [decision pending]", sel] if x))
        if not nb2:
            for k in NB2_ONLY:
                set_(k, None, "Pending", "NB2 (C3)", "Phase 2 (C3): C1/C2 hold known positives only")

    if nb2:
        auc, ci = nb2.get("auroc_qd"), nb2.get("auroc_qd_ci")
        if auc is not None:
            set_("AUROC", f"{auc:.3f}" + (f" (95% CI {ci[0]:.3f}–{ci[1]:.3f})" if ci else ""), "Met" if auc >= 0.75 else "Not Met",
                 "NB2 Arm 1, test", f"Time-dependent AUROC @ {nb2['horizon_years']}y (IPCW). {lname}: {_fmt(nb2.get('auroc_lrs'))}")
        c, cci = nb2.get("c_index_qd"), nb2.get("c_index_qd_ci")
        if c is not None:
            set_("C-Index", f"{c:.3f}" + (f" (95% CI {cci[0]:.3f}–{cci[1]:.3f})" if cci else ""),
                 "Met" if 0.55 <= c <= 0.90 else "Not Met", "NB2 Arm 1, test", f"{lname}: {_fmt(nb2.get('c_index_lrs'))}")
        set_("Recalibration Slope / O:E",
             f"Arm 1 O:E {_fmt(nb2.get('oe_qd_kol1'))}, slope {_fmt(nb2.get('cal_slope_qd_kol1'))}; "
             f"Arm 2a O:E {_fmt(nb2.get('oe_qd_kol2a'))}, slope {_fmt(nb2.get('cal_slope_qd_kol2a'))}",
             "Reported", "NB2")
        thr = nb2.get("qd_threshold", {})
        lthr = nb2.get("lrs_threshold", {})
        lrs_note = (f"{lname} ≥{_fmt(lthr.get('threshold'))}: sens {_fmt(lthr.get('sensitivity'))}, "
                    f"spec {_fmt(lthr.get('specificity'))}, PPV {_fmt(lthr.get('ppv'))}, NPV {_fmt(lthr.get('npv'))}, "
                    f"alert/1000 {_fmt(lthr.get('alert_rate_per_1000'), 1)}") if lthr.get("threshold") is not None \
            else f"{lname}: no threshold chosen [decision pending]"
        if "sensitivity" in thr:
            set_("Sensitivity (Recall, positive class)", f"{thr['sensitivity']:.3f}", "Met" if thr["sensitivity"] >= 0.70 else "Not Met", "NB2",
                 lrs_note + (f" · {c1_det}" if c1_det else ""))
            set_("Specificity", f"{thr['specificity']:.3f}", "Met" if thr["specificity"] >= 0.70 else "Not Met", "NB2", lrs_note)
            set_("NPV & PPV", f"PPV {thr['ppv']:.3f}, NPV {thr['npv']:.3f}", "Reported", "NB2", lrs_note)
            set_("Precision / Recall / F1", f"P {thr['precision']:.3f}, R {thr['recall']:.3f}, F1 {thr['f1']:.3f}", "Reported", "NB2")
            set_("Alert Rate per 1,000 Patients", f"{thr['alert_rate_per_1000']:.1f}", "Reported", "NB2")
        else:
            for k in ["Specificity", "NPV & PPV", "Precision / Recall / F1", "Alert Rate per 1,000 Patients"]:
                set_(k, None, "Pending", "NB2", "QDiabetes threshold not pre-specified (qd_risk_threshold_pct) [decision pending]. " + lrs_note)
            if not c1_det:          # otherwise the NB1 C1 detection rate stays in the row
                set_("Sensitivity (Recall, positive class)", None, "Pending", "NB2",
                     "QDiabetes threshold not pre-specified (qd_risk_threshold_pct) [decision pending]. " + lrs_note
                     + (f" · {sel}" if sel else ""))
    return pd.DataFrame(rows.values())


def graduation(table: pd.DataFrame) -> dict:
    crit = table[table["critical"]]
    non = table[~table["critical"]]
    if (crit["met"] == "Not Met").any():
        outcome = "Do Not Graduate (Critical Fail)"
    elif (crit["met"] == "Pending").any():
        outcome = "Pending"
    else:
        evaluable = non[non["met"].isin(["Met", "Not Met"])]
        rate = (evaluable["met"] == "Met").mean() if len(evaluable) else float("nan")
        outcome = "Graduate" if rate >= 0.8 else "Graduate with Mitigation" if rate >= 0.5 else "Pending"
    return {"outcome": outcome,
            "critical_met": int((crit["met"] == "Met").sum()), "critical_total": len(crit),
            "non_critical_met": int((non["met"] == "Met").sum()),
            "non_critical_evaluable": int(non["met"].isin(["Met", "Not Met"]).sum())}


def to_markdown(table: pd.DataFrame, grad: dict, meta: dict) -> str:
    lines = ["# KPI report — Albert Health × DHA Health Data Sandbox", "",
             f"- Generated: {meta.get('generated_utc')}  ·  Source: {meta.get('source')}",
             f"- Input runs: {', '.join(f'{k}={v}' for k, v in meta.get('runs', {}).items())}",
             f"- **Graduation pre-assessment:** {grad['outcome']} (Critical {grad['critical_met']}/{grad['critical_total']}; "
             f"non-critical Met {grad['non_critical_met']}/{grad['non_critical_evaluable']} evaluable)", "",
             "| KPI | Target | Critical | Owner | Actual | Status | Note |", "|---|---|---|---|---|---|---|"]
    for _, r in table.iterrows():
        lines.append(f"| {r['kpi']} | {r['target']} | {'Yes' if r['critical'] else 'No'} | {r['owner']} | "
                     f"{'—' if pd.isna(r['actual']) else r['actual']} | {r['met']} | {r['notes']} |")   # NaN on pandas 3
    return "\n".join(lines) + "\n"
