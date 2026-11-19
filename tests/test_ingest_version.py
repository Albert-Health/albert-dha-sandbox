"""Ingest sürümü (nabidh.INGEST_VERSION): ingest çıktısı, özet, kanonik ingest.json, KOPYALA başlığı, NB bloğu."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import enclave  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402
from test_enclave import SCHEMA, _Db, run_main, temp_outputs  # noqa: E402
from test_nabidh_adapter import write_raw  # noqa: E402

V = nabidh.INGEST_VERSION


class TestIngestVersion(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(V, r"^\d+\.\d+\.\d+$")

    def test_ingest_writes_version(self):
        spec = importlib.util.spec_from_file_location("ingest_nabidh", ROOT / "tools" / "ingest_nabidh.py")
        ing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ing)
        (ROOT / "outputs").mkdir(exist_ok=True)          # audit çıktı yollarını repo köküne göre yazar
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs", prefix=".test_ingest_version_") as d:
            d = Path(d)
            (d / "raw" / "c1").mkdir(parents=True)
            write_raw(d / "raw" / "c1")
            with mock.patch("sandbox.audit.OUTPUT_DIR", d / "out"), mock.patch("sandbox.audit.AUDIT_DIR", d / "out" / "audit"), \
                    mock.patch.object(ing, "CANONICAL_DIR", d / "canonical"), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                ing.main(["--raw-root", str(d / "raw"), "--cohorts", "c1", "--source", "test_ver"])
            meta = json.loads((d / "canonical" / "test_ver" / "c1" / "ingest.json").read_text(encoding="utf-8"))
            summary = json.loads(next((d / "out").glob("*_ingest_nabidh_*/ingest/c1_summary.json")).read_text())
            log = (d / "out" / "audit" / "audit_log.jsonl").read_text(encoding="utf-8")
        self.assertTrue(out.getvalue().startswith(f"Ingest v{V} · run "))
        self.assertEqual((meta["ingest_version"], meta["cohort"], meta["input"]), (V, "c1", "file"))
        self.assertEqual(summary["ingest_version"], V)
        self.assertIn(f'"ingest_version": "{V}"', log)

    def test_data_versions_for_notebook_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "nabidh" / "c1").mkdir(parents=True)
            (base / "nabidh" / "c1" / "ingest.json").write_text(json.dumps(
                {"ingest_version": V, "ingest_run_id": "R1"}), encoding="utf-8")
            (base / "nabidh" / "c2").mkdir()
            with mock.patch("sandbox.config.CANONICAL_DIR", base):
                self.assertEqual(enclave.data_versions("nabidh"), f"c1 ingest v{V} (R1)")
                self.assertIn("bilinmiyor", enclave.data_versions("synthetic"))


class TestBlockHeader(_Db, unittest.TestCase):
    def test_header_shows_ingest_version(self):
        with temp_outputs():
            rc, text = run_main(["values", f"{SCHEMA}.Patient", "Nationality", "--iris-sqlite", str(self.dir)])
        self.assertEqual(rc, 0, text)
        self.assertIn(f"| ingest v{V} | commit ", text.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
