"""NABIDH data (raw file or IRIS) → canonical schema (the first step in the enclave; Phase 1 and Phase 2 read it).

Usage — raw file:
  python tools/ingest_nabidh.py                          # data/nabidh/raw/<c1|c2|c3> → data/canonical/nabidh/<…>
  python tools/ingest_nabidh.py --cohorts c1 c2          # Phase 1
  python tools/ingest_nabidh.py --raw-root data/nabidh_dryrun/raw --source nabidh_dryrun   # dry run

Usage — InterSystems IRIS (DHA; connection settings at the top of src/sandbox/io/iris.py):
  python tools/ingest_nabidh.py --input iris --cohorts c1 c2
      → data/nabidh_iris/raw/<cohort>/*.csv (snapshot) + data/canonical/nabidh/<cohort>/
  python tools/ingest_nabidh.py --raw-root data/nabidh_iris/raw        # from the snapshot, without going to IRIS
  python tools/ingest_nabidh.py --input iris --iris-sqlite data/nabidh_dryrun/iris --source nabidh_dryrun_iris
      # dry run: SQLite instead of IRIS (built by tools/make_nabidh_dryrun.py)

Then:  SANDBOX_SOURCE=nabidh python notebooks/00_data_profile.py  (same for NB1, NB2)

Output:
  data/<source>_iris/raw/<cohort>/*.csv                  (IRIS) query results in raw-file form (recorded in the audit)
  data/canonical/<source>/<cohort>/*.csv                 canonical tables (recorded in the audit)
  outputs/<run_id>/ingest/<cohort>_summary.json          rows read / produced per source,
                                                         unparseable dates, absent optional columns
  outputs/<run_id>/ingest/<cohort>_validation.csv        schema checks (schema.validate)
  outputs/<run_id>/ingest/<cohort>_value_counts.csv      sex, nationality, smoking, family history, code|unit,
                                                         non-ATC drug codes … (< 10 suppressed)
"unmapped" values → extend the dictionaries in src/sandbox/io/adapters/nabidh.py and run again.
With a schema ERROR the canonical data is still written (for inspection) but the exit code is 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from sandbox import sdc  # noqa: E402
from sandbox.audit import Run  # noqa: E402
from sandbox.config import CANONICAL_DIR, COHORTS, DATA_DIR, PARAMS, RAW_DIR  # noqa: E402
from sandbox.io import iris, schema  # noqa: E402
from sandbox.io.adapters import ddc, nabidh  # noqa: E402


_START = time.monotonic()


def say(msg: str) -> None:
    """Progress line on screen (stays inside the enclave; not in the COPY block): clock time + seconds since start."""
    print(f"[{time.strftime('%H:%M:%S')} +{time.monotonic() - _START:.0f}s] {msg}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NABIDH data (raw file or IRIS) → canonical schema")
    ap.add_argument("--input", choices=["files", "iris"], default="files",
                    help="files: the files under --raw-root; iris: DHA InterSystems IRIS (io/iris.py)")
    ap.add_argument("--raw-root", type=Path, default=RAW_DIR["nabidh"],
                    help="(files) directory holding the cohort folders (c1, c2, c3)")
    ap.add_argument("--source", default="nabidh", help="canonical output name: data/canonical/<source>/")
    ap.add_argument("--cohorts", nargs="+", choices=COHORTS, default=None,
                    help="default: files → those found under raw-root; iris → those in IRIS_COHORTS")
    ap.add_argument("--iris-url", default=None,
                    help=f"(iris) jdbc:IRIS://host:port/NAMESPACE; default {iris.ENV_URL} / ~/.nabidh_iris")
    ap.add_argument("--iris-sqlite", type=Path, default=None,
                    help="(iris, dry run) <dir>/<cohort>.sqlite files instead of IRIS")
    ap.add_argument("--snapshot-root", type=Path, default=None,
                    help="(iris) directory for the query results; default data/<source>_iris/raw (nabidh → nabidh_iris)")
    ap.add_argument("--no-snapshot", action="store_true", help="(iris) do not write a snapshot")
    a = ap.parse_args(argv)
    raw_root = a.raw_root.resolve()
    use_iris = a.input == "iris"

    p = dict(PARAMS)
    p.update(json.loads(os.environ.get("SANDBOX_PARAMS", "{}")))
    run = Run("ingest_nabidh", params=p, source=a.source)
    print(f"Ingest v{nabidh.INGEST_VERSION} · run {run.run_id}")
    run.log("ingest version", ingest_version=nabidh.INGEST_VERSION)
    if use_iris:
        cohorts = a.cohorts or [c for c in COHORTS if c in nabidh.IRIS_COHORTS]
        if a.iris_sqlite:
            cohorts = [c for c in cohorts if (a.iris_sqlite / f"{c}.sqlite").is_file()]
    else:
        cohorts = a.cohorts or [c for c in COHORTS if (raw_root / c).is_dir()]
    if not cohorts:
        where = (a.iris_sqlite or "IRIS_COHORTS") if use_iris else f"{raw_root}/<c1|c2|c3>"
        print(f"No cohort found: {where}")
        run.log("ingest start", input=a.input, cohorts=[])
        run.finish("no_input")
        return 2

    conn, target, snap_root = None, None, None
    if use_iris:
        default_snap = DATA_DIR / f"{a.source.removesuffix('_iris')}_iris" / "raw"      # nabidh → nabidh_iris
        snap_root = None if a.no_snapshot else (a.snapshot_root or default_snap).resolve()
        if snap_root is not None and snap_root in (raw_root, RAW_DIR["nabidh"].resolve()):
            print(f"--snapshot-root cannot be the raw delivery folder: {snap_root}")
            run.finish("bad_arguments")
            return 2
        if a.iris_sqlite:
            sq = a.iris_sqlite.resolve()
            conn = iris.sqlite_standin({nabidh.IRIS_COHORTS[c]["schema"]: sq / f"{c}.sqlite" for c in cohorts})
            target, user, driver = f"sqlite stand-in: {sq}", None, "sqlite3"
        else:
            user = driver = None
            try:
                s = iris.connection_settings(a.iris_url)
                target, user, driver = s["target"], s["user"], s["driver"]
                say(f"connecting to IRIS {target} as {user} ...")
                conn = iris.connect(a.iris_url)
                say("connected")
            except Exception as e:                  # settings / driver / network / login — no password in the message
                err = f"{type(e).__name__}: {str(e)[:300]}"
                print(f"Could not connect to IRIS ({target or 'no connection settings'}): {err}\n"
                      f"Detailed diagnosis: python tools/check_environment.py --iris")
                run.log("iris connect failed", target=target, user=user, driver=driver, error=err)
                run.finish("connection_failed")
                return 2
        run.log("ingest start", input="iris", target=target, user=user, driver=driver, cohorts=cohorts,
                snapshot_root=str(snap_root) if snap_root else None)
    else:
        run.log("ingest start", input="files", raw_root=str(raw_root), cohorts=cohorts)

    run.add_inputs([ddc.REFERENCE_PATH])           # drug code / name → ATC reference (DDC list)
    try:
        n_errors = _ingest(run, a, cohorts, raw_root, conn, target, snap_root)
    finally:
        if conn is not None:
            conn.close()

    status = "success" if n_errors == 0 else "schema_errors"
    run.finish(status)
    print(f"\nRun: {run.run_id}  status: {status}")
    return 0 if n_errors == 0 else 1


def _ingest(run: Run, a, cohorts, raw_root: Path, conn, target, snap_root) -> int:
    n_errors = 0
    for c in cohorts:
        progress = lambda msg, c=c: say(f"{c} {msg}")      # noqa: E731
        if conn is None:
            d = raw_root / c
            run.add_inputs([d])
            say(f"{c}: reading {d}")
            ds, rep = nabidh.load(d, c, progress=progress)
        else:
            say(f"{c}: reading {len(nabidh.SOURCES)} sources from IRIS")
            ds, rep = nabidh.load_iris(conn, c, snapshot_dir=snap_root / c if snap_root else None, progress=progress)
            for name, s in rep["sources"].items():
                if "query" in s:
                    run.add_query_input(target, s["query"], s["rows_read"], s["sha256"], f"{c} {name}")
                if "snapshot" in s:
                    run.register_output(Path(s["snapshot"]), f"IRIS snapshot {c} {name}")
        ds.source = a.source
        say(f"{c}: writing canonical tables and checking the schema")
        out_dir = schema.write_dataset(ds, CANONICAL_DIR)
        meta = {"ingest_version": nabidh.INGEST_VERSION, "ingest_run_id": run.run_id, "source": a.source,
                "cohort": c, "input": "file" if conn is None else "iris"}
        (out_dir / "ingest.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        run.register_output(out_dir / "ingest.json", f"canonical {a.source} {c} ingest version")
        for f in sorted(out_dir.glob("*.csv")):
            run.register_output(f, f"canonical {a.source} {c} {f.stem}")

        back = schema.read_dataset(CANONICAL_DIR, a.source, c)       # validate what NB0 will see
        val = schema.validate(back)
        errors = int((val["severity"] == "ERROR").sum())
        n_errors += errors
        run.save_table(val, f"ingest/{c}_validation.csv", f"{c} schema checks")

        vc = pd.DataFrame(rep.pop("value_counts"), columns=["source", "field", "value", "n_rows"])
        run.save_table(sdc.suppress_small_counts(vc, ["n_rows"]), f"ingest/{c}_value_counts.csv",
                       f"{c} source value distributions (for the mapping dictionaries)")
        unmapped = vc[vc["value"].str.contains("unmapped", na=False)]
        summary = {**rep, "ingest_version": nabidh.INGEST_VERSION, "source": a.source, "n_patients": back.n_patients,
                   "rows": {t: int(len(df)) for t, df in back.tables.items()},
                   "schema_errors": errors, "schema_warnings": int((val["severity"] == "WARN").sum()),
                   "unmapped_value_rows": int(unmapped["n_rows"].sum())}
        run.save_json(summary, f"ingest/{c}_summary.json", f"{c} ingest summary")
        run.log(f"{c} ingested", n_patients=back.n_patients, rows=summary["rows"], schema_errors=errors,
                unmapped_value_rows=summary["unmapped_value_rows"])

        print(f"\n== {c.upper()}: {back.n_patients} patients → {out_dir}")
        print("   rows: " + ", ".join(f"{t}={n}" for t, n in summary["rows"].items()))
        for name, s in rep["sources"].items():
            bad = {k: v for k, v in s.items() if k.startswith("unparseable_") and v}
            extra = f"  unparseable dates: {bad}" if bad else ""
            for k, v in s.items():
                if k.startswith("dropped_empty_") and not k.endswith("_by_code") and v:
                    extra += f"  {k}={v}" + (f" ({s[k + '_by_code']})" if s.get(k + "_by_code") else "")
            if s.get("error"):
                extra += f"  ({s['error'][:120]})"
            print(f"   {name:16s} {s.get('status')}  rows_read={s.get('rows_read', '—')}{extra}")
        issues = val[val["severity"] != "INFO"]
        if len(issues):
            print(issues.to_string(index=False))
        if len(unmapped):
            print("   unmapped values (to add to the adapter dictionaries):")
            print(unmapped.head(20).to_string(index=False))
    return n_errors


if __name__ == "__main__":
    sys.exit(main())
