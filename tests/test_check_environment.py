"""tools/check_environment.py: sürüm karşılaştırma, requirements okuma, IRIS ayar / TCP / eşleme kontrolleri.
Unit testler ve pip check burada çalıştırılmaz (--quick) — kendini çağırmasın."""
import importlib.util
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sandbox.io import iris  # noqa: E402
from test_nabidh_iris import SCHEMA, raw_tables, standin  # noqa: E402
from test_nabidh_adapter import write_raw  # noqa: E402

_spec = importlib.util.spec_from_file_location("check_environment", ROOT / "tools" / "check_environment.py")
ce = importlib.util.module_from_spec(_spec)
sys.modules["check_environment"] = ce            # dataclass, modülü sys.modules'te arar
_spec.loader.exec_module(ce)

IRIS_ENV = (iris.ENV_URL, iris.ENV_USER, iris.ENV_PASSWORD, iris.ENV_ODBC)


def no_iris_settings():
    """IRIS ayarı olmayan ortam (kullanıcının ~/.nabidh_iris dosyası da okunmaz)."""
    env = {k: v for k, v in os.environ.items() if k not in IRIS_ENV}
    env[iris.ENV_CREDENTIALS] = str(ROOT / "tests" / "__no_such_credentials_file__")
    return mock.patch.dict(os.environ, env, clear=True)


def by(results, group):
    return {r.check: r for r in results if r.group == group}


class TestVersions(unittest.TestCase):
    def test_version_ok(self):
        self.assertTrue(ce.version_ok("2.1.4", ">=2.0,<4"))
        self.assertTrue(ce.version_ok("3.1.1", ">=2.0,<4"))
        self.assertFalse(ce.version_ok("1.5.3", ">=2.0,<4"))
        self.assertFalse(ce.version_ok("4.0.0", ">=2.0,<4"))
        self.assertTrue(ce.version_ok("2.0.0rc1", ">=2.0"))
        self.assertTrue(ce.version_ok("3.7", ">=3.7"))
        self.assertTrue(ce.version_ok("1.0", ""))

    def test_parse_requirements(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "req.txt"
            p.write_text("# yorum\nnumpy>=1.24,<3\n\npandas >=2.0 # satır sonu yorumu\nmatplotlib\n", encoding="utf-8")
            self.assertEqual(ce.parse_requirements(p),
                             [("numpy", ">=1.24,<3"), ("pandas", ">=2.0"), ("matplotlib", "")])

    def test_repo_requirements_parse(self):
        names = [n for n, _ in ce.parse_requirements(ROOT / "requirements.txt")]
        self.assertEqual(names, ["numpy", "pandas", "matplotlib"])


class TestRunChecks(unittest.TestCase):
    def test_this_environment_without_iris(self):
        with no_iris_settings():
            res = ce.run_checks(quick=True)
        # Testler çalışıyorsa Python sürümü ve çekirdek paketler yeterlidir; pip vb. ortama göre değişir
        self.assertEqual(by(res, "python")["Python sürümü"].status, ce.PASS)
        self.assertEqual([r for r in res if r.group == "core" and r.status == ce.FAIL], [])
        self.assertEqual(by(res, "iris")["Bağlantı ayarları"].status, ce.SKIP)
        self.assertEqual(by(res, "mapping")["Adapter eşlemesi (IRIS)"].status, ce.SKIP)
        self.assertEqual(by(res, "tests")["Unit testler + pip check"].status, ce.SKIP)

    def test_iris_required_without_settings_fails(self):
        with no_iris_settings():
            res = ce.run_checks(quick=True, iris_required=True)
        self.assertEqual(by(res, "iris")["Bağlantı ayarları"].status, ce.FAIL)

    def test_closed_port_fails_and_hides_password(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()                                        # bu port artık kapalı
        with no_iris_settings():
            os.environ.update({iris.ENV_URL: f"jdbc:IRIS://127.0.0.1:{port}/NS;password=topsecret",
                               iris.ENV_USER: "reader", iris.ENV_PASSWORD: "topsecret"})
            res, conn = ce.check_iris(False, None, None)
        self.assertIsNone(conn)
        got = {r.check: r for r in res}
        self.assertEqual(got["Bağlantı ayarları"].status, ce.PASS)
        self.assertEqual(got["TCP erişimi"].status, ce.FAIL)
        self.assertNotIn("topsecret", " ".join(r.detail for r in res))


class TestMapping(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        (self.t / "raw").mkdir()
        write_raw(self.t / "raw")

    def tearDown(self):
        self.tmp.cleanup()

    def test_mapping_ok_and_optional_absent(self):
        conn = standin(self.t, raw_tables(self.t / "raw"))
        res = {r.check: r for r in ce.check_mapping(conn, ["c1"])}
        conn.close()
        self.assertEqual(res["c1 · patient_profile"].status, ce.PASS)
        self.assertIn(f"{SCHEMA}.Patient", res["c1 · patient_profile"].detail)
        self.assertEqual(res["c1 · encounters"].status, ce.INFO)            # opsiyonel, tablo yok
        self.assertEqual(sum(r.status == ce.PASS for r in res.values()), 6)

    def test_missing_column_and_table_warn(self):
        tables = raw_tables(self.t / "raw", rename={"Diagnosis": {"code": "dx"}})
        tables.pop("Medication")
        conn = standin(self.t, tables)
        res = {r.check: r for r in ce.check_mapping(conn, ["c1"])}
        conn.close()
        self.assertEqual(res["c1 · diagnoses"].status, ce.WARN)
        self.assertIn("'code'", res["c1 · diagnoses"].detail)
        self.assertIn("dx", res["c1 · diagnoses"].detail)                 # tablodaki sütunlar listelenir
        self.assertEqual(res["c1 · medications"].status, ce.WARN)
        self.assertIn("ingest çalışmaz", res["c1 · medications"].detail)


if __name__ == "__main__":
    unittest.main()
