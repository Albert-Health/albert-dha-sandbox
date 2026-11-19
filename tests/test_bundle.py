"""tools/build_bundle.py: the one-file bundle for a VM without `git pull`.

Main claims: the bundle runs its own (embedded) code, not the repo's files, and gives the same canonical output as
the repo's ingest; a copy that lost or changed a line is refused; the audit names the bundle."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_bundle  # noqa: E402
from sandbox.audit import sha256_file  # noqa: E402
from sandbox.io import iris, schema  # noqa: E402
from sandbox.io.adapters import nabidh  # noqa: E402
from test_nabidh_adapter import write_raw  # noqa: E402
from test_nabidh_iris import raw_tables  # noqa: E402

DDC = "src/sandbox/reference/ddc.csv.gz"


class BundleCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text, cls.meta = build_bundle.build(["ingest"], allow_dirty=True)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "repo"                # stands in for the VM repo: no code, only the DDC reference
        (self.root / DDC).parent.mkdir(parents=True)
        shutil.copy(ROOT / DDC, self.root / DDC)
        self.bundle = self.root / "ingest_bundle.py"
        self.bundle.write_text(self.text, encoding="utf-8")

    def run_bundle(self, *args) -> tuple[int, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SANDBOX_")}
        p = subprocess.run([sys.executable, str(self.bundle), *args], cwd=self.root, env=env, capture_output=True,
                           text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr


class TestBuild(BundleCase):
    def test_closure(self):
        files = set(self.meta["files"])
        for rel in ("tools/enclave.py", "tools/ingest_nabidh.py", "tools/check_environment.py",
                    "src/sandbox/__init__.py", "src/sandbox/io/adapters/nabidh.py", "src/sandbox/io/adapters/ddc.py",
                    "src/sandbox/io/adapters/synthetic.py", "src/sandbox/io/iris.py", "src/sandbox/codelists.py"):
            self.assertIn(rel, files)
        self.assertFalse(any(f.startswith(("notebooks/", "src/sandbox/scores/")) for f in files), files)
        self.assertNotIn("src/sandbox/metrics.py", files)

    def test_ascii_and_deterministic(self):
        self.assertTrue(self.text.isascii())
        self.assertEqual(build_bundle.build(["ingest"], allow_dirty=True)[0], self.text)

    def test_info(self):
        rc, out = self.run_bundle("bundle-info")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"Bundle {self.meta['payload_sha256'][:12]}", out)
        self.assertIn("File check: OK", out)
        self.assertIn("tools/ingest_nabidh.py", out)
        self.assertIn("not in the repo", out)

    def test_editor_line_endings_and_trailing_spaces_accepted(self):
        self.bundle.write_bytes(("\r\n".join(ln + "  " for ln in self.text.splitlines()) + "\r\n\r\n").encode())
        rc, out = self.run_bundle("bundle-info")
        self.assertEqual(rc, 0, out)

    def test_changed_copy_refused(self):
        lines = self.text.splitlines()
        i = lines.index(build_bundle.PAYLOAD_MARK) + 5
        lines[i] = lines[i][:10] + ("A" if lines[i][10] != "A" else "B") + lines[i][11:]
        self.bundle.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc, out = self.run_bundle("bundle-info")
        self.assertEqual(rc, 2, out)
        self.assertIn("changed while copying", out)

    def test_truncated_copy_refused(self):
        self.bundle.write_text("\n".join(self.text.splitlines()[:-40]) + "\n", encoding="utf-8")
        rc, out = self.run_bundle("bundle-info")
        self.assertEqual(rc, 2, out)
        self.assertIn("incomplete", out)

    def test_missing_reference_and_unknown_step(self):
        (self.root / DDC).unlink()
        rc, out = self.run_bundle("run", "ingest", "--iris-sqlite", str(self.tmp), "--cohorts", "c1")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("ddc.csv.gz is missing", out)
        rc, out = self.run_bundle("run", "nb1")
        self.assertNotEqual(rc, 0, out)
        self.assertIn("not in this bundle", out)


class TestIngest(BundleCase):
    def test_same_canonical_output_as_the_repo(self):
        raw = self.tmp / "raw"
        raw.mkdir()
        write_raw(raw)
        iris_dir = self.tmp / "iris"
        iris_dir.mkdir()
        iris.write_sqlite_standin(iris_dir / "c1.sqlite", raw_tables(raw))

        rc, out = self.run_bundle("run", "ingest", "--iris-sqlite", str(iris_dir), "--cohorts", "c1",
                                  "--source", "bt")

        conn = iris.sqlite_standin({nabidh.IRIS_COHORTS["c1"]["schema"]: iris_dir / "c1.sqlite"})
        self.addCleanup(conn.close)
        ds, _ = nabidh.load_iris(conn, "c1")
        ds.source = "bt"
        want = schema.write_dataset(ds, self.tmp / "expected")
        val = schema.validate(schema.read_dataset(self.tmp / "expected", "bt", "c1"))
        self.assertEqual(rc, 1 if (val["severity"] == "ERROR").any() else 0, out)    # the fixture has an ERROR row
        self.assertIn(f"bundle {self.meta['payload_sha256'][:12]}", out)       # COPY START header
        self.assertIn("COPY END", out)
        got = self.root / "data" / "canonical" / "bt" / "c1"
        names = sorted(p.name for p in want.glob("*.csv"))
        self.assertEqual(names, sorted(p.name for p in got.glob("*.csv")))
        for n in names:
            self.assertEqual((want / n).read_bytes(), (got / n).read_bytes(), n)
        self.assertEqual(json.loads((got / "ingest.json").read_text())["ingest_version"], nabidh.INGEST_VERSION)

        manifest = next((self.root / "outputs").glob("*_ingest_nabidh_*/run_manifest.json"))
        m = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(m["status"], "success" if rc == 0 else "schema_errors")
        self.assertEqual(m["code"]["bundle"]["payload_sha256"], self.meta["payload_sha256"])
        self.assertEqual(m["code"]["files"]["src/sandbox/io/adapters/nabidh.py"],
                         sha256_file(ROOT / "src/sandbox/io/adapters/nabidh.py"))


if __name__ == "__main__":
    unittest.main()
