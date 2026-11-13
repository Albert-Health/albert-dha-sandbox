"""NABIDH ham verisi → kanonik şema (enclave'deki ilk adım; Faz 1 ve Faz 2 bunu okur).

Kullanım:
  python tools/ingest_nabidh.py                          # data/nabidh/raw/<c1|c2|c3> → data/canonical/nabidh/<…>
  python tools/ingest_nabidh.py --cohorts c1 c2          # Faz 1
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun   # prova

Ardından:  SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py  (NB1, NB2 aynı)

Çıktı:
  data/canonical/<source>/<kohort>/*.csv                 kanonik tablolar (audit'e kayıtlı)
  outputs/<run_id>/ingest/<kohort>_summary.json          kaynak bazında okunan / üretilen satırlar,
                                                         çözülemeyen tarihler, eksik opsiyonel sütunlar
  outputs/<run_id>/ingest/<kohort>_validation.csv        şema kontrolleri (schema.validate)
  outputs/<run_id>/ingest/<kohort>_value_counts.csv      cinsiyet, uyruk, sigara, aile öyküsü, kod|birim,
                                                         ATC dışı ilaç kodları … (< 10 bastırılmış)
"unmapped" değerler → src/sandbox/io/adapters/nabidh.py sözlüklerini genişlet, tekrar çalıştır.
Şema ERROR varsa kanonik veri yine yazılır (inceleme için) ama çıkış kodu 1 olur.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sandbox import sdc  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, COHORTS, PARAMS, RAW_DIR  # noqa: E402
from sandbox.io import schema  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NABIDH ham verisi → kanonik şema")
    ap.add_argument("--raw-root", type=Path, default=RAW_DIR["nabidh"],
                    help="kohort klasörlerini (c1, c2, c3) içeren dizin")
    ap.add_argument("--source", default="nabidh", help="kanonik çıktı adı: data/canonical/<source>/")
    ap.add_argument("--cohorts", nargs="+", choices=COHORTS, default=None,
                    help="varsayılan: raw-root altında bulunan tüm kohortlar")
    a = ap.parse_args(argv)
    raw_root = a.raw_root.resolve()

    p = dict(PARAMS)
    p.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))
    run = Run("ingest_nabidh", params=p, source=a.source)
    cohorts = a.cohorts or [c for c in COHORTS if (raw_root / c).is_dir()]
    run.log("ingest start", raw_root=str(raw_root), cohorts=cohorts)
    if not cohorts:
        print(f"Kohort klasörü bulunamadı: {raw_root}/<c1|c2|c3>")
        run.finish("no_input")
        return 2

    n_errors = 0
    for c in cohorts:
        d = raw_root / c
        run.add_inputs([d])
        ds, rep = nabidh.load(d, c)
        ds.source = a.source
        out_dir = schema.write_dataset(ds, CANONICAL_DIR)
        for f in sorted(out_dir.glob("*.csv")):
            run.register_output(f, f"canonical {a.source} {c} {f.stem}")

        back = schema.read_dataset(CANONICAL_DIR, a.source, c)       # NB0'ın göreceği hâli doğrula
        val = schema.validate(back)
        errors = int((val["severity"] == "ERROR").sum())
        n_errors += errors
        run.save_table(val, f"ingest/{c}_validation.csv", f"{c} şema kontrolleri")

        vc = pd.DataFrame(rep.pop("value_counts"), columns=["source", "field", "value", "n_rows"])
        run.save_table(sdc.suppress_small_counts(vc, ["n_rows"]), f"ingest/{c}_value_counts.csv",
                       f"{c} kaynak değer dağılımları (eşleme sözlükleri için)")
        unmapped = vc[vc["value"].str.contains("unmapped", na=False)]
        summary = {**rep, "source": a.source, "n_patients": back.n_patients,
                   "rows": {t: int(len(df)) for t, df in back.tables.items()},
                   "schema_errors": errors, "schema_warnings": int((val["severity"] == "WARN").sum()),
                   "unmapped_value_rows": int(unmapped["n_rows"].sum())}
        run.save_json(summary, f"ingest/{c}_summary.json", f"{c} ingest özeti")
        run.log(f"{c} ingested", n_patients=back.n_patients, rows=summary["rows"], schema_errors=errors,
                unmapped_value_rows=summary["unmapped_value_rows"])

        print(f"\n== {c.upper()}: {back.n_patients} hasta → {out_dir}")
        print("   satır: " + ", ".join(f"{t}={n}" for t, n in summary["rows"].items()))
        for name, s in rep["sources"].items():
            bad = {k: v for k, v in s.items() if k.startswith("unparseable_") and v}
            extra = f"  çözülemeyen tarih: {bad}" if bad else ""
            print(f"   {name:16s} {s.get('status')}  okunan={s.get('rows_read', '—')}{extra}")
        issues = val[val["severity"] != "INFO"]
        if len(issues):
            print(issues.to_string(index=False))
        if len(unmapped):
            print("   eşlenemeyen değerler (adapter sözlüklerine eklenecek):")
            print(unmapped.head(20).to_string(index=False))

    status = "success" if n_errors == 0 else "schema_errors"
    run.finish(status)
    print(f"\nRun: {run.run_id}  durum: {status}")
    return 0 if n_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
