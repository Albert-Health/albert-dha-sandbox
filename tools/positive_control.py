"""Positive control: bilinen bir etnisite etkisini sentetik C3'e enjekte edip NB2 alt-grup O:E
analizinin onu yakaladığını gösterir.

Neden: sentetik veride outcome etnisiteden bağımsız üretildi; asıl hipotez (Emirati / Gulf Arab
grubunda QDiabetes'in riski düşük tahmin etmesi) bu veride test edilemez. Burada hedef grupta
kümülatif insidans ≈ PC_FACTOR katına çıkarılır (olaysız hastalara takip içinde diyabetik HbA1c eklenir).

Kullanım:  python tools/positive_control.py
Girdi:     data/canonical/synthetic/c3 (değiştirilmez)
Çıktı:     data/canonical/synthetic_pc/c3 + outputs/<run_id>/positive_control/*
           NB2'yi bu veriyle görmek için: SANDBOX_SOURCE=synthetic_pc python notebooks/02_c3_benchmark.py
Başarı:    r = O:E(hedef) / O:E(diğer). r(enjekte) / r(orijinal) ≥ 1.5 → PASS; aksi halde çıkış kodu 1.
Not:       r(orijinal) 1'den büyük çıkabilir: sentetik outcome etnisiteden bağımsızken QDiabetes "Other"
           kategorisine (Emirati / Gulf Arab) Güney Asya'ya göre düşük risk verir — eşlemenin yapısal etkisi.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sandbox import cohorts, metrics, recalibration  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, PARAMS  # noqa: E402
from sandbox.io import schema  # noqa: E402
from sandbox.io.schema import Dataset  # noqa: E402
from sandbox.scores import qdiabetes2018a as qd  # noqa: E402

TARGET = ["Emirati", "Gulf Arab (non-Emirati)"]
PC_FACTOR = 2.0


def inject(ds: Dataset, c3: pd.DataFrame, seed: int) -> tuple[Dataset, int]:
    rng = np.random.default_rng(seed)
    tgt = c3[c3["ethnicity"].isin(TARGET)]
    f = tgt["incident_diabetes"].mean()
    q = min(0.9, (PC_FACTOR - 1) * f / max(1 - f, 1e-9))
    cand = tgt[~tgt["incident_diabetes"] & tgt["last_glycaemic_date"].notna()]
    chosen = cand[rng.random(len(cand)) < q]
    span = (chosen["last_glycaemic_date"] - chosen["index_date"]).dt.days.clip(lower=1)
    offset = np.maximum(1, np.floor(rng.random(len(chosen)) * span.to_numpy())).astype(int)
    new = pd.DataFrame({"patient_id": chosen.index, "loinc": "4548-4", "test_name": "HbA1c (positive control)",
                        "value": 7.2, "unit": "%",
                        "date": chosen["index_date"].to_numpy() + pd.to_timedelta(offset, unit="D")})
    tables = dict(ds.tables)
    tables["labs"] = pd.concat([ds["labs"], schema.coerce(new, "labs")], ignore_index=True)
    return Dataset(source="synthetic_pc", cohort="c3", tables=tables), len(new)


def group_oe(ds: Dataset, p: dict) -> pd.DataFrame:
    c3 = cohorts.build_c3(ds, p)["cohort"]
    x = c3.join(qd.score(c3, years=10, p=p)[["qd_lp", "qd_computable"]])
    x = x[x["qd_computable"]]
    h = p["horizon_years"]
    m = recalibration.fit_stratified(x["followup_years"], x["incident_diabetes"], x["qd_lp"], x["sex"], h, "baseline")
    x["p"] = recalibration.predict_stratified(m, x["qd_lp"], x["sex"])
    x["grp"] = np.where(x["ethnicity"].isin(TARGET), "target (Emirati+Gulf Arab)", "others")
    rows = []
    for g, d in x.groupby("grp"):
        oe = metrics.observed_expected(d["followup_years"], d["incident_diabetes"], d["p"], h)
        rows.append({"group": g, "n": len(d), "events": int(d["incident_diabetes"].sum()), **oe})
    return pd.DataFrame(rows)


def main() -> int:
    p = dict(PARAMS)
    p.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))
    run = Run("positive_control", params=p, source="synthetic_pc")
    run.add_inputs([CANONICAL_DIR / "synthetic" / "c3"])
    base = schema.read_dataset(CANONICAL_DIR, "synthetic", "c3")
    c3 = cohorts.build_c3(base, p)["cohort"]
    pc, n_inj = inject(base, c3, p["seed"] + 99)
    d = schema.write_dataset(pc, CANONICAL_DIR)
    for f in sorted(d.glob("*.csv")):
        run.register_output(f, f"positive control canonical {f.stem}")
    run.log("injected events", n=n_inj, target=TARGET, factor=PC_FACTOR)

    res = pd.concat([group_oe(base, p).assign(data="original"), group_oe(pc, p).assign(data="positive_control")])
    run.save_table(res, "positive_control/group_oe.csv", "Hedef vs diğer O:E (Kol 2a)")
    ratio = {k: float(v.set_index("group").loc["target (Emirati+Gulf Arab)", "oe_ratio"] /
                      v.set_index("group").loc["others", "oe_ratio"]) for k, v in res.groupby("data")}
    lift = ratio["positive_control"] / ratio["original"]
    passed = lift >= 1.5
    summary = {"injected_events": n_inj, "oe_ratio_target_vs_others": ratio, "detection_lift": lift,
               "pass": passed, "criterion": "r(enjekte) / r(orijinal) ≥ 1.5"}
    run.save_json(summary, "positive_control/summary.json", "Positive control sonucu")
    run.finish("success" if passed else "positive_control_failed")
    print(res.to_string(index=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
