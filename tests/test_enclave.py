"""tools/enclave.py + src/sandbox/io/explore.py: IRIS exploration from the terminal and the COPY block (SQLite
instead of IRIS).

Main claim: no patient-level value gets into the block copied out of the enclave — no values in ID / birth date
columns, values seen in < 10 distinct patients are not shown, counts < 10 are suppressed, percentages are not
mistaken for counts and mangled."""
import contextlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import pandas as pd  # noqa: E402

import enclave  # noqa: E402
from sandbox import audit, breakdowns, sdc  # noqa: E402
from sandbox.io import explore, iris  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402

SCHEMA = nabidh.IRIS_COHORTS["c1"]["schema"]   # enclave --iris-sqlite attaches c1.sqlite under this name


def fixture_tables() -> dict[str, pd.DataFrame]:
    """30 patients. 'Rareland' in one patient only; that patient has 12 'ZZ-1' observations (rows ≥ 10 but 1 patient)."""
    ids = [f"P{i:03d}" for i in range(30)]
    patients = pd.DataFrame({
        "PatientID": ids, "Sex": ["M"] * 15 + ["F"] * 15,
        "DateOfBirth": [f"19{50 + i}-01-0{1 + i % 9}" for i in range(30)],
        "Nationality": ["India"] * 20 + ["Nepal"] * 9 + ["Rareland"],
    })
    obs = [{"PatientID": p, "Code": "39156-5", "Value": f"{20 + i * 0.37:.1f}", "ObsDate": f"2021-0{1 + i % 9}-1{i % 10}"}
           for i, p in enumerate(ids * 2)]
    obs += [{"PatientID": ids[-1], "Code": "ZZ-1", "Value": "1", "ObsDate": "2022-02-02"}] * 12
    return {"Patient": patients, "Observation": pd.DataFrame(obs)}


class _Db:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        iris.write_sqlite_standin(cls.dir / "c1.sqlite", fixture_tables())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def conn(self):
        c = iris.sqlite_standin({SCHEMA: self.dir / "c1.sqlite"})
        self.addCleanup(c.close)
        return c


class TestShapesAndNames(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(explore.shape("2023-01-05"), "9999-99-99")
        self.assertEqual(explore.shape("E11.9"), "a99.9")
        self.assertEqual(explore.shape("Never smoked"), "a a")
        self.assertEqual(explore.shape("66841"), "99999")
        self.assertEqual(explore.shape("2023-01-05 10:00:00"), "9999-99-99 99:99:99")

    def test_sensitive_names(self):
        for name in ("PatientID", "patient_id", "date_of_birth", "DateOfBirth", "DOB", "FirstName", "Name",
                     "EmiratesID", "MobileNumber", "Email", "MRN", "HSAA_PatientId"):
            self.assertTrue(explore.is_sensitive(name), name)
        for name in ("Sex", "Nationality", "DrugName", "TestName", "Code", "ObservationValue", "SmokingStatus",
                     "diagnosis_date", "loinc", "Description"):
            self.assertFalse(explore.is_sensitive(name), name)

    def test_patient_key(self):
        self.assertEqual(explore.patient_key(["ObsID", "PatientID", "Code"]), "PatientID")
        self.assertEqual(explore.patient_key(["code", "patient_id"]), "patient_id")
        self.assertEqual(explore.patient_key(["MRN", "x"]), "MRN")
        self.assertIsNone(explore.patient_key(["Code", "Value"]))

    def test_profile_kinds(self):
        p = explore.profile_column("ObsDate", pd.Series(["2021-01-01", "2021-02-03", None]))
        self.assertEqual((p["kind"], p["filled"], p["shape"]), ("date", 2, "9999-99-99"))
        p = explore.profile_column("EventDate", pd.Series(["66841", "66900"] * 5))
        self.assertTrue(p["kind"].startswith("date?"))
        p = explore.profile_column("Id", pd.Series([f"X{i}" for i in range(30)]))
        self.assertTrue(p["kind"].startswith("unique"))
        self.assertIsNotNone(explore.hidden_reason("Id", p))


class TestCatalog(_Db, unittest.TestCase):
    def test_schemas_tables_columns(self):
        c = self.conn()
        self.assertEqual(explore.list_schemas(c)["schema"].tolist(), [SCHEMA])
        self.assertEqual(sorted(explore.list_tables(c, SCHEMA.lower())["table"]), ["Observation", "Patient"])
        self.assertEqual(explore.list_columns(c, SCHEMA, "Patient")["column"].tolist(),
                         ["PatientID", "Sex", "DateOfBirth", "Nationality"])
        self.assertEqual(explore.resolve_table(c, f"{SCHEMA.lower()}.patient"), (SCHEMA, "Patient"))
        with self.assertRaisesRegex(LookupError, "Patient"):
            explore.resolve_table(c, f"{SCHEMA}.Patiant")
        with self.assertRaises(ValueError):
            explore.resolve_table(c, "Patient")

    def test_find_and_count(self):
        c = self.conn()
        tables, cols = explore.find(c, "nation")
        self.assertTrue(tables.empty)
        self.assertEqual(cols[["table", "column"]].values.tolist(), [["Patient", "Nationality"]])
        self.assertEqual(explore.count_query(c, f"SELECT DISTINCT PatientID FROM {SCHEMA}.Observation;"), 30)
        with self.assertRaises(ValueError):
            explore.count_query(c, f"DELETE FROM {SCHEMA}.Patient")

    def test_table_profile_hides_identifiers(self):
        n, n_smp, prof = explore.table_profile(self.conn(), SCHEMA, "Patient")
        self.assertEqual((n, n_smp), (30, 30))
        vis = dict(zip(prof["column"], prof["values"]))
        self.assertEqual(vis["PatientID"], "hidden")
        self.assertEqual(vis["DateOfBirth"], "hidden")
        self.assertEqual(vis["Sex"], "use values")


class TestValueCounts(_Db, unittest.TestCase):
    def test_values_need_ten_patients(self):
        v = explore.value_counts(self.conn(), SCHEMA, "Observation", "Code")
        self.assertEqual(v["patient_col"], "PatientID")
        self.assertEqual(v["values"]["v"].tolist(), ["39156-5"])          # ZZ-1: 12 rows but 1 patient
        self.assertEqual(v["rest_small"], {"values": 1, "rows": 12})
        v = explore.value_counts(self.conn(), SCHEMA, "Patient", "Nationality")
        self.assertEqual(v["values"]["v"].tolist(), ["India"])            # Nepal 9, Rareland 1 patient
        self.assertEqual(v["rest_small"]["values"], 2)

    def test_without_patient_key_rows_rule(self):
        v = explore.value_counts(self.conn(), SCHEMA, "Observation", "Code", patient_col="none")
        self.assertIn("ZZ-1", v["values"]["v"].tolist())                  # row rule: 12 ≥ 10

    def test_sensitive_and_continuous(self):
        for col in ("PatientID", "DateOfBirth"):
            v = explore.value_counts(self.conn(), SCHEMA, "Patient", col)
            self.assertIsNotNone(v["hidden"], col)
            self.assertIsNone(v["values"], col)
        v = explore.value_counts(self.conn(), SCHEMA, "Observation", "Value", where="Code = '39156-5'")
        self.assertTrue(v["distribution_only"])
        self.assertEqual(set(v["quantiles"]), {"p5", "p25", "p50", "p75", "p95"})
        v = explore.value_counts(self.conn(), SCHEMA, "Observation", "ObsDate")
        self.assertTrue(v["distribution_only"])
        self.assertRegex(v["quantiles"]["p50"], r"^\d{4}-\d{2}$")         # month resolution

    def test_unknown_column_suggests(self):
        with self.assertRaisesRegex(LookupError, "Nationality"):
            explore.value_counts(self.conn(), SCHEMA, "Patient", "Nationalty")


class FakeIris:
    """Fake DB-API connection for the IRIS dialect (INFORMATION_SCHEMA, TOP, %EXACT): records the SQL sent and returns
    canned results by pattern. Tests the Python side of this path, not IRIS itself."""

    def __init__(self):
        self.sql = []

    def cursor(self):
        conn = self

        class Cur:
            description, _rows = None, []

            def execute(self, sql):
                conn.sql.append(sql)
                cols, self._rows = conn.respond(sql)
                self.description = [(c,) for c in cols]

            def fetchall(self):
                return self._rows

            def close(self):
                pass
        return Cur()

    @staticmethod
    def respond(sql):
        if "INFORMATION_SCHEMA.TABLES GROUP BY" in sql:
            return ["SCHEMA_NAME", "TABLE_TYPE", "N"], [("HSAA", "BASE TABLE", 3), ("HSAA", "VIEW", 1),
                                                       ("%Library", "SYSTEM TABLE", 9), ("Ens_Config", "BASE TABLE", 2)]
        if "FROM INFORMATION_SCHEMA.TABLES WHERE UPPER(TABLE_SCHEMA)" in sql:
            return ["TABLE_SCHEMA", "TABLE_NAME", "TABLE_TYPE"], [("HSAA", "Patient", "BASE TABLE")]
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            return ["COLUMN_NAME", "DATA_TYPE", "IS_NULLABLE"], [("PatientId", "VARCHAR", "NO"), ("Gender", "VARCHAR", "YES")]
        if "GROUP BY %EXACT" in sql:
            return ["V", "N", "NP"], [("M", 20, 20), ("F", 19, 19), ("U", 1, 1)]
        if "COUNT(*) AS n, COUNT(" in sql:
            return ["N", "NN"], [(40, 39)]
        if sql.startswith("SELECT TOP 5000"):
            return ["Gender"], [("M",)] * 20 + [("F",)] * 19 + [(None,)]
        raise AssertionError(f"unexpected SQL: {sql}")


class TestIrisDialect(unittest.TestCase):
    def test_catalog_and_values_sql(self):
        c = FakeIris()
        sch = explore.list_schemas(c)
        self.assertEqual(sch.to_dict("records"), [{"schema": "Ens_Config", "tables": 2, "views": 0},
                                                  {"schema": "HSAA", "tables": 3, "views": 1}])   # % hidden
        self.assertEqual(explore.resolve_table(c, "hsaa.patient"), ("HSAA", "Patient"))
        v = explore.value_counts(c, "HSAA", "Patient", "gender")
        self.assertEqual(v["patient_col"], "PatientId")
        self.assertEqual(v["values"]["v"].tolist(), ["M", "F"])
        self.assertEqual(v["rest_small"], {"values": 1, "rows": 1})
        grp = next(s for s in c.sql if "GROUP BY" in s and "%EXACT" in s)
        self.assertTrue(grp.startswith('SELECT TOP 1000 %EXACT("Gender") AS v, COUNT(*) AS n, '
                                       'COUNT(DISTINCT "PatientId") AS np FROM "HSAA"."Patient"'), grp)
        self.assertTrue(all(iris.assert_select(s) for s in c.sql))


@contextlib.contextmanager
def temp_outputs():
    """Point the audit and the day's block file at a temporary directory (no test run in the real
    outputs/audit_log.jsonl or logs/enclave/). The directory is inside the repo (outputs/ is untracked): the audit
    writes output paths relative to the repo root. The block files are under <out>.parent / "logs" / "enclave"."""
    (ROOT / "outputs").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "outputs", prefix=".test_enclave_") as d:
        out = Path(d) / "outputs"
        with mock.patch.object(audit, "OUTPUT_DIR", out), mock.patch.object(audit, "AUDIT_DIR", out / "audit"), \
                mock.patch("sandbox.config.OUTPUT_DIR", out), \
                mock.patch.object(enclave, "LOG_DIR", Path(d) / "logs" / "enclave"):
            yield out


def day_logs(out: Path) -> list[Path]:
    """The day files written under temp_outputs()."""
    return sorted((out.parent / "logs" / "enclave").glob("*.log"))


def screen_block(text: str) -> str:
    """The block as printed: COPY START … COPY END (the 'Saved to' line below it is outside)."""
    i, j = text.index(enclave.MARK_START), text.index(enclave.MARK_END)
    return text[i:j + len(enclave.MARK_END)]


def run_main(argv) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = enclave.main(argv)
    return rc, buf.getvalue()


class TestEnclaveCli(_Db, unittest.TestCase):
    def test_values_block_has_no_patient_values(self):
        with temp_outputs() as out:
            rc, text = run_main(["values", f"{SCHEMA}.Patient", "Nationality", "--iris-sqlite", str(self.dir)])
            self.assertEqual(rc, 0, text)
            lines = text.strip().splitlines()
            self.assertTrue(lines[0].startswith("----8<---- COPY START"))
            self.assertEqual(lines[-2], enclave.MARK_END)
            self.assertRegex(lines[-1], r"^Saved to outputs/\.test_enclave_\w+/logs/enclave/\d{4}-\d{2}-\d{2}\.log ")
            self.assertIn("India", text)
            self.assertNotIn("Rareland", text)
            self.assertNotIn("Nepal", text)
            saved = list(out.glob("*_enclave_values_*/enclave/block.txt"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].read_text(encoding="utf-8").strip(), screen_block(text))
            rc, again = run_main(["last"])
            self.assertEqual(screen_block(again), screen_block(text))

    def test_cohort_alias(self):
        self.assertEqual(enclave.cohort_alias("c1.Patient"), f"{SCHEMA}.Patient")
        self.assertEqual(enclave.cohort_alias("C2"), nabidh.IRIS_COHORTS["c2"]["schema"])
        for same in (f"{SCHEMA}.Patient", "HSAA.Patient", "c1x.Patient", ".Patient"):
            self.assertEqual(enclave.cohort_alias(same), same)
        with temp_outputs():
            rc, text = run_main(["values", "c1.Patient", "Nationality", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 0, text)
        self.assertIn(f"{SCHEMA}.Patient.Nationality", text)

    def test_columns_block_hides_ids(self):
        with temp_outputs():
            rc, text = run_main(["columns", f"{SCHEMA}.patient", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 0, text)
        self.assertNotIn("P001", text)
        self.assertNotIn("1951-01-02", text)
        self.assertIn("9999-99-99", text)

    def test_error_inside_block(self):
        with temp_outputs():
            rc, text = run_main(["tables", "NOPE", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 1)
        self.assertIn("no such schema", text)
        self.assertEqual(text.strip().splitlines()[-2], enclave.MARK_END)

    def test_header_shows_sandbox_params(self):
        """SANDBOX_PARAMS (parameter values only) in the header: an exploration run is told apart in the block."""
        with temp_outputs(), mock.patch.dict(os.environ, {"SANDBOX_PARAMS": '{"lrs_variant":  "assessment_2010"}'}):
            rc, text = run_main(["req", "R9"])
        header = screen_block(text).splitlines()[0]
        self.assertRegex(header, r'^----8<---- COPY START \| enclave req R9 \| SANDBOX_PARAMS \{"lrs_variant": '
                                 r'"assessment_2010"\} \| \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC \| ingest v')
        with temp_outputs(), mock.patch.dict(os.environ, {"SANDBOX_PARAMS": " "}):
            rc, text = run_main(["req", "R9"])
        self.assertNotIn("SANDBOX_PARAMS", screen_block(text).splitlines()[0])

    def test_req_stdlib_checks(self):
        with temp_outputs():
            rc, text = run_main(["req", "r9", "R1"])
        self.assertIn("[R9]", text)
        self.assertIn("Summary: R9", text)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            enclave.main(["req", "R10"])


class TestDayLog(_Db, unittest.TestCase):
    """logs/enclave/<UTC date>.log: only the block (header … end marker) goes in, under the header's date; a second
    command the same day is appended to the same file; `last` reprints without appending."""

    def test_blocks_appended_to_the_day_file_last_not_again(self):
        with temp_outputs() as out:
            self.assertTrue(enclave.LOG_DIR.is_relative_to(out.parent))     # not the real logs/enclave/
            rc1, t1 = run_main(["values", f"{SCHEMA}.Patient", "Nationality", "--iris-sqlite", str(self.dir)])
            rc2, t2 = run_main(["req", "R9"])
            files = day_logs(out)
            self.assertEqual(len(files), 1, files)
            day = files[0]
            self.assertIn(f" | {day.stem} ", screen_block(t1).splitlines()[0])  # file date = the header's UTC date
            self.assertEqual(day.read_text(encoding="utf-8"), screen_block(t1) + "\n\n" + screen_block(t2) + "\n")
            self.assertEqual(t1.strip().splitlines()[-1], f"Saved to {enclave.repo_rel(day)} (block 1 of the UTC day)")
            self.assertEqual(t2.strip().splitlines()[-1], f"Saved to {enclave.repo_rel(day)} (block 2 of the UTC day)")
            before = day.read_text(encoding="utf-8")
            rc, again = run_main(["last"])
            self.assertEqual(rc, 0)
            self.assertEqual(day.read_text(encoding="utf-8"), before)
            self.assertIn(screen_block(again), before)                  # (same-second runs: either block)
            self.assertNotIn("Saved to", again)
            self.assertEqual(again.strip().splitlines()[-1], f"Already in {enclave.repo_rel(day)} (not saved again)")

    def test_unwritable_log_dir_keeps_the_block(self):
        with temp_outputs() as out:
            blocker = out.parent / "logs"
            blocker.write_text("not a directory", encoding="utf-8")    # mkdir logs/enclave fails
            rc, text = run_main(["req", "R9"])
        self.assertEqual(text.strip().splitlines()[-2], enclave.MARK_END)
        self.assertIn("(could not save the block to", text.strip().splitlines()[-1])


class TestChecks(unittest.TestCase):
    """`checks`: the step 1 queries in one block; a missing table is one line, not a stop; < 10 patients not shown."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        ids = [f"P{i:03d}" for i in range(30)]
        obs = [{"PatientID": p, "ObservationCode_Code": "8302-2", "ObservationValue": f"{150 + i * 1.3:.1f}"}
               for i, p in enumerate(ids)]
        obs += [{"PatientID": ids[-1], "ObservationCode_Code": "ZZ-9", "ObservationValue": "777"}] * 12
        iris.write_sqlite_standin(cls.dir / "c1.sqlite", {"Observation": pd.DataFrame(obs)})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_one_block_missing_tables_reported(self):
        with temp_outputs():
            rc, text = run_main(["checks", "1c", "1D", "--cohorts", "c1", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 0, text)
        self.assertEqual(text.count("COPY START"), 1)
        self.assertEqual(text.strip().splitlines()[-2], enclave.MARK_END)
        self.assertIn("== 1c · c1.Observation.ObservationValue · WHERE ObservationCode_Code = '8302-2'", text)
        self.assertIn("Distribution (sample)", text)                    # continuous → percentiles, no value list
        self.assertIn("== 1c · c1.LabResultItem.TestItemCode_Code", text)
        self.assertIn("not available", text)                            # no LabResultItem / Diagnosis / FamilyHistory
        self.assertIn("8302-2", text)
        self.assertNotIn("ZZ-9", text)                                   # 12 rows but 1 patient
        self.assertNotIn("777", text)
        n = len(enclave.CHECKS["1c"][1]) + len(enclave.CHECKS["1d"][1])
        self.assertRegex(text, rf"checks 1c 1d: (\d+) queries done, (\d+) not available")
        done, failed = map(int, re.search(r"(\d+) queries done, (\d+) not available", text).groups())
        self.assertEqual(done + failed, n)

    def test_all_failed_and_unknown_id(self):
        with temp_outputs():
            rc, text = run_main(["checks", "1a", "--cohorts", "c1", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 1, text)                                    # no SocialHistory at all
        self.assertIn("0 queries done", text)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            enclave.main(["checks", "1z", "--iris-sqlite", str(self.dir)])


class TestSmokingCheck(unittest.TestCase):
    """`checks 1s`: counts of where the smoking status comes from; < 10 suppressed; NULL ids don't empty NOT IN."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        ids = [f"P{i:03d}" for i in range(30)]
        sh = [{"Patient": p, "SocialHabitCategory_Code": "Smoking", "SocialHabitQty_Description": "Never",
               "EnteredOn": ""} for p in ids[:12]]
        sh += [{"Patient": p, "SocialHabitCategory_Code": "Smoking", "SocialHabitQty_Description": "Unknown",
                "EnteredOn": ""} for p in ids[12:20]]
        sh += [{"Patient": None, "SocialHabitCategory_Code": "Smoking", "SocialHabitQty_Description": "Never",
                "EnteredOn": ""}]
        dx = [{"Patient": p, "Diagnosis_Code": "Z72.0", "DiagnosisDate": "2021-01-01"} for p in ids[15:25]]
        iris.write_sqlite_standin(cls.dir / "c1.sqlite", {
            "Patient": pd.DataFrame({"ID": ids, "Gender_Code": ["M"] * 30}),
            "SocialHistory": pd.DataFrame(sh), "Diagnosis": pd.DataFrame(dx)})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def count_after(self, text, label):
        i = text.index(f"== 1s · c1 · {label}")
        return text[i:].splitlines()[1].strip()

    def test_counts(self):
        with temp_outputs():
            rc, text = run_main(["checks", "1s", "--cohorts", "c1", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 0, text)
        self.assertEqual(self.count_after(text, "patients (Patient.ID)"), "30")
        self.assertEqual(self.count_after(text, "patients with any SocialHistory row"), "20")      # the NULL id not counted
        self.assertEqual(self.count_after(text, "patients with a tobacco item and a usable value"), "12")
        self.assertEqual(self.count_after(text, "patients whose tobacco records are all Unknown or empty"), "<10")
        self.assertEqual(self.count_after(text, "patients with a smoking diagnosis code"), "10")
        self.assertEqual(self.count_after(text, "patients with neither a SocialHistory row nor a smoking diagnosis code"), "<10")
        self.assertIn("tables / columns whose name contains 'SMOK'", text)
        self.assertNotIn("P00", text)                                       # no patient ids in the block


class TestIrisSetup(unittest.TestCase):
    def test_writes_private_file_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as d, temp_outputs():
            cred = Path(d) / "nabidh_iris"
            cred.write_text("NABIDH_IRIS_URL=jdbc:IRIS://old:1/OLD\nNABIDH_IRIS_PASSWORD=s3cret\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {iris.ENV_CREDENTIALS: str(cred)}):
                rc, text = run_main(["iris-setup", "--namespace", "NABIDH", "--user", "reader", "--yes"])
                got = iris.read_credentials_file(cred)
            self.assertEqual(rc, 0, text)
            self.assertEqual(got[iris.ENV_URL], f"jdbc:IRIS://{enclave.DEFAULT_IRIS_HOST}:{enclave.DEFAULT_IRIS_PORT}/NABIDH")
            self.assertEqual(got[iris.ENV_USER], "reader")
            self.assertEqual(got[iris.ENV_PASSWORD], "s3cret")                  # kept
            self.assertNotIn("s3cret", text)                                    # not printed
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(cred.stat().st_mode), 0o600)

    def test_refuses_file_inside_repo(self):
        with temp_outputs(), mock.patch.dict(os.environ, {iris.ENV_CREDENTIALS: str(ROOT / "outputs" / "x_iris")}):
            rc, text = run_main(["iris-setup", "--url", "jdbc:IRIS://h:1/NS", "--user", "u", "--yes"])
        self.assertEqual(rc, 1)
        self.assertIn("inside the repo", text)
        self.assertFalse((ROOT / "outputs" / "x_iris").exists())


class TestOutputTables(unittest.TestCase):
    def test_safe_table(self):
        df = pd.DataFrame({"group": ["a", "b"], "n": [5, 120], "n_bad": [0, 3], "pct_patients": [4.0, 96.0],
                           "patients_with_any": [7, 200]})
        got = enclave.safe_table(df)
        self.assertEqual(got["n"].tolist(), ["<10", 120])
        self.assertEqual(got["n_bad"].tolist(), [0, "<10"])
        self.assertEqual(got["patients_with_any"].tolist(), ["<10", 200])
        self.assertEqual(got["pct_patients"].tolist(), [4.0, 96.0])              # a percentage is not a count
        with self.assertRaises(ValueError):
            enclave.safe_table(pd.DataFrame({"patient_id": ["P1"], "n": [1]}))

    def test_framework_pivot_hides_small_pct(self):
        df = pd.DataFrame({"cohort": ["c1", "c2"], "domain": ["dx", "dx"], "group": ["gdm", "gdm"],
                           "patients_with_any": ["<10", "212"], "pct_patients": [0.3, 8.2]})
        got = enclave.framework_pivot(df)
        self.assertEqual(got[["c1", "c2"]].values.tolist(), [["<10 patients", 8.2]])

    def test_completeness_tables_and_kpi_note_in_block(self):
        """NB1 per-variable completeness (measure / meets_90 / note) and joint core-7 reach the block; the KPI step
        prints the Data Completeness note (weakest variable, without ethnicity) in full."""
        note = ("Weakest variable: C1 ethnicity 0.0% · Without ethnicity (weakest of the other 7): C1 smoking 92.0% · "
                "Joint core-7 (all but ethnicity): C1 90.0% (N=900/1000)")
        absent = "no record = absent: 100% by definition, not a fill rate"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "nb01").mkdir()
            (Path(d) / "kpi").mkdir()
            pd.DataFrame({"cohort": ["c1"] * 3, "group": ["all", "all", "T2DM"],
                          "variable": ["cvd", "family_history_recorded", "cvd"],
                          "measure": ["present_absent", "recorded", "present_absent"], "n": [1000, 1000, 600],
                          "complete_n": [1000, 5, 600], "complete_pct": [100.0, "suppressed (<10)", 100.0],
                          "meets_90": ["-", False, "-"],
                          "note": [absent, "FamilyHistory record or Z83.3", absent]}
                         ).to_csv(Path(d) / "nb01" / "completeness_by_variable.csv", index=False)
            pd.DataFrame({"cohort": ["c1"], "group": ["all"], "n": [1000], "joint_core7_n": [900],
                          "joint_core7_pct": [90.0], "joint_core8_n": [0], "joint_core8_pct": [0.0]}
                         ).to_csv(Path(d) / "nb01" / "joint_completeness.csv", index=False)
            pd.DataFrame({"kpi": ["Audit Trail Completeness", "Data Completeness for Required Variables"],
                          "target": ["100%", ">= 90%"], "actual": ["100.0% (1/1 runs)", "C1 0.0%"],
                          "met": ["Met", "Not Met"], "notes": [None, note]}
                         ).to_csv(Path(d) / "kpi" / "kpi_table.csv", index=False)
            block = enclave.Block("HEADER")
            with contextlib.redirect_stdout(io.StringIO()):
                enclave.summary_tables("nb1")(Path(d), block, mock.Mock(max_rows=60))
                enclave.summary_tables("kpi")(Path(d), block, mock.Mock(max_rows=60))
        text = "\n".join(block.lines)
        self.assertIn("-- nb01/completeness_by_variable.csv (2 rows)", text)    # group "all" only
        line = next(ln for ln in block.lines if "family_history_recorded" in ln)
        self.assertIn("recorded", line)
        self.assertIn("<10", line)                                               # complete_n 5
        self.assertIn("100% by definition, not a fill rate", text)
        self.assertNotIn("NaN", next(ln for ln in block.lines if " cvd " in ln))   # meets_90 "-", not NaN
        self.assertIn("joint_core7_pct", text)
        self.assertIn(note, text)                                                # not truncated
        self.assertEqual(sum("Data Completeness for Required Variables" in ln for ln in block.lines), 2)

    END = pd.Timestamp("2025-12-31")

    def block_tables(self, facility_ids):
        """NB0 / NB1 block tables written as the notebooks write them (breakdowns + sdc), with small cells: C1 smoking
        3 / 4 / 5 of 60, C2 5 of 200 missing; C2 demographics 4 of 30 outside 25–84, 3 women; SMD 3 of 50; facility.
        Returns (block lines, raw tables: the leak scan's input)."""
        def patients(n_in, n_out, males):
            dob = [self.END - pd.Timedelta(days=round(a * 365.25)) for a in [50.0] * n_in + [90.0] * n_out]
            return pd.DataFrame({"sex": ["Male"] * males + ["Female"] * (n_in + n_out - males),
                                 "date_of_birth": pd.to_datetime(pd.Series(dob)), "facility_id": None})

        demo = pd.DataFrame([{"cohort": "c1", **breakdowns.demographics(patients(170, 30, 120), self.END)},
                             {"cohort": "c2", **breakdowns.demographics(patients(26, 4, 27), self.END)}])
        fac = pd.DataFrame([{"cohort": "c1", **breakdowns.facility_representation(
            pd.DataFrame({"facility_id": facility_ids}))}])
        snap = lambda src, conflict=0: pd.DataFrame({       # noqa: E731
            "smoking_source": pd.Series(src, dtype=object),
            "smoking_undated_conflict": [False] * (len(src) - conflict) + [True] * conflict})
        sm = pd.concat([breakdowns.smoking_source(snap(["structured"] * 48 + ["diagnosis_code"] * 3 + [None] * 9, 5))
                        .assign(cohort="c1"),
                        breakdowns.smoking_source(snap(["structured"] * 195 + [None] * 5)).assign(cohort="c2")],
                       ignore_index=True)[["cohort", "smoking_source", "n", "n_cohort", "pct"]]
        f1 = pd.DataFrame({"age": [40.0, 61.0] * 25, "rare": [True] * 3 + [False] * 47, "male": [True] * 30 + [False] * 20})
        f2 = pd.DataFrame({"age": [44.0, 66.0] * 25, "rare": [True] * 12 + [False] * 38, "male": [True] * 26 + [False] * 24})
        sel = breakdowns.selection_effect(f1, f2)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "nb00").mkdir()
            (d / "nb01").mkdir()
            breakdowns.suppressed_demographics(demo).to_csv(d / "nb00" / "demographics.csv", index=False)
            breakdowns.suppressed_facility(fac).to_csv(d / "nb00" / "facility_representation.csv", index=False)
            breakdowns.suppressed_shares(sm).to_csv(d / "nb01" / "smoking_source.csv", index=False)
            breakdowns.suppressed_selection_effect(sel).to_csv(d / "nb01" / "selection_effect_smd.csv", index=False)
            block = enclave.Block("HEADER")
            with contextlib.redirect_stdout(io.StringIO()):
                enclave.summary_tables("nb0")(d, block, mock.Mock(max_rows=60))
                enclave.summary_tables("nb1")(d, block, mock.Mock(max_rows=60))
        return block.lines, {"demo": demo, "fac": fac, "sm": sm, "sel": sel}

    def test_new_tables_in_block(self):
        lines, _ = self.block_tables(["F1"] * 60 + ["F2"] * 25 + [None] * 15)
        text = "\n".join(lines)
        self.assertIn("-- nb00/demographics.csv (2 rows)", text)
        header = next(ln for ln in lines if "age_outside_25_84_pct" in ln).split()
        self.assertEqual(header, ["cohort", "n", "age_median", "age_iqr", "age_missing_n", "age_outside_25_84_n",
                                  "age_outside_25_84_pct", "male_pct"])
        c1 = next(ln for ln in lines if ln.split()[:2] == ["c1", "200"]).split()
        self.assertEqual(c1[5:], ["30", "15.0", "60.0"])                         # 30 of 200 outside 25–84
        self.assertIn("-- nb00/facility_representation.csv (1 rows)", text)      # a facility is known: the table
        self.assertIn("-- nb01/selection_effect_smd.csv (3 rows)", text)
        self.assertEqual(next(ln for ln in lines if "|smd|>0.1" in ln).split(), ["variable", "c1", "c2", "smd", "|smd|>0.1"])
        self.assertEqual(next(ln for ln in lines if ln.split()[:1] == ["male"]).split()[1:3], ["0.6", "0.52"])
        self.assertIn("-- nb01/smoking_source.csv (6 rows)", text)
        self.assertNotIn("n_cohort", text)

    def test_facility_not_mapped_is_one_line(self):
        lines, _ = self.block_tables([None] * 50 + ["unknown"] * 5)
        fac = [ln for ln in lines if "facility" in ln]
        self.assertEqual(fac, ["-- nb00/facility_representation.csv: no facility in any cohort (facility_id empty / "
                               "unknown; the adapter maps none yet — DHA question)"])
        self.assertTrue(enclave.no_facility(pd.DataFrame()))
        self.assertFalse(enclave.no_facility(pd.DataFrame({"n_facilities": [0, 3]})))

    def test_no_small_count_or_rate_in_block(self):
        """No count 0 < n < 10 in a count column, and no rate whose count or (N − count) is < 10 (rate × N gives the
        count back), in any of the new block tables or smoking_source; checked against the unsuppressed values."""
        lines, raw = self.block_tables(["F1"] * 95 + ["F2"] * 3 + [None] * 2)
        tokens = {t for ln in lines for t in ln.split()}

        def small(x):
            return pd.notna(x) and 0 < x < 10

        def forms(v):
            return {str(v), f"{v:.1f}", f"{v:.2f}", f"{v:.3f}"}

        leaked_rates, small_counts = set(), set()
        for name, num, den, rate in [("sm", "n", "n_cohort", "pct"),
                                     ("demo", "age_outside_25_84_n", "n", "age_outside_25_84_pct"),
                                     ("demo", "age_25_84_n", "n", "age_25_84_pct"), ("demo", "male_n", "n", "male_pct"),
                                     ("fac", "top_facility_n", "facility_known_n", "top_facility_share_pct"),
                                     ("sel", "c1_k", "c1_n", "c1"), ("sel", "c1_k", "c1_n", "smd")]:
            for _, r in raw[name].iterrows():
                k, n = r[num], r[den]
                if small(k) or small(n - k):
                    leaked_rates |= forms(r[rate])
                if small(k):
                    small_counts.add(str(int(k)))
        fac = raw["fac"].iloc[0]
        leaked_rates |= forms(fac["facility_missing_pct"])                       # 2 of 100 missing
        self.assertTrue({"8.3", "97.5", "13.3", "86.7", "90.0", "96.9", "2.0", "0.06"} <= leaked_rates)   # fixture check
        self.assertEqual(small_counts, {"3", "4", "5"})
        self.assertFalse(leaked_rates & tokens, sorted(leaked_rates & tokens))
        self.assertFalse(small_counts & tokens, sorted(small_counts & tokens))
        self.assertIn("<10", tokens)
        self.assertIn("suppressed (<10)", "\n".join(lines))
        self.assertIn("80.0", tokens)                                            # 48 of 60: shown (12 others)

    def test_failure_lines(self):
        log = ["x", "Traceback (most recent call last):", f'  File "{ROOT}/tools/x.py", line 3, in <module>',
               "ValueError: bad"]
        got = enclave.failure_lines(log)
        self.assertTrue(got[0].startswith('Where: File "./tools/x.py", line 3'))
        self.assertEqual(got[1], "Error: ValueError: bad")

    def test_safe_argv_drops_url_parameters(self):
        got = enclave.safe_argv(["iris-setup", "--url", "jdbc:IRIS://h:1/NS;password=x", "--url=jdbc:IRIS://h:1/NS?p=y"])
        self.assertEqual(got, ["iris-setup", "--url", "jdbc:IRIS://h:1/NS", "--url=jdbc:IRIS://h:1/NS"])

    def test_medication_summary_hides_rare_names(self):
        v = pd.DataFrame({"source": ["medications"] * 5 + ["patient_profile"],
                          "field": ["drug → ATC method", "drug → ATC method", "drug_name without study drug class",
                                    "drug_name without study drug class", "rows dropped: no study drug class", "sex"],
                          "value": ["DDC code", "name: ingredient", "PANADOL", "RARE BRAND X", "<no ATC>", "M"],
                          "n_rows": ["1200", "<10", "340", "<10", "350", "900"]})
        got = enclave.medication_summary(v)
        self.assertEqual(got["value"].tolist(), ["DDC code", "name: ingredient", "<no ATC>", "PANADOL"])
        self.assertNotIn("RARE BRAND X", got["value"].tolist())                 # a name with < 10 rows is not printed

    def test_family_history_summary(self):
        v = pd.DataFrame({"source": ["family_history"] * 4 + ["medications"],
                          "field": ["diabetes recognised by", "diabetes recognised by",
                                    "condition | condition_text (non-diabetes, dropped)",
                                    "condition | condition_text (non-diabetes, dropped)", "diabetes recognised by"],
                          "value": ["SNOMED code", "text only", "5 | Hypertension", "9 | Rare text", "x"],
                          "n_rows": ["2300", "<10", "42", "<10", "1"]})
        got = enclave.field_summary(v, "family_history", enclave.FH_FIELDS, suffix=True)
        self.assertEqual(got["value"].tolist(), ["SNOMED code", "text only", "5 | Hypertension"])

    def test_lab_summary(self):
        f = "glycaemic-looking tests (dropped): code | unit | name"
        v = pd.DataFrame({"source": ["lab_results"] * 5 + ["observations"],
                          "field": ["study lab: code | unit | name", "value by kind | unit", f, f,
                                    "study lab: code | unit | name", "study lab: code | unit | name"],
                          "value": ["4548-4 | % | HbA1c", "hba1c | % : 812 patients, p5 5.2 / median 6.9 / p95 10.1",
                                    "LOC-1 | % | HbA1c", "LOC-2 | mg/dL | Rare glucose", "9-9 | % | Rare", "x"],
                          "n_rows": ["4100", "4100", "35", "<10", "<10", "1"]})
        got = enclave.field_summary(v, "lab_results", enclave.LAB_FIELDS)
        self.assertEqual(got["value"].tolist(), ["4548-4 | % | HbA1c",
                                                 "hba1c | % : 812 patients, p5 5.2 / median 6.9 / p95 10.1",
                                                 "LOC-1 | % | HbA1c"])

    def test_lab_unit_spellings_in_summary(self):
        """Unit spellings (unit text, not a patient value) are shown even below 10 rows; the count stays suppressed."""
        f = "study lab unit: delivered → canonical"
        v = pd.DataFrame({"source": ["lab_results"] * 3, "field": [f] * 3,
                          "value": ["MG/DL → mg/dL", "0 → <no unit>", "NULL → <no unit>"],
                          "n_rows": ["611", "<10", "<10"]})
        got = enclave.field_summary(v, "lab_results", enclave.LAB_FIELDS)
        self.assertEqual(got["value"].tolist(), ["MG/DL → mg/dL", "0 → <no unit>", "NULL → <no unit>"])
        self.assertEqual(got["n_rows"].tolist(), ["611", "<10", "<10"])

    def test_lab_non_numeric_shapes_in_summary(self):
        """Non-numeric lab results: the raw values stay hidden below 10 rows, their shapes (no value) are shown."""
        v = pd.DataFrame({"source": ["lab_results"] * 4,
                          "field": ["lab value non-numeric (raw)", "rows dropped: non-numeric value",
                                    "non-numeric value (dropped): kind | shape",
                                    "non-numeric value (dropped): kind | shape"],
                          "value": ["<5.0", "<n rows>", "hba1c | <9.9", "fpg | a"],
                          "n_rows": ["<10", "<10", "<10", "<10"]})
        got = enclave.field_summary(v, "lab_results", enclave.LAB_FIELDS)
        self.assertEqual(got["value"].tolist(), ["<n rows>", "hba1c | <9.9", "fpg | a"])

    def test_ingest_summary_shows_dropped_empty_values(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ingest").mkdir()
            src = {"observations": {"status": "read", "rows_read": 52000, "dropped_empty_value": 7365,
                                    "dropped_empty_value_by_code": "3141-9 (4100), 8302-2 (3260), +1 labels < 10 rows"},
                   "lab_results": {"status": "read", "rows_read": 900, "dropped_empty_value": 4}}
            (Path(d) / "ingest" / "c1_summary.json").write_text(
                json.dumps({"ingest_version": "9.9.9", "n_patients": 1000, "sources": src}))
            block = enclave.Block("HEADER")
            with contextlib.redirect_stdout(io.StringIO()):
                enclave.summary_ingest(Path(d), block, mock.Mock(max_rows=60))
        obs = next(ln for ln in block.lines if ln.strip().startswith("observations"))
        self.assertIn("dropped_empty_value=7365", obs)
        self.assertIn("dropped_empty_value_by_code: 3141-9 (4100), 8302-2 (3260), +1 labels < 10 rows", obs)
        lab = next(ln for ln in block.lines if ln.strip().startswith("lab_results"))
        self.assertIn("dropped_empty_value=<10", lab)                           # small count suppressed

    def test_ingest_summary_shows_vital_distribution(self):
        """Vitals have no unit column (i32): the per-vital distribution is in the block (only groups ≥ 10 patients
        carry numbers; the adapter writes no numbers for smaller groups)."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ingest").mkdir()
            (Path(d) / "ingest" / "c1_summary.json").write_text(json.dumps({"ingest_version": "9.9.9",
                                                                            "n_patients": 1000, "sources": {}}))
            pd.DataFrame({"source": ["observations"] * 2, "field": ["vital value by concept | unit"] * 2,
                          "value": ["height_cm | <no unit> : 2400 patients, p5 1.52 / median 1.65 / p95 1.8",
                                    "bmi | <no unit> : < 10 patients with a numeric value, no distribution"],
                          "n_rows": ["5000", "<10"]}).to_csv(Path(d) / "ingest" / "c1_value_counts.csv", index=False)
            block = enclave.Block("HEADER")
            with contextlib.redirect_stdout(io.StringIO()):
                enclave.summary_ingest(Path(d), block, mock.Mock(max_rows=60))
        text = "\n".join(block.lines)
        self.assertIn("vitals (Observation; no unit column", text)
        self.assertIn("height_cm | <no unit> : 2400 patients, p5 1.52 / median 1.65 / p95 1.8", text)
        self.assertIn("bmi | <no unit> : < 10 patients with a numeric value, no distribution", text)

    def test_fmt_count(self):
        self.assertEqual([sdc.fmt_count(x) for x in (0, 3, 10, "-", None)], ["0", "<10", "10", "-", "None"])


if __name__ == "__main__":
    unittest.main()
