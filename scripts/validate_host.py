#!/usr/bin/env python3
"""Run reproducible host checks and record source-bound full-flow evidence."""
import hashlib
import argparse
from datetime import date
import importlib
import json
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def payload_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "payload/opt/dino").glob("*.py"))}


def payload_file_hashes():
    result = {}
    for path in sorted((ROOT/"payload").rglob("*")):
        if path.is_symlink():
            raise ValueError("Unexpected symlink in runtime inventory")
        if path.is_file():
            result[path.relative_to(ROOT/"payload").as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deterministic-only', action='store_true',
                        help='Run functional checks only; explicitly leaves wall-clock input timing unqualified')
    args = parser.parse_args()
    checked_date = date.today().isoformat()
    before = payload_hashes()
    files_before = payload_file_hashes()
    started = time.monotonic()
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    if args.deterministic_only:
        def functional_tests(group):
            for test in group:
                if isinstance(test, unittest.TestSuite):
                    yield from functional_tests(test)
                elif not test.id().startswith('test_input_latency.'):
                    yield test
        suite = unittest.TestSuite(functional_tests(suite))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    after = payload_hashes()
    files_after = payload_file_hashes()
    unchanged = before == after and files_before == files_after
    passed = result.wasSuccessful() and unchanged and not result.skipped
    report = {"schema": 4, "date": checked_date, "version": "0.4.8",
              "mode": "functional-host-only" if args.deterministic_only else "full-including-wall-clock-input",
              "wall_clock_input_qualified": passed and not args.deterministic_only,
              "status": "PASS" if passed else "FAIL", "tests_run": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "payload_unchanged_during_checks": unchanged,
              "duration_seconds": round(time.monotonic()-started, 3),
              "host_python": platform.python_version(), "payload_sha256": after,
              "payload_files_sha256": files_after,
              "physical_hardware_tested": False, "SD_written": False}
    (ROOT / "validation/tests.json").write_text(json.dumps(report, indent=2) + "\n")
    flow = importlib.import_module("test_full_flow")
    runtime_ui = importlib.import_module("test_runtime_ui")
    flow_report = {
        "schema": 3, "date": checked_date, "version": "0.4.8",
        "status": report["status"],
        "tests_run": (unittest.defaultTestLoader.loadTestsFromModule(flow).countTestCases()
                      + unittest.defaultTestLoader.loadTestsFromModule(runtime_ui).countTestCases()),
        "test_files": ["tests/test_full_flow.py", "tests/test_runtime_ui.py"],
        "scope": "Real Session, PokerUI and launcher with injected monotonic clock, GPIO traces, LCD frame sink and signer callback; nonblocking animations, menu/animation gesture, credit arithmetic and animation skip tested",
        "scenarios": flow.OBSERVATIONS,
        "additional_scenarios": [
            "animation skip plus held Deal cannot double-spend",
            "signer gesture completes during artificial10sanimation",
            "paytable menu does not block signer gesture",
            "short chord has no card-hold or control-focus side effects",
            "production entropy wait and retry preserve all state and do not block signer gesture"],
        "payload_sha256": after, "payload_unchanged_during_checks": unchanged,
        "payload_files_sha256": files_after,
        "physical_device_or_sd_card_written": False,
        "actual_upstream_seedsigner_started": False,
        "hardware_gpio_or_spi_exercised": False}
    (ROOT / "validation/full-flow.json").write_text(json.dumps(flow_report, indent=2) + "\n")
    latency = importlib.import_module("test_input_latency")
    latency_report = {
        "schema": 1, "date": checked_date, "version": "0.4.8",
        "status": "NOT_RUN_HOST_CONTENTION" if args.deterministic_only else report["status"],
        "scope": "Production input sampler with real wall-clock short taps during blocked rendering/display work; fake GPIO and LCD, no physical device latency claim",
        "test_file": "tests/test_input_latency.py",
        "tests_run": 0 if args.deterministic_only else unittest.defaultTestLoader.loadTestsFromModule(latency).countTestCases(),
        "prior_full_run_report": "input-latency-sampled-full-run.json",
        "prior_isolated_recheck_report": "input-latency-isolated-v040.json",
        "timing_guard_or_assertions_weakened": False,
        "scenarios": latency.OBSERVATIONS,
        "payload_files_sha256": files_after,
        "physical_hardware_tested": False,
        "SD_written": False,
    }
    (ROOT / "validation/input-latency.json").write_text(json.dumps(latency_report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
