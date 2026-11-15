#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check schema validation, timing arithmetic, report privacy, and CLI failures without hardware."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("report", ROOT / "tools/airport_throughput.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def snapshot(**changes):
    result = dict.fromkeys(report.FIELDS, 0)
    result.update(schema=2, sequence=1, session_ticks=100, snapshot_ticks=1000,
                  ns_per_billion_ticks=1000000000, bounce_sample_period=64,
                  gauge_state=4, gauge_running=1)
    result.update(changes)
    return result


def iperf():
    totals = {"seconds": 10, "bytes": 500000000, "bits_per_second": 400000000,
              "retransmits": 2, "address": "private-address"}
    return {"start": {"connected": ["private-address"]}, "server_output_text": "private-log",
            "end": {"sum_sent": totals.copy(), "sum_received": totals.copy()}}


class ReportTests(unittest.TestCase):
    def test_schema_matches_collector(self):
        header = (ROOT / "include/HAL/MtkPerf.hpp").read_text()
        self.assertEqual(set(re.findall(r"X\((\w+)\)", header)) | report.META, report.FIELDS)

    def test_registry_allowlist(self):
        tree = [{"serial-number": "private-serial", "IORegistryEntryChildren":
                 [{"MtkThroughput": snapshot(), "ssid": "private-network"}]}]
        self.assertEqual(report.extract_snapshot(tree), snapshot())
        self.assertNotIn("private", json.dumps(report.extract_snapshot(tree)))
        for invalid in ([], tree + tree, [{"MtkThroughput": snapshot(extra=1)}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                report.extract_snapshot(invalid)

    def test_invalid_snapshots(self):
        cases = [None, {}, snapshot(schema=1), snapshot(sequence=0), snapshot(session_ticks=0),
                 snapshot(snapshot_ticks=99), snapshot(ns_per_billion_ticks=0),
                 snapshot(bounce_sample_period=0)]
        cases += [snapshot(rx_desc=v) for v in (True, -1, 2**64, "1", 1.0, None)]
        missing = snapshot()
        del missing["tx_dma_drop"]
        cases.append(missing)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                report.validate_snapshot(value)

    def test_delta_timebase_gauges_and_lifetime_maximum(self):
        before = snapshot(ns_per_billion_ticks=2000000000, gauge_tx_free=32,
                          rx_bounce_sample_samples=4, rx_bounce_sample_ticks=100,
                          rx_bounce_sample_max_ticks=50)
        after = dict(before, sequence=2, snapshot_ticks=500001000, gauge_tx_free=3,
                     rx_bounce_sample_samples=6, rx_bounce_sample_ticks=300,
                     rx_bounce_sample_max_ticks=150, rx_bsd_bytes=50000000, gauge_ba_lost=2)
        result = report.delta(before, after)
        self.assertEqual(result["window_seconds"], 1)
        self.assertEqual(result["rx_bsd_mbps_over_window"], 400)
        self.assertEqual(result["counters"]["gauge_ba_lost"], 2)
        self.assertEqual(result["gauges"]["gauge_tx_free"], {"before": 32, "after": 3})
        self.assertEqual(result["timings"]["rx_bounce_sample"],
                         {"samples": 2, "total_ms": 0.0004, "mean_us": 0.2})
        self.assertEqual(result["lifetime_max_us"]["rx_bounce_sample_max_us"], 0.3)
        self.assertIsNone(result["timings"]["rx_dequeue"]["mean_us"])

    def test_delta_rejects_resets_and_configuration_changes(self):
        before = snapshot(rx_desc=10, rx_dequeue_max_ticks=10)
        after = dict(before, sequence=2, snapshot_ticks=2000)
        for change in ({"session_ticks": 101}, {"sequence": 1}, {"snapshot_ticks": 1000},
                       {"ns_per_billion_ticks": 2}, {"bounce_sample_period": 32},
                       {"rx_desc": 9}, {"rx_dequeue_max_ticks": 9}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                report.delta(before, dict(after, **change))

    def test_fresh_snapshot_waits_for_sequence(self):
        with patch.object(report, "read_snapshot", side_effect=[snapshot(), snapshot(), snapshot(sequence=2)]), \
                patch.object(report.time, "sleep"):
            self.assertEqual(report.fresh_snapshot()["sequence"], 2)
        with patch.object(report, "read_snapshot", return_value=snapshot()), \
                patch.object(report.time, "monotonic", side_effect=[0, 16]):
            with self.assertRaisesRegex(ValueError, "No fresh snapshot"):
                report.fresh_snapshot()
        with patch.object(report, "read_snapshot", side_effect=[snapshot(), snapshot(session_ticks=101)]), \
                patch.object(report.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "session changed"):
                report.fresh_snapshot()

    def test_iperf_sanitization_and_invalid_results(self):
        sanitized = report.summarize_iperf(iperf())
        self.assertEqual(sanitized["sum_received"]["bits_per_second"], 400000000)
        self.assertNotIn("private", json.dumps(sanitized))
        cases = [None, {"error": "private-message"}, {}, {"end": []}]
        for value in (None, True, -1, float("nan"), float("inf"), 2**1000, "private-message"):
            data = iperf()
            data["end"]["sum_received"]["bytes"] = value
            cases.append(data)
        data = iperf()
        data["end"]["sum_received"]["seconds"] = 0
        cases.append(data)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError) as error:
                report.summarize_iperf(data)
            self.assertNotIn("private", str(error.exception))

    def test_save_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            report.save(path, snapshot())
            with self.assertRaises(FileExistsError):
                report.save(path, {})
            self.assertEqual(json.loads(path.read_text()), snapshot())

    def run_cli(self, direction="down", failure=None):
        before, after = snapshot(), snapshot(sequence=2, snapshot_ticks=1000001000)
        if failure == "disconnected":
            after["gauge_running"] = 0
        proc = subprocess.CompletedProcess([], 1 if failure == "iperf" else 0,
                                            json.dumps(iperf()).encode(), b"private-message")
        argv = ["airport_throughput.py", "run", "--server", "private-server", "--direction", direction,
                "--seconds", "20", "--omit", "3", "--streams", "4"]
        output = io.StringIO()
        with patch("sys.argv", argv), patch.object(report, "check_loaded"), \
                patch.object(report, "fresh_snapshot", side_effect=[before, after]), \
                patch.object(report.shutil, "which", return_value="/mock/iperf3"), \
                patch.object(report.subprocess, "run", return_value=proc) as run, \
                patch.object(report, "save") as save, contextlib.redirect_stdout(output):
            if failure:
                with self.assertRaises(ValueError) as error:
                    report.main()
                self.assertNotIn("private", str(error.exception))
            else:
                report.main()
                command = run.call_args.args[0]
                self.assertEqual("-R" in command, direction == "down")
                self.assertEqual(command[3:9], ["-t", "20", "-P", "4", "-O", "3"])
                self.assertEqual(run.call_args.kwargs["timeout"], 43)
                self.assertIn("400.0 Mbit/s", output.getvalue())
            save.assert_not_called()
        self.assertNotIn("private", output.getvalue())

    def test_cli_directions_without_implicit_files(self):
        for direction in ("down", "up"):
            self.run_cli(direction)

    def test_cli_failures(self):
        for failure in ("iperf", "disconnected"):
            self.run_cli(failure=failure)


if __name__ == "__main__":
    unittest.main()
