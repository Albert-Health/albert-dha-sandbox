"""DFF Health Data Sandbox KPI tablosu (KPI & Graduation Framework v4 / Albert V2.0).

NB0 / NB1 / NB2'nin `kpi_values.json` çıktıları, audit log ve son evidence package kontrol
listesinden Actual / Met değerlerini doldurur. Graduation kuralı: herhangi bir Critical KPI
Not Met → Do Not Graduate; aksi halde non-critical Met oranı ≥%80 Graduate, %50–79 Graduate with Mitigation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

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
    """Adı prefix içeren, başarıyla bitmiş en son run klasörü (manifest started_utc'ye göre).
    source verilirse yalnızca o veri kaynağıyla (synthetic / nabidh / synthetic_pc) çalışmış run'lar."""
    best, best_ts = None, ""
    for m in base.glob(f"*{prefix}*/run_manifest.json"):
        rec = json.loads(m.read_text(encoding="utf-8"))
        rec_source = rec.get("source") or "synthetic"     # source alanı öncesi run'lar sentetikti
        if source is not None and rec_source != source:
            continue
        if rec.get("status") == "success" and rec.get("started_utc", "") > best_ts:
            best, best_ts = m.parent, rec["started_utc"]
    return best


def _load(run_dir: Path | None, rel: str) -> dict:
    if run_dir is None or not (run_dir / rel).exists():
        return {}
    return json.loads((run_dir / rel).read_text(encoding="utf-8"))


def audit_completeness(log: Path = AUDIT_DIR / "audit_log.jsonl") -> dict:
    starts, ends = set(), set()
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("event") == "run_start":
                starts.add(ev["run_id"])
            elif ev.get("event") == "run_end":
                ends.add(ev["run_id"])
    pct = 100.0 * len(starts & ends) / len(starts) if starts else float("nan")
    return {"runs": len(starts), "closed": len(starts & ends), "pct": pct, "open": sorted(starts - ends)}


def _fmt(x, nd=3):
    if x is None or (isinstance(x, float) and x != x):
        return None
    return round(x, nd) if isinstance(x, float) else x


def build(nb0: dict, nb1: dict, nb2: dict, evidence: dict, audit: dict, p: dict = PARAMS) -> pd.DataFrame:
    rows = {k: {"kpi": k, "category": c, "owner": o, "target": t, "critical": cr,
                "actual": None, "met": "Pending", "source": "", "notes": ""} for k, c, o, t, cr in KPI_ROWS}

    def set_(k, actual, met, source, notes=""):
        rows[k].update(actual=actual, met=met, source=source, notes=notes)

    if audit.get("runs"):
        set_("Audit Trail Completeness", f"{audit['pct']:.1f}% ({audit['closed']}/{audit['runs']} runs)",
             "Met" if audit["pct"] >= 100 else "Not Met", "outputs/audit/audit_log.jsonl",
             "Açık run'lar: " + ", ".join(audit["open"][:5]) if audit["open"] else "")
    if evidence:
        set_("Evidence Package Completeness", f"{evidence['complete_sections']}/{evidence['total_sections']} bölüm",
             "Met" if evidence["complete"] else "Not Met", evidence.get("path", ""),
             "Şablonlar doldurulup imzalanana kadar 'Not Met'" if not evidence["complete"] else "")
    set_("Data Security / No-Incident", f"{p['security_incidents']} incidents", "Met" if p["security_incidents"] == 0 else "Not Met",
         "config.security_incidents (manuel)", "Enclave olay kaydından manuel teyit")

    if nb0:
        set_("Applicant Data Requirement Framework Match", "Match" if nb0["framework_match"] else
             "Eksik: " + ", ".join(nb0["framework_missing_groups"][:6]),
             "Met" if nb0["framework_match"] else "Not Met", "NB0 nb00/kpi_values.json")
        dc = nb0["data_completeness_min_core8_pct"]
        set_("Data Completeness for Required Variables", "; ".join(f"{c.upper()} {v:.1f}%" for c, v in dc.items()),
             "Met" if all(v >= 90 for v in dc.values()) else "Not Met", "NB0",
             "Min değişken: " + ", ".join(f"{c}={v}" for c, v in nb0.get("data_completeness_weakest", {}).items()))

    if nb2:
        set_("Joint Completeness - QDiabetes",
             f"{nb2['joint_completeness_qdiabetes_pct']}% (N={nb2['joint_completeness_qdiabetes_n']}/{nb2['c3_eligible_n']})",
             "Reported", "NB2 (C3 tabanı)", f"Tanım: 8 çekirdek değişken ({nb2.get('qd_variant')}) [DFF ile teyit bekliyor]")
        set_("Joint Completeness - LRS",
             f"{nb2['joint_completeness_lrs_pct']}% (N={nb2['joint_completeness_lrs_n']}/{nb2['c3_eligible_n']})",
             "Reported", "NB2 (C3 tabanı)")
        auc, ci = nb2.get("auroc_qd"), nb2.get("auroc_qd_ci")
        if auc is not None:
            set_("AUROC", f"{auc:.3f}" + (f" (95% CI {ci[0]:.3f}–{ci[1]:.3f})" if ci else ""), "Met" if auc >= 0.75 else "Not Met",
                 "NB2 Kol 1, test", f"Zaman-bağımlı AUROC @ {nb2['horizon_years']}y (IPCW). LRS: {_fmt(nb2.get('auroc_lrs'))}")
        c, cci = nb2.get("c_index_qd"), nb2.get("c_index_qd_ci")
        if c is not None:
            set_("C-Index", f"{c:.3f}" + (f" (95% CI {cci[0]:.3f}–{cci[1]:.3f})" if cci else ""),
                 "Met" if 0.55 <= c <= 0.90 else "Not Met", "NB2 Kol 1, test", f"LRS: {_fmt(nb2.get('c_index_lrs'))}")
        set_("Recalibration Slope / O:E",
             f"Kol 1 O:E {_fmt(nb2.get('oe_qd_kol1'))}, slope {_fmt(nb2.get('cal_slope_qd_kol1'))}; "
             f"Kol 2a O:E {_fmt(nb2.get('oe_qd_kol2a'))}, slope {_fmt(nb2.get('cal_slope_qd_kol2a'))}",
             "Reported", "NB2")
        thr = nb2.get("qd_threshold", {})
        lthr = nb2.get("lrs_threshold", {})
        lrs_note = (f"LRS ≥{_fmt(lthr.get('threshold'))}: sens {_fmt(lthr.get('sensitivity'))}, "
                    f"spec {_fmt(lthr.get('specificity'))}, PPV {_fmt(lthr.get('ppv'))}, NPV {_fmt(lthr.get('npv'))}, "
                    f"alert/1000 {_fmt(lthr.get('alert_rate_per_1000'), 1)}") if lthr.get("threshold") is not None else ""
        if "sensitivity" in thr:
            set_("Sensitivity (Recall, positive class)", f"{thr['sensitivity']:.3f}", "Met" if thr["sensitivity"] >= 0.70 else "Not Met", "NB2", lrs_note)
            set_("Specificity", f"{thr['specificity']:.3f}", "Met" if thr["specificity"] >= 0.70 else "Not Met", "NB2", lrs_note)
            set_("NPV & PPV", f"PPV {thr['ppv']:.3f}, NPV {thr['npv']:.3f}", "Reported", "NB2", lrs_note)
            set_("Precision / Recall / F1", f"P {thr['precision']:.3f}, R {thr['recall']:.3f}, F1 {thr['f1']:.3f}", "Reported", "NB2")
            set_("Alert Rate per 1,000 Patients", f"{thr['alert_rate_per_1000']:.1f}", "Reported", "NB2")
        else:
            for k in ["Sensitivity (Recall, positive class)", "Specificity", "NPV & PPV", "Precision / Recall / F1",
                      "Alert Rate per 1,000 Patients"]:
                set_(k, None, "Pending", "NB2", "QDiabetes eşiği önceden belirlenmedi (qd_risk_threshold_pct) [karar bekliyor]. " + lrs_note)
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
    lines = ["# KPI raporu — Albert Health × DHA Health Data Sandbox", "",
             f"- Oluşturma: {meta.get('generated_utc')}  ·  Kaynak: {meta.get('source')}",
             f"- Girdi run'ları: {', '.join(f'{k}={v}' for k, v in meta.get('runs', {}).items())}",
             f"- **Graduation ön değerlendirmesi:** {grad['outcome']} (Critical {grad['critical_met']}/{grad['critical_total']}; "
             f"non-critical Met {grad['non_critical_met']}/{grad['non_critical_evaluable']} değerlendirilebilir)", "",
             "| KPI | Hedef | Critical | Sahibi | Actual | Durum | Not |", "|---|---|---|---|---|---|---|"]
    for _, r in table.iterrows():
        lines.append(f"| {r['kpi']} | {r['target']} | {'Evet' if r['critical'] else 'Hayır'} | {r['owner']} | "
                     f"{r['actual'] if r['actual'] is not None else '—'} | {r['met']} | {r['notes']} |")
    return "\n".join(lines) + "\n"
