"""`enclave.sh run all` and the audit KPI.
Claims: (1) `run all` runs ingest → nb0 → nb1 → kpi and no step's screen output falls between the COPY markers
(the screen stays inside the enclave; only the block is copied out); (2) the audit KPI does not count the enclave
run that is still running the KPI step as "open" (VM 2026-11-20: Audit Trail never reached 100%); (3) the block
shows SANDBOX_PARAMS in its header and which step run had a parameter override, so an exploration run (VM
2026-11-20 08:18 UTC NB1, example threshold) is told apart from a run with the configured PARAMS."""
import contextlib
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


# A step that writes one finished run folder: argv = outputs dir, run folder name, manifest JSON, graduation JSON
FAKE_STEP = """
import json, pathlib, sys
print("SCREEN-ONLY", " ".join(sys.argv[5:]))
d = pathlib.Path(sys.argv[1]) / sys.argv[2]
d.mkdir(parents=True)
(d / "run_manifest.json").write_text(sys.argv[3])
if sys.argv[4] != "null":
    (d / "kpi").mkdir()
    (d / "kpi" / "graduation.json").write_text(sys.argv[4])
"""
EXPLORE = {"qd_risk_threshold_pct": 5.6, "ethnicity_source": "ethnicity"}


class TestParamsInBlock(unittest.TestCase):
    def fake(self, out, manifests: dict, grad: dict | None = None):
        def step(name):
            run = f"20261120T081800Z_{enclave.STEPS[name][1]}_abc123"
            rec = {"status": "success", "outputs": [], **manifests.get(name, {"params_override": None})}
            return [sys.executable, "-c", FAKE_STEP, str(out), run, json.dumps(rec), json.dumps(grad if name == "kpi" else None)]
        return step

    def test_header_shows_sandbox_params(self):
        with temp_outputs() as out, mock.patch.dict(os.environ, {"SANDBOX_PARAMS": json.dumps(EXPLORE)}):
            rc, text = run_main(["run", "nb1", "--source", "nabidh_dryrun_iris"], self.fake(out, {
                "nb1": {"params_override": EXPLORE}}))
            saved = day_logs(out)[0].read_text(encoding="utf-8")
            _, again = run_main(["last"], enclave.step_command)
        header = screen_block(text).splitlines()[0]
        self.assertIn(' | SANDBOX_PARAMS {"qd_risk_threshold_pct": 5.6, "ethnicity_source": "ethnicity"} | 2026-', header)
        self.assertIn(header, saved)                                     # the day's file has the same header
        self.assertIn("Run: 20261120T081800Z_nb01_c1_c2_feasibility_abc123 · status: success · 0 outputs · "
                      'params override {"qd_risk_threshold_pct": 5.6, "ethnicity_source": "ethnicity"}', screen_block(text))
        self.assertIn("Already in", again)                               # `last` still finds the header's date

    def test_no_params_no_marker(self):
        with temp_outputs() as out, mock.patch.dict(os.environ, {"SANDBOX_PARAMS": ""}):
            rc, text = run_main(["run", "nb1", "--source", "nabidh_dryrun_iris"], self.fake(out, {}))
        block = screen_block(text)
        self.assertNotIn("SANDBOX_PARAMS", block.splitlines()[0])
        self.assertNotIn("params override", block)
        with mock.patch.dict(os.environ, {"SANDBOX_PARAMS": "{qd: 5"}):
            self.assertEqual(enclave.params_label(), "SANDBOX_PARAMS (not valid JSON) {qd: 5")
        with mock.patch.dict(os.environ, {"SANDBOX_PARAMS": "{}"}):
            self.assertEqual(enclave.params_label(), "")

    def test_kpi_lines_name_used_and_skipped_runs(self):
        nb01 = "20261120T081800Z_nb01_c1_c2_feasibility_abc123"
        grad = {"runs": {"nb00": "20261120T080000Z_nb00_data_profile_def456", "nb01": None, "nb02": None},
                "skipped_override_runs": {"nb01": [nb01]}, "override_inputs": {}}
        with temp_outputs() as out:
            rc, text = run_main(["run", "kpi", "--source", "nabidh_dryrun_iris"], self.fake(out, {}, grad))
        block = screen_block(text)
        self.assertIn("KPI inputs: nb00 20261120T080000Z_nb00_data_profile_def456 · "
                      "nb01 none (only runs with params override) · nb02 none", block)
        self.assertIn(f"Not used (parameter overrides, SANDBOX_PARAMS): nb01={nb01}", block)
        self.assertNotIn("--allow-overrides", text)

    def test_allow_overrides_passed_and_marked(self):
        nb01 = "20261120T081800Z_nb01_c1_c2_feasibility_abc123"
        used = {"nb01": {"run": nb01, "params_override": EXPLORE}}
        grad = {"runs": {"nb00": None, "nb01": nb01, "nb02": None}, "override_inputs": used}
        with temp_outputs() as out:
            rc, text = run_main(["run", "all", "--allow-overrides", "--source", "nabidh_dryrun_iris"],
                                self.fake(out, {"kpi": {"params_override": None, "override_inputs": used}}, grad))
        block = screen_block(text)
        self.assertIn("SCREEN-ONLY --allow-overrides", text[:text.index("COPY START")])    # only the kpi step gets it
        self.assertEqual(text.count("SCREEN-ONLY --allow-overrides"), 1)
        self.assertIn("Run: 20261120T081800Z_kpi_report_abc123 · status: success · 0 outputs · "
                      "KPI inputs with params override (--allow-overrides): nb01", block)
        self.assertIn("EXPLORATORY (--allow-overrides), not for the DFF report", block)


def run_main(argv, step_command) -> tuple[int, str]:
    buf = io.StringIO()
    with mock.patch.object(enclave, "step_command", step_command), contextlib.redirect_stdout(buf):
        rc = enclave.main(argv)
    return rc, buf.getvalue()


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
