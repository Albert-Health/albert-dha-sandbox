"""Closing a run left open in the audit log (decision D34).
Claims: (1) `audit.close_abandoned` only APPENDS a run_end "abandoned" event: every earlier line of the log stays
byte for byte; (2) the Audit Trail KPI then counts the run as closed (100%) and names it in its note, so the closure is
visible, not hidden; (3) it refuses without a reason, for an unknown id and for a run that already has a run_end;
(4) `enclave.sh audit-close` lists open runs without its own run and closes one in an audited command; (5) a run
ended by SIGTERM / SIGHUP (VM 2026-11-19: terminal closed) still writes run_end."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from sandbox import audit, kpi  # noqa: E402
from test_enclave import run_main, temp_outputs  # noqa: E402

OPEN = "20261119T054135Z_nb00_data_profile_b068d0"


def write_log(path: Path, events) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def sample_log(path: Path) -> None:
    write_log(path, [{"event": "run_start", "run_id": "a", "name": "nb00", "ts": "t0"},
                     {"event": "run_end", "run_id": "a", "status": "success"},
                     {"event": "run_start", "run_id": OPEN, "name": "nb00_data_profile", "ts": "2026-11-19T05:41:35+00:00"},
                     {"event": "output", "run_id": OPEN, "path": "x.csv"}])


class TestCloseAbandoned(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "audit_log.jsonl"
        sample_log(self.log)

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_only_and_kpi_reaches_100_with_a_note(self):
        before = self.log.read_bytes()
        self.assertEqual(kpi.audit_completeness(self.log)["pct"], 50.0)
        got = audit.close_abandoned(OPEN, "terminal closed before run_end", closed_by_run="closer", log=self.log)
        after = self.log.read_bytes()
        self.assertTrue(after.startswith(before))                         # nothing edited or deleted
        added = [json.loads(x) for x in after[len(before):].decode().splitlines()]
        self.assertEqual(len(added), 1)
        self.assertEqual((added[0]["event"], added[0]["run_id"], added[0]["status"], added[0]["closed_after_the_fact"],
                          added[0]["closed_by_run"], added[0]["n_outputs"]),
                         ("run_end", OPEN, "abandoned", True, "closer", 1))
        self.assertEqual(got["closed"]["reason"], "terminal closed before run_end")
        a = kpi.audit_completeness(self.log)
        self.assertEqual((a["pct"], a["open"], a["abandoned"]), (100.0, [], [OPEN]))
        row = kpi.build({}, {}, {}, {}, a).set_index("kpi").loc["Audit Trail Completeness"]
        self.assertEqual((row["actual"], row["met"]), ("100.0% (2/2 runs)", "Met"))
        self.assertIn(f"Closed after the fact as abandoned (run_end appended, D34): {OPEN}", row["notes"])

    def test_refuses_without_reason_unknown_or_closed(self):
        before = self.log.read_bytes()
        with self.assertRaises(ValueError):
            audit.close_abandoned(OPEN, "  ", closed_by_run=None, log=self.log)
        with self.assertRaisesRegex(LookupError, "no run_start"):
            audit.close_abandoned("nope", "x", closed_by_run=None, log=self.log)
        with self.assertRaisesRegex(LookupError, "already has a run_end"):
            audit.close_abandoned("a", "x", closed_by_run=None, log=self.log)
        self.assertEqual(self.log.read_bytes(), before)

    def test_open_runs(self):
        self.assertEqual(audit.open_runs(self.log),
                         [{"run_id": OPEN, "name": "nb00_data_profile", "ts": "2026-11-19T05:41:35+00:00", "n_outputs": 1}])


class TestAuditCloseCommand(unittest.TestCase):
    def test_list_then_close(self):
        with temp_outputs() as out:
            log = out / "audit" / "audit_log.jsonl"
            sample_log(log)
            rc, text = run_main(["audit-close"])
            self.assertEqual(rc, 0, text)
            self.assertIn("Open runs in the audit log (without this command's own run): 1", text)
            self.assertIn(OPEN, text)
            rc, text = run_main(["audit-close", OPEN])                    # no reason → refused, nothing appended
            self.assertEqual(rc, 1, text)
            self.assertIn("--reason is required", text)
            self.assertEqual(kpi.audit_completeness(log)["abandoned"], [])
            rc, text = run_main(["audit-close", OPEN, "--reason", "terminal closed before run_end"])
            self.assertEqual(rc, 0, text)
            self.assertIn(f"Closed as abandoned: {OPEN}", text)
            self.assertIn("Open runs left (without this command's own run): 0", text)
            a = kpi.audit_completeness(log)
            self.assertEqual((a["pct"], a["abandoned"]), (100.0, [OPEN]))  # the three audited commands closed too
            closers = [e for e in audit.read_log(log) if e.get("status") == "abandoned"]
            self.assertTrue(closers[0]["closed_by_run"].split("_", 1)[1].startswith("enclave_audit_close"))


@unittest.skipUnless(hasattr(signal, "SIGHUP"), "POSIX signals")
class TestTerminateWritesRunEnd(unittest.TestCase):
    def test_sigterm_and_sighup(self):
        for sig in ("SIGTERM", "SIGHUP"):
            with self.subTest(sig=sig), tempfile.TemporaryDirectory() as d:
                code = textwrap.dedent(f"""
                    import os, signal, sys
                    from pathlib import Path
                    sys.path.insert(0, {str(ROOT / 'src')!r})
                    from sandbox import audit
                    audit.OUTPUT_DIR = Path({d!r}); audit.AUDIT_DIR = Path({d!r}) / "audit"
                    run = audit.Run("probe")
                    os.kill(os.getpid(), signal.{sig})
                    import time; time.sleep(5)
                """)
                p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
                self.assertEqual(p.returncode, 128 + getattr(signal, sig), p.stderr)
                ends = [e for e in audit.read_log(Path(d) / "audit" / "audit_log.jsonl") if e["event"] == "run_end"]
                self.assertEqual([e["status"] for e in ends], ["failed_or_interrupted"])


if __name__ == "__main__":
    unittest.main()
