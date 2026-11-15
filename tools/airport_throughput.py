#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read throughput snapshots or run a TCP test with before/after diagnostics.

Build AirportMtkWlan with MTK_PERF=1 and load that build first. Python 3 is
required; the run command also needs iperf3 and a reachable iperf3 server.
Only numeric counters and selected TCP totals are exported. Timer values are
elapsed time, may overlap, and do not represent independent CPU usage.
"""

import argparse
import json
import math
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

SCHEMA = 2
META = {"schema", "sequence", "session_ticks", "snapshot_ticks",
        "ns_per_billion_ticks", "bounce_sample_period"}
GAUGES = {"gauge_state", "gauge_running", "gauge_tx_free", "gauge_txwi_free",
          "gauge_tx_oactive", "gauge_amsdu_pending"}
# Explicit schema allowlist: never export unrelated IORegistry properties.
FIELDS = META | set("""
rx_desc rx_desc_bytes rx_records rx_record_bytes rx_partial_drop rx_normal rx_normal_bytes
rx_fill_drop rx_mpdu rx_mpdu_bytes rx_amsdu_sub rx_amsdu_sub_bytes rx_amsdu_flush
rx_amsdu_alloc_fail rx_amsdu_chain rx_amsdu_copy_fail rx_amsdu_timer_flush
rx_amsdu_timer_fail rx_amsdu_cross_batch_complete rx_amsdu_purge_sub rx_budget_more
rx_refill_fail rx_bsd_packets rx_bsd_bytes rx_bsd_return_packets rx_bsd_flush_return
rx_normalize_copy rx_normalize_drop tx_pull_packets tx_pull_bytes tx_enqueue_ok
tx_enqueue_drop tx_dma_ok tx_dma_drop tx_dma_bytes tx_wtbl_ba_enable_submit
tx_wtbl_ba_disable_submit tx_wtbl_ba_submit_fail tx_sta_ba_submit_fail
gauge_tx_ba_agreements bounce_rx_calls bounce_rx_bytes bounce_tx_calls bounce_tx_bytes
watchdog_busy gauge_state gauge_running gauge_tx_full gauge_tx_free gauge_txwi_free
tx_full_token tx_full_ring tx_wake_below_threshold tx_pause_abort tx_pause_samples
tx_pause_ticks tx_pause_max_ticks gauge_tx_oactive gauge_ba_gap_timeout gauge_ba_lost
gauge_ba_below gauge_ba_above gauge_tooshort gauge_decap gauge_nombuf gauge_rx_fill_fail
gauge_amsdu_pending rx_dequeue_samples rx_dequeue_ticks rx_dequeue_max_ticks
rx_refill_samples rx_refill_ticks rx_refill_max_ticks rx_process_samples rx_process_ticks
rx_process_max_ticks rx_if_input_samples rx_if_input_ticks rx_if_input_max_ticks
rx_bsd_flush_samples rx_bsd_flush_ticks rx_bsd_flush_max_ticks tx_start_samples
tx_start_ticks tx_start_max_ticks tx_gated_samples tx_gated_ticks tx_gated_max_ticks
tx_gate_wait_samples tx_gate_wait_ticks tx_gate_wait_max_ticks rx_bounce_sample_samples
rx_bounce_sample_ticks rx_bounce_sample_max_ticks rx_intr_samples rx_intr_ticks
rx_intr_max_ticks
""".split())


def validate_snapshot(result):
    if not isinstance(result, dict) or result.get("schema") != SCHEMA:
        raise ValueError("Unsupported MtkThroughput schema; load a matching MTK_PERF=1 build")
    if result.keys() != FIELDS:
        raise ValueError("Unexpected or missing MtkThroughput fields")
    if any(type(v) is not int or not 0 <= v < 2**64 for v in result.values()):
        raise ValueError("Invalid diagnostic field type or range")
    if (not result["sequence"] or not result["session_ticks"]
            or result["snapshot_ticks"] < result["session_ticks"]
            or not result["ns_per_billion_ticks"] or not result["bounce_sample_period"]):
        raise ValueError("Invalid snapshot metadata")
    return result


def extract_snapshot(tree):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "MtkThroughput" in node:
                found.append(node["MtkThroughput"])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(tree)
    if len(found) != 1:
        raise ValueError("Expected one MtkThroughput property; load an MTK_PERF=1 AirportMtkWlan build")
    return validate_snapshot(found[0])


def read_snapshot():
    # Parse the registry in memory; only the allowlisted numeric snapshot leaves it.
    raw = subprocess.check_output(["ioreg", "-a", "-r", "-c", "IOPCIDevice"], timeout=10)
    return extract_snapshot(plistlib.loads(raw))


def fresh_snapshot(timeout=15):
    previous = read_snapshot()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.25)
        current = read_snapshot()
        if current["session_ticks"] != previous["session_ticks"]:
            raise ValueError("Driver session changed while waiting for a snapshot")
        if current["sequence"] > previous["sequence"]:
            return current
    raise ValueError("No fresh snapshot; the main workloop may be busy or the interface stopped")


def delta(before, after):
    validate_snapshot(before)
    validate_snapshot(after)
    for name in META - {"sequence", "snapshot_ticks"}:
        if before[name] != after[name]:
            raise ValueError("Snapshots belong to different sessions or configurations")
    ticks = after["snapshot_ticks"] - before["snapshot_ticks"]
    if ticks <= 0 or after["sequence"] <= before["sequence"]:
        raise ValueError("Snapshot did not advance or the driver restarted")
    scale = after["ns_per_billion_ticks"] / 1e9
    seconds = ticks * scale / 1e9
    counters, gauges, maxima = {}, {}, {}
    for name in sorted(FIELDS - META):
        if name in GAUGES:
            gauges[name] = {"before": before[name], "after": after[name]}
        elif name.endswith("_max_ticks"):
            if after[name] < before[name]:
                raise ValueError("Timing maximum decreased; counters may have reset")
            maxima[name[:-6] + "_us"] = after[name] * scale / 1000
        else:
            value = after[name] - before[name]
            if value < 0:
                raise ValueError("Counter decreased; reset or wrap detected: " + name)
            counters[name] = value
    timings = {}
    for name, value in counters.items():
        if name.endswith("_ticks"):
            prefix = name[:-6]
            samples = counters.get(prefix + "_samples", 0)
            timings[prefix] = {"samples": samples, "total_ms": value * scale / 1e6,
                               "mean_us": value * scale / (1000 * samples) if samples else None}
    return {"window_seconds": seconds, "counters": counters, "gauges": gauges,
            "timings": timings, "lifetime_max_us": maxima,
            "rx_bsd_mbps_over_window": counters["rx_bsd_bytes"] * 8 / seconds / 1e6}


def summarize_iperf(result):
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("iperf3 reported an error; no valid throughput result")
    end = result.get("end", {})
    if not isinstance(end, dict):
        raise ValueError("Missing iperf3 TCP totals")
    sanitized = {}
    for side in ("sum_sent", "sum_received"):
        data = end.get(side)
        if not isinstance(data, dict):
            raise ValueError("Missing iperf3 TCP totals")
        sanitized[side] = {key: data[key] for key in
                           ("seconds", "bytes", "bits_per_second", "retransmits") if key in data}
        if not {"seconds", "bytes", "bits_per_second"} <= sanitized[side].keys():
            raise ValueError("Incomplete iperf3 TCP totals")
        if any(type(v) not in (int, float) or not 0 <= v < 2**64 or not math.isfinite(v)
               for v in sanitized[side].values()):
            raise ValueError("Invalid iperf3 numeric totals")
        if not sanitized[side]["seconds"]:
            raise ValueError("Empty iperf3 measurement interval")
    return sanitized


def check_loaded():
    loaded = subprocess.check_output(["kmutil", "showloaded", "--list-only"],
                                     stderr=subprocess.DEVNULL, text=True, timeout=15)
    if "com.flxxxxddd.AirportMtkWlan" not in loaded:
        raise ValueError("AirportMtkWlan is not loaded")


def save(path, value):
    # Explicit destinations only; never overwrite an existing report.
    with path.open("x") as stream:
        json.dump(value, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    snap = sub.add_parser("snapshot", help="read a fresh numeric snapshot")
    snap.add_argument("--output", type=Path, help="optionally save a numeric JSON snapshot")
    run = sub.add_parser("run", help="run one TCP test and report diagnostic deltas")
    run.add_argument("--server", required=True, help="iperf3 server; omitted from reports")
    run.add_argument("--direction", choices=("up", "down"), default="down")
    run.add_argument("--seconds", type=int, choices=range(5, 301), default=10, metavar="5..300")
    run.add_argument("--streams", type=int, choices=range(1, 17), default=1, metavar="1..16")
    run.add_argument("--omit", type=int, choices=range(0, 61), default=0, metavar="0..60",
                     help="warm-up seconds excluded from iperf3 totals (default: 0)")
    run.add_argument("--output", type=Path, help="optionally save a numeric JSON report")
    args = parser.parse_args()
    check_loaded()
    before = fresh_snapshot()
    if args.action == "snapshot":
        if args.output:
            save(args.output, before)
        else:
            for key, value in sorted(before.items()):
                print(f"{key}: {value}")
    else:
        if before["gauge_state"] != 4 or not before["gauge_running"]:
            raise ValueError("The Wi-Fi interface must be connected and running before a test")
        iperf = shutil.which("iperf3")
        if not iperf:
            raise ValueError("iperf3 was not found")
        command = [iperf, "-c", args.server, "-t", str(args.seconds), "-P", str(args.streams),
                   "-O", str(args.omit), "-J"]
        if args.direction == "down":
            command.append("-R")
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=args.seconds + args.omit + 20)
        if proc.returncode:
            raise ValueError("iperf3 failed; no valid throughput result")
        summary = summarize_iperf(json.loads(proc.stdout))
        after = fresh_snapshot()
        report = {"schema": SCHEMA, "direction": args.direction, "streams": args.streams,
                  "seconds": args.seconds, "omit_seconds": args.omit, "iperf": summary,
                  "before": before, "after": after, "delta": delta(before, after)}
        if after["gauge_state"] != 4 or not after["gauge_running"]:
            raise ValueError("The Wi-Fi interface stopped or disconnected during the test")
        if args.output:
            save(args.output, report)
        print("TCP receiver: %.1f Mbit/s" % (summary["sum_received"]["bits_per_second"] / 1e6))
        timings = report["delta"]["timings"]
        bounce_mean = timings.get("rx_bounce_sample", {}).get("mean_us")
        if bounce_mean is not None:
            print("Sampled RX bounce copy mean: %.3f us" % bounce_mean)
        counters = report["delta"]["counters"]
        for key in ("gauge_ba_lost", "gauge_tooshort", "rx_amsdu_chain", "rx_amsdu_copy_fail",
                    "rx_refill_fail", "tx_dma_drop", "tx_full_ring", "tx_full_token"):
            print(f"{key} delta: {counters[key]}")
    if args.output:
        print(args.output.resolve())


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        # Never print the server argument, a failed command line, or raw server output.
        print("Error: " + str(error) if isinstance(error, ValueError)
              else "Error: system command or file operation failed")
        raise SystemExit(1)
