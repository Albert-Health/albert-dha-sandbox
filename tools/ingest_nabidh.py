"""NABIDH verisi (ham dosya ya da IRIS) → kanonik şema (enclave'deki ilk adım; Faz 1 ve Faz 2 bunu okur).

Kullanım — ham dosya:
  python tools/ingest_nabidh.py                          # data/nabidh/raw/<c1|c2|c3> → data/canonical/nabidh/<…>
  python tools/ingest_nabidh.py --cohorts c1 c2          # Faz 1
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun   # prova

Kullanım — InterSystems IRIS (DHA; bağlantı ayarları src/sandbox/io/iris.py başında):
  python tools/ingest_nabidh.py --input iris --cohorts c1 c2
      → data/nabidh_iris/raw/<kohort>/*.csv (snapshot) + data/canonical/nabidh/<kohort>/
  python tools/ingest_nabidh.py --raw-root data/nabidh_iris/raw        # snapshot'tan, IRIS'e gitmeden
  python tools/ingest_nabidh.py --input iris --iris-sqlite data/nabidh_dryrun/iris --source nabidh_dryrun_iris
      # prova: IRIS yerine SQLite (tools/make_nabidh_dryrun.py üretir)

Ardından:  SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py  (NB1, NB2 aynı)

Çıktı:
  data/<source>_iris/raw/<kohort>/*.csv                  (IRIS) sorgu sonuçları, ham dosya biçiminde (audit'e kayıtlı)
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
from sandbox.config import CANONICAL_DIR, COHORTS, DATA_DIR, PARAMS, RAW_DIR  # noqa: E402
from sandbox.io import iris, schema  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NABIDH verisi (ham dosya ya da IRIS) → kanonik şema")
    ap.add_argument("--input", choices=["files", "iris"], default="files",
                    help="files: --raw-root altındaki dosyalar; iris: DHA InterSystems IRIS (io/iris.py)")
    ap.add_argument("--raw-root", type=Path, default=RAW_DIR["nabidh"],
                    help="(files) kohort klasörlerini (c1, c2, c3) içeren dizin")
    ap.add_argument("--source", default="nabidh", help="kanonik çıktı adı: data/canonical/<source>/")
    ap.add_argument("--cohorts", nargs="+", choices=COHORTS, default=None,
                    help="varsayılan: files → raw-root altında bulunanlar; iris → IRIS_COHORTS'takiler")
    ap.add_argument("--iris-url", default=None,
                    help=f"(iris) jdbc:IRIS://host:port/NAMESPACE; varsayılan {iris.ENV_URL} / ~/.nabidh_iris")
    ap.add_argument("--iris-sqlite", type=Path, default=None,
                    help="(iris, prova) IRIS yerine <dizin>/<kohort>.sqlite dosyaları")
    ap.add_argument("--snapshot-root", type=Path, default=None,
                    help="(iris) sorgu sonuçlarının yazılacağı dizin; varsayılan data/<source>_iris/raw (nabidh → nabidh_iris)")
    ap.add_argument("--no-snapshot", action="store_true", help="(iris) snapshot yazma")
    a = ap.parse_args(argv)
    raw_root = a.raw_root.resolve()
    use_iris = a.input == "iris"

    p = dict(PARAMS)
    p.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))
    run = Run("ingest_nabidh", params=p, source=a.source)
    if use_iris:
        cohorts = a.cohorts or [c for c in COHORTS if c in nabidh.IRIS_COHORTS]
        if a.iris_sqlite:
            cohorts = [c for c in cohorts if (a.iris_sqlite / f"{c}.sqlite").is_file()]
    else:
        cohorts = a.cohorts or [c for c in COHORTS if (raw_root / c).is_dir()]
    if not cohorts:
        where = (a.iris_sqlite or "IRIS_COHORTS") if use_iris else f"{raw_root}/<c1|c2|c3>"
        print(f"Kohort bulunamadı: {where}")
        run.log("ingest start", input=a.input, cohorts=[])
        run.finish("no_input")
        return 2

    conn, target, snap_root = None, None, None
    if use_iris:
        default_snap = DATA_DIR / f"{a.source.removesuffix('_iris')}_iris" / "raw"      # nabidh → nabidh_iris
        snap_root = None if a.no_snapshot else (a.snapshot_root or default_snap).resolve()
        if snap_root is not None and snap_root in (raw_root, RAW_DIR["nabidh"].resolve()):
            print(f"--snapshot-root ham teslim klasörüyle aynı olamaz: {snap_root}")
            run.finish("bad_arguments")
            return 2
        if a.iris_sqlite:
            sq = a.iris_sqlite.resolve()
            conn = iris.sqlite_standin({nabidh.IRIS_COHORTS[c]["schema"]: sq / f"{c}.sqlite" for c in cohorts})
            target, user, driver = f"sqlite stand-in: {sq}", None, "sqlite3"
        else:
            s = iris.connection_settings(a.iris_url)
            target, user, driver = s["target"], s["user"], s["driver"]
            conn = iris.connect(a.iris_url)
        run.log("ingest start", input="iris", target=target, user=user, driver=driver, cohorts=cohorts,
                snapshot_root=str(snap_root) if snap_root else None)
    else:
        run.log("ingest start", input="files", raw_root=str(raw_root), cohorts=cohorts)

    try:
        n_errors = _ingest(run, a, cohorts, raw_root, conn, target, snap_root)
    finally:
        if conn is not None:
            conn.close()

    status = "success" if n_errors == 0 else "schema_errors"
    run.finish(status)
    print(f"\nRun: {run.run_id}  durum: {status}")
    return 0 if n_errors == 0 else 1


def _ingest(run: Run, a, cohorts, raw_root: Path, conn, target, snap_root) -> int:
    n_errors = 0
    for c in cohorts:
        if conn is None:
            d = raw_root / c
            run.add_inputs([d])
            ds, rep = nabidh.load(d, c)
        else:
            ds, rep = nabidh.load_iris(conn, c, snapshot_dir=snap_root / c if snap_root else None)
            for name, s in rep["sources"].items():
                if "query" in s:
                    run.add_query_input(target, s["query"], s["rows_read"], s["sha256"], f"{c} {name}")
                if "snapshot" in s:
                    run.register_output(Path(s["snapshot"]), f"IRIS snapshot {c} {name}")
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
            if s.get("error"):
                extra += f"  ({s['error'][:120]})"
            print(f"   {name:16s} {s.get('status')}  okunan={s.get('rows_read', '—')}{extra}")
        issues = val[val["severity"] != "INFO"]
        if len(issues):
            print(issues.to_string(index=False))
        if len(unmapped):
            print("   eşlenemeyen değerler (adapter sözlüklerine eklenecek):")
            print(unmapped.head(20).to_string(index=False))
    return n_errors


if __name__ == "__main__":
    sys.exit(main())
