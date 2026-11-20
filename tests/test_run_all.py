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
from test_enclave import temp_outputs  # noqa: E402


class TestRunAll(unittest.TestCase):
    def test_screen_output_stays_outside_the_block(self):
        started = []

        def fake_step(step):
            started.append(step)
            return [sys.executable, "-c", f"print('SCREEN-ONLY {step} 3 patients')"]

        buf = io.StringIO()
        with temp_outputs(), mock.patch.object(enclave, "step_command", fake_step), contextlib.redirect_stdout(buf):
            rc = enclave.main(["run", "all", "--source", "nabidh_dryrun_iris"])
        text = buf.getvalue()
        self.assertEqual(started, list(enclave.RUN_ALL))
        self.assertEqual(text.count("COPY START"), 1)
        block = text[text.index("COPY START"):text.index("COPY END")]
        self.assertNotIn("SCREEN-ONLY", block)                        # step output only before the block
        self.assertIn("SCREEN-ONLY kpi", text[:text.index("COPY START")])
        for i, step in enumerate(enclave.RUN_ALL, 1):
            self.assertIn(f"### {i}/{len(enclave.RUN_ALL)} · run {step}", block)
        self.assertIn("run all · exit codes: ingest 0 · nb0 0 · nb1 0 · kpi 0", block)
        self.assertEqual(rc, 0)                                          # every step exited 0


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
