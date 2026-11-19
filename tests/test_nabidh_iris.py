"""NABIDH IRIS input (io/iris.py + nabidh.load_iris). SQLite stands in for IRIS: the cohort file is attached under
the IRIS schema name, so the adapter's `{schema}.Table` queries run as they are.
Main claim: the same raw data gives exactly the same canonical output whether read from files or from IRIS."""
import copy
import datetime as dt
import decimal
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from sandbox.audit import sha256_file  # noqa: E402
from sandbox.io import iris  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402
from sandbox.io.adapters.synthetic import read_raw_csv  # noqa: E402
from test_nabidh_adapter import write_raw  # noqa: E402

SCHEMA = nabidh.IRIS_COHORTS["c1"]["schema"]


def raw_tables(raw_dir: Path, rename=None, extra=None) -> dict[str, pd.DataFrame]:
    """Raw files → {IRIS table name: df}. rename: {table: {column: new name}}, extra: {table: {column: value}}."""
    out = {}
    for spec in nabidh.SOURCES.values():
        p = raw_dir / spec["file"]
        if p.exists():
            t = spec["table"].split(".", 1)[-1]
            df = read_raw_csv(p).rename(columns=(rename or {}).get(t, {}))
            for col, val in (extra or {}).get(t, {}).items():
                df[col] = val
            out[t] = df
    return out


def standin(tmp: Path, tables: dict) -> object:
    return iris.sqlite_standin({SCHEMA: iris.write_sqlite_standin(tmp / "c1.sqlite", tables)})


class TestFilesVsIris(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        t = Path(cls.tmp.name)
        (t / "raw").mkdir()
        write_raw(t / "raw")
        cls.ds_file, cls.rep_file = nabidh.load(t / "raw", "c1")
        # On the IRIS side, upper-case column names and an extra identifier column: the mapping must still hold,
        # and the identifier column must not be pulled
        tables = raw_tables(t / "raw", rename={"Patient": {"ID": "id", "Gender_Code": "GENDER_CODE"}},
                            extra={"Patient": {"full_name": "SHOULD NOT LEAVE IRIS"}})
        cls.conn = standin(t, tables)
        cls.snap = t / "snap"
        cls.ds_iris, cls.rep_iris = nabidh.load_iris(cls.conn, "c1", snapshot_dir=cls.snap)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.tmp.cleanup()

    def test_same_canonical_tables(self):
        for t, df in self.ds_file.tables.items():
            pd.testing.assert_frame_equal(df, self.ds_iris.tables[t], obj=t)

    def test_report(self):
        self.assertEqual(self.rep_iris["input"], "iris")
        self.assertEqual(self.rep_file["input"], "files")
        s = self.rep_iris["sources"]["patient_profile"]
        self.assertEqual(s["status"], "read")
        self.assertEqual(s["rows_read"], self.rep_file["sources"]["patient_profile"]["rows_read"])
        self.assertIn(f"FROM {SCHEMA}.Patient", s["query"])
        self.assertIn('"id" AS "ID"', s["query"])
        self.assertNotIn("full_name", s["query"])               # only the mapped columns
        self.assertEqual(len(s["sha256"]), 64)

    def test_optional_absent_table(self):
        s = self.rep_iris["sources"]["encounters"]
        self.assertEqual(s["status"], "absent (optional)")
        self.assertIn("no such table", s["error"])

    def test_snapshot_reingests_identically(self):
        ds_snap, _ = nabidh.load(self.snap, "c1")
        for t, df in self.ds_iris.tables.items():
            pd.testing.assert_frame_equal(df, ds_snap.tables[t], obj=t)
        s = self.rep_iris["sources"]["patient_profile"]
        self.assertEqual(sha256_file(Path(s["snapshot"])), s["sha256"])
        self.assertNotIn("full_name", (self.snap / "patients.csv").read_text(encoding="utf-8"))
        self.assertFalse((self.snap / "encounters.csv").exists())


class TestIrisSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / "raw").mkdir()
        write_raw(self.t / "raw")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_required_column(self):
        conn = standin(self.t, raw_tables(self.t / "raw", rename={"Diagnosis": {"Diagnosis_Code": "dx"}}))
        with self.assertRaisesRegex(KeyError, r"diagnoses .*required columns missing.*'Diagnosis_Code'"):
            nabidh.load_iris(conn, "c1")
        conn.close()

    def test_explicit_query_and_placeholders(self):
        tables = raw_tables(self.t / "raw", rename={"Patient": {"ID": "PID"}})
        conn = standin(self.t, tables)
        src = copy.deepcopy(nabidh.SOURCES)
        src["patient_profile"]["query"] = ("SELECT PID AS ID, Gender_Code, Age, Nationality "
                                           "FROM {schema}.Patient WHERE '{cohort}' = 'c1'")
        ds, rep = nabidh.load_iris(conn, "c1", sources=src)
        self.assertEqual(sorted(ds["patients"]["patient_id"]), ["A1", "A2", "A3", "A4"])
        self.assertIn("'c1' = 'c1'", rep["sources"]["patient_profile"]["query"])
        src["patient_profile"]["query"] = "SELECT * FROM {nope}.Patient"
        with self.assertRaisesRegex(KeyError, "placeholder"):
            nabidh.load_iris(conn, "c1", sources=src)
        conn.close()

    def test_non_select_query_refused(self):
        conn = standin(self.t, raw_tables(self.t / "raw"))
        src = copy.deepcopy(nabidh.SOURCES)
        src["patient_profile"]["query"] = "DELETE FROM {schema}.Patient"
        with self.assertRaisesRegex(ValueError, "SELECT"):
            nabidh.load_iris(conn, "c1", sources=src)
        n = conn.execute(f"SELECT COUNT(*) FROM {SCHEMA}.Patient").fetchone()[0]
        self.assertEqual(n, 4)
        conn.close()

    def test_horolog_dates(self):
        tables = raw_tables(self.t / "raw")
        dx = tables["Diagnosis"]
        dx["DiagnosisDate"] = ["66839", "65743,3600", "", "not-a-date"]   # 2023-12-31, 2020-12-30 01:00
        conn = standin(self.t, tables)
        src = copy.deepcopy(nabidh.SOURCES)
        src["diagnoses"]["date_format"] = "horolog"
        ds, rep = nabidh.load_iris(conn, "c1", sources=src)
        got = ds["conditions"].set_index("patient_id")["date"]
        self.assertEqual(got["A1"], pd.Timestamp("2023-12-31"))
        self.assertEqual(got["A2"], pd.Timestamp("2020-12-30 01:00"))
        self.assertTrue(pd.isna(got["A3"]))
        self.assertEqual(rep["sources"]["diagnoses"]["unparseable_date"], 1)
        conn.close()


class TestIrisHelpers(unittest.TestCase):
    def test_parse_url(self):
        t = iris.parse_url("jdbc:IRIS://dhasbx.example:51772/NABIDH")
        self.assertEqual((t.host, t.port, t.namespace), ("dhasbx.example", 51772, "NABIDH"))
        t = iris.parse_url("jdbc:IRIS://10.0.0.5:51772/NABIDH/logfile;user=x;password=secret?ssl=1")
        self.assertEqual(str(t), "10.0.0.5:51772/NABIDH")            # parameters (password) are dropped
        self.assertEqual(iris.parse_url("host/NS").port, iris.DEFAULT_PORT)
        with self.assertRaises(ValueError):
            iris.parse_url("jdbc:sqlserver://host:1433")

    def test_assert_select(self):
        for ok in ["SELECT 1", "  select a FROM b;", "-- not\nSELECT 1", "WITH x AS (SELECT 1) SELECT * FROM x"]:
            iris.assert_select(ok)
        for bad in ["DELETE FROM t", "SELECT 1; DROP TABLE t", "UPDATE t SET a=1", "/* SELECT */ DROP TABLE t"]:
            with self.assertRaises(ValueError, msg=bad):
                iris.assert_select(bad)

    def test_as_text_table(self):
        df = pd.DataFrame([(8517006, dt.date(2021, 1, 2), dt.datetime(2021, 1, 2, 10, 30),
                            decimal.Decimal("6.80"), 6.8, "x"),
                           (None, None, None, None, None, "")],
                          columns=list("abcdef"), dtype=object)
        out, text = iris.as_text_table(df)
        self.assertEqual(out.iloc[0].tolist(), ["8517006", "2021-01-02", "2021-01-02 10:30:00", "6.80", "6.8", "x"])
        self.assertTrue(out.iloc[1].isna().all())                    # NULL and empty text → missing
        self.assertEqual(len(iris.sha256_text(text)), 64)

    def test_parse_horolog(self):
        got = nabidh.parse_horolog(pd.Series(["0", "1", "67000,3600", "1.5", "x", None]))
        self.assertEqual(got[0], pd.Timestamp("1840-12-31"))
        self.assertEqual(got[1], pd.Timestamp("1841-01-01"))
        self.assertEqual(got[2], pd.Timestamp("1840-12-31") + pd.Timedelta(days=67000, hours=1))
        self.assertTrue(got[3:].isna().all())

    def test_settings_from_env_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            cred = Path(d) / "cred"
            cred.write_text("# yorum\nNABIDH_IRIS_URL=jdbc:IRIS://h:51772/NS\nNABIDH_IRIS_USER='reader'\n"
                            "NABIDH_IRIS_PASSWORD=pw\n", encoding="utf-8")
            env = {"NABIDH_IRIS_CREDENTIALS": str(cred)}
            with mock.patch.dict(os.environ, env):
                for k in (iris.ENV_URL, iris.ENV_USER, iris.ENV_PASSWORD, iris.ENV_ODBC):
                    os.environ.pop(k, None)
                s = iris.connection_settings()
                self.assertEqual((s["target"], s["user"]), ("h:51772/NS", "reader"))
                self.assertNotIn("pw", str({k: v for k, v in s.items() if k != "_url"}))
                os.environ[iris.ENV_USER] = "other"                     # environment variable beats the file
                self.assertEqual(iris.connection_settings()["user"], "other")
                with mock.patch.dict(sys.modules, {"iris": None}):      # driver not installed
                    with self.assertRaisesRegex(RuntimeError, "intersystems-irispython"):
                        iris.connect()
            with mock.patch.dict(os.environ, {"NABIDH_IRIS_CREDENTIALS": str(Path(d) / "none")}):
                for k in (iris.ENV_URL, iris.ENV_ODBC):
                    os.environ.pop(k, None)
                with self.assertRaisesRegex(RuntimeError, "No IRIS connection string"):
                    iris.connection_settings()

    def test_can_prompt(self):
        """Terminal, IntelliJ 'Emulate terminal' (tty), Jupyter (ipykernel) → can prompt; pipe / no stdin → no."""
        tty, pipe = mock.Mock(isatty=lambda: True), mock.Mock(isatty=lambda: False)
        no_kernel = {k: v for k, v in sys.modules.items() if k != "ipykernel"}
        with mock.patch.dict(sys.modules, no_kernel, clear=True):
            with mock.patch.object(sys, "stdin", tty):
                self.assertTrue(iris.can_prompt())
            with mock.patch.object(sys, "stdin", pipe):
                self.assertFalse(iris.can_prompt())
                with mock.patch.dict(sys.modules, {"ipykernel": mock.Mock()}):
                    self.assertTrue(iris.can_prompt())
            with mock.patch.object(sys, "stdin", None):
                self.assertFalse(iris.can_prompt())

    def test_password_prompt(self):
        env = {iris.ENV_URL: "jdbc:IRIS://h:51772/NS", iris.ENV_USER: "reader",
               iris.ENV_CREDENTIALS: str(ROOT / "tests" / "__no_such_credentials_file__")}
        with mock.patch.dict(os.environ, env):
            os.environ.pop(iris.ENV_PASSWORD, None)
            os.environ.pop(iris.ENV_ODBC, None)
            with mock.patch.object(iris, "can_prompt", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "cannot prompt.*Emulate terminal"):
                    iris.connect()
            fake = mock.Mock(return_value="conn")
            with mock.patch.object(iris, "can_prompt", return_value=True), \
                    mock.patch.object(iris, "_driver_connect", return_value=fake), \
                    mock.patch("getpass.getpass", return_value="typed") as gp:
                self.assertEqual(iris.connect(), "conn")
            gp.assert_called_once()
            self.assertEqual(fake.call_args.args, ("h", 51772, "NS", "reader", "typed"))
            # stdin closed in Jupyter (nbconvert / papermill): the kernel error becomes a readable RuntimeError
            with mock.patch.object(iris, "can_prompt", return_value=True), \
                    mock.patch("getpass.getpass", side_effect=NotImplementedError("stdin")):
                with self.assertRaisesRegex(RuntimeError, "Could not prompt"):
                    iris.connect()



class TestIngestConnectionFailure(unittest.TestCase):
    """tools/ingest_nabidh.py --input iris: if the connection fails, a readable message instead of a traceback, exit 2,
    `connection_failed` in the audit; the password is written nowhere."""

    def test_readable_error_and_audited(self):
        spec = importlib.util.spec_from_file_location("ingest_nabidh", ROOT / "tools" / "ingest_nabidh.py")
        ing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ing)
        env = {iris.ENV_URL: "jdbc:IRIS://h:51772/NS", iris.ENV_USER: "reader", iris.ENV_PASSWORD: "topsecret",
               iris.ENV_CREDENTIALS: str(ROOT / "tests" / "__no_such_credentials_file__")}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env), \
                mock.patch("sandbox.audit.OUTPUT_DIR", Path(d)), \
                mock.patch("sandbox.audit.AUDIT_DIR", Path(d) / "audit"), \
                mock.patch.object(iris, "connect", side_effect=ConnectionError("Failed to connect to server")), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            os.environ.pop(iris.ENV_ODBC, None)
            rc = ing.main(["--input", "iris", "--cohorts", "c1", "--source", "test_iris"])
            manifest = json.loads(next(Path(d).glob("*_ingest_nabidh_*/run_manifest.json")).read_text(encoding="utf-8"))
            log = (Path(d) / "audit" / "audit_log.jsonl").read_text(encoding="utf-8")
        self.assertEqual(rc, 2)
        self.assertEqual(manifest["status"], "connection_failed")
        self.assertIn("Could not connect to IRIS (h:51772/NS): ConnectionError", out.getvalue())
        self.assertIn("check_environment.py --iris", out.getvalue())
        self.assertNotIn("topsecret", out.getvalue() + log + json.dumps(manifest))


if __name__ == "__main__":
    unittest.main()
