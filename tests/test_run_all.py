"""`enclave.sh run all` and the audit KPI.
Claims: (1) `run all` runs ingest → nb0 → nb1 → kpi and no step's screen output falls between the COPY markers
(the screen stays inside the enclave; only the block is copied out); (2) the audit KPI does not count the enclave
run that is still running the KPI step as "open" (VM 2026-11-20: Audit Trail never reached 100%)."""
import contextlib
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
from sandbox import kpi  # noqa: E402
from test_enclave import day_logs, screen_block, temp_outputs  # noqa: E402


class TestRunAll(unittest.TestCase):
    def test_screen_output_stays_outside_the_block(self):
        started = []

        def fake_step(step):
            started.append(step)
            return [sys.executable, "-c", f"print('SCREEN-ONLY {step} 3 patients')"]

        buf = io.StringIO()
        with temp_outputs() as out, mock.patch.object(enclave, "step_command", fake_step), \
                contextlib.redirect_stdout(buf):
            rc = enclave.main(["run", "all", "--source", "nabidh_dryrun_iris"])
            logs = day_logs(out)
            saved = logs[0].read_text(encoding="utf-8") if logs else ""
        text = buf.getvalue()
        self.assertEqual(len(logs), 1, logs)                              # the day's file: the block only
        self.assertEqual(saved, screen_block(text) + "\n")
        for screen in ("SCREEN-ONLY", "Running:", "===== run all", "stays inside the enclave; the summary"):
            self.assertIn(screen, text)
            self.assertNotIn(screen, saved)
        self.assertTrue(text.strip().splitlines()[-1].startswith("Saved to "))
        self.assertEqual(started, list(enclave.RUN_ALL))
        self.assertEqual(text.count("COPY START"), 1)
        block = text[text.index("COPY START"):text.index("COPY END")]
        self.assertNotIn("SCREEN-ONLY", block)                        # step output only before the block
        self.assertIn("SCREEN-ONLY kpi", text[:text.index("COPY START")])
        for i, step in enumerate(enclave.RUN_ALL, 1):
            self.assertIn(f"### {i}/{len(enclave.RUN_ALL)} · run {step}", block)
        self.assertIn("run all · exit codes: ingest 0 · nb0 0 · nb1 0 · kpi 0", block)
        self.assertEqual(rc, 0)                                          # every step exited 0

    def test_single_step_day_file_has_no_screen_output(self):
        buf = io.StringIO()
        fake = lambda step: [sys.executable, "-c", "print('SCREEN-ONLY nb1 3 patients')"]   # noqa: E731
        with temp_outputs() as out, mock.patch.object(enclave, "step_command", fake), \
                contextlib.redirect_stdout(buf):
            enclave.main(["run", "nb1", "--source", "nabidh_dryrun_iris"])
            saved = day_logs(out)[0].read_text(encoding="utf-8")
            step_log = next(out.glob("*_enclave_run_*/enclave/nb1.log")).read_text(encoding="utf-8")
        text = buf.getvalue()
        self.assertIn("SCREEN-ONLY", step_log)                           # the full screen output stays in outputs/
        self.assertEqual(saved, screen_block(text) + "\n")
        self.assertNotIn("SCREEN-ONLY", saved)
        self.assertNotIn("Running:", saved)
        self.assertIn("enclave/nb1.log", saved)                          # the block names the screen log, not its text


class TestAuditRunning(unittest.TestCase):
    def test_running_parent_is_not_open(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "audit_log.jsonl"
            ev = [{"event": "run_start", "run_id": r} for r in ("a", "b", "parent")] + \
                 [{"event": "run_end", "run_id": r} for r in ("a", "b")]
            log.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
            self.assertEqual(kpi.audit_completeness(log)["open"], ["parent"])
            got = kpi.audit_completeness(log, running=["parent"])
            self.assertEqual((got["runs"], got["closed"], got["pct"], got["open"]), (2, 2, 100.0, []))


if __name__ == "__main__":
    unittest.main()
