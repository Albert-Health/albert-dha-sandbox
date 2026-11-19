"""src/sandbox/envfile.py: git dışı .env → os.environ (ayarlı değişkeni ezmez, audit'e yalnız anahtar adları)."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import check_environment as ce  # noqa: E402
from sandbox import audit, envfile  # noqa: E402
from test_enclave import temp_outputs  # noqa: E402

SAMPLE = """
# yorum
SANDBOX_SOURCE=nabidh
export NABIDH_IRIS_PASSWORD='p#ss=w$rd '
  SPACED_KEY  =  spaced value
QUOTED="çift tırnak"
MISMATCH="yarım'
EMPTY=
bad key=x
1BAD=x
satır eşittir yok
"""


class TestParse(unittest.TestCase):
    def test_parse(self):
        v = envfile.parse(SAMPLE)
        self.assertEqual(v["SANDBOX_SOURCE"], "nabidh")
        self.assertEqual(v["NABIDH_IRIS_PASSWORD"], "p#ss=w$rd ")       # export öneki, #, =, $ ve tırnak içi boşluk
        self.assertEqual(v["SPACED_KEY"], "spaced value")
        self.assertEqual(v["QUOTED"], "çift tırnak")
        self.assertEqual(v["MISMATCH"], "\"yarım'")                      # eşleşmeyen tırnak atılmaz
        self.assertEqual(v["EMPTY"], "")
        self.assertNotIn("bad key", v)
        self.assertNotIn("1BAD", v)
        self.assertEqual(len(v), 6)


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / ".env"
        self.file.write_text("ENVFILE_TEST_A=from_file\nENVFILE_TEST_B=from_file\n", encoding="utf-8")
        p = mock.patch.dict(os.environ, {"ENVFILE_TEST_B": "from_shell"})
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("ENVFILE_TEST_A", None)
        loaded = mock.patch.dict(envfile.LOADED, {"path": None, "keys": []})
        loaded.start()
        self.addCleanup(loaded.stop)

    def test_existing_environment_wins(self):
        self.assertEqual(envfile.load(self.file), ["ENVFILE_TEST_A"])
        self.assertEqual(os.environ["ENVFILE_TEST_A"], "from_file")
        self.assertEqual(os.environ["ENVFILE_TEST_B"], "from_shell")          # komut satırı / export kazanır
        self.assertEqual(envfile.LOADED, {"path": str(self.file), "keys": ["ENVFILE_TEST_A"]})

    def test_override(self):
        envfile.load(self.file, override=True)
        self.assertEqual(os.environ["ENVFILE_TEST_B"], "from_file")

    def test_missing_or_disabled(self):
        self.assertEqual(envfile.load(Path(self.tmp.name) / "yok"), [])
        for off in ("", "none", "NONE"):
            with mock.patch.dict(os.environ, {envfile.ENV_FILE_VAR: off}):
                self.assertIsNone(envfile.path())
                self.assertEqual(envfile.load(), [])
        with mock.patch.dict(os.environ, {envfile.ENV_FILE_VAR: str(self.file)}):
            self.assertEqual(envfile.path(), self.file)
        self.assertNotIn("ENVFILE_TEST_A", os.environ)

    def test_unreadable_file_warns(self):
        self.file.write_bytes(b"A=\xff\xfe\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(envfile.load(self.file), [])
        self.assertIn("UYARI", err.getvalue())

    def test_audit_records_key_names_not_values(self):
        self.file.write_text("ENVFILE_TEST_A=s3cret-value\n", encoding="utf-8")
        envfile.load(self.file)
        with temp_outputs():
            run = audit.Run("envfile_test")
            run.finish()
            manifest = (run.dir / "run_manifest.json").read_text(encoding="utf-8")
        self.assertEqual(run.record["env_file"], {"file": ".env", "keys": ["ENVFILE_TEST_A"]})
        self.assertNotIn("s3cret-value", manifest)


class TestRepo(unittest.TestCase):
    def test_env_is_git_ignored(self):
        r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, capture_output=True)
        if r.returncode == 128:
            self.skipTest("git deposu değil")
        self.assertEqual(r.returncode, 0, ".env .gitignore'da olmalı (şifre içerebilir)")

    def test_check_environment_prints_keys_only(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / ".env"
            f.write_text("SANDBOX_SOURCE=nabidh\nNABIDH_IRIS_PASSWORD=topsecret\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {envfile.ENV_FILE_VAR: str(f)}):
                res = ce.check_env_file()
        self.assertEqual(len(res), 1)                                         # repo dışı: git kontrolü yok
        self.assertIn("NABIDH_IRIS_PASSWORD, SANDBOX_SOURCE", res[0].detail)
        self.assertNotIn("topsecret", res[0].detail)
        with mock.patch.dict(os.environ, {envfile.ENV_FILE_VAR: "none"}):
            self.assertEqual(ce.check_env_file()[0].status, ce.INFO)


if __name__ == "__main__":
    unittest.main()
