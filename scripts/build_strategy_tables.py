#!/usr/bin/env python3
"""Build exact-enumeration subset data and solve ongoing classic Ultimate X.

Host-only reproducible tool. A pilot never emits a usable bias/strategy table.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ["royal_flush", "straight_flush", "four_aces_kicker", "four_234_kicker",
              "four_aces", "four_234", "four_5k", "full_house", "flush", "straight",
              "three_kind", "two_pair", "high_pair", "nothing"]
PAYOUTS = [800,50,400,160,160,80,50,9,6,4,3,1,1,0]
MULTIPLIERS = [4,4,4,4,4,4,3,12,10,8,4,3,2,1]
SECTIONS = [
    {"subset_size":0,"offset":64,"rows":1,"width":4},
    {"subset_size":1,"offset":120,"rows":52,"width":4},
    {"subset_size":2,"offset":3032,"rows":1326,"width":2},
    {"subset_size":3,"offset":40160,"rows":22100,"width":2},
    {"subset_size":4,"offset":658960,"rows":270725,"width":1},
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"validation/strategy-research/generated")
    parser.add_argument("--subsets-only", action="store_true")
    parser.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 2)//2))
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument("--pilot", type=int, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    build = ROOT/"validation/strategy-research/bin"
    build.mkdir(parents=True, exist_ok=True)
    binary = build/"strategy_tables"
    source = ROOT/"native/strategy_tables.cpp"
    subprocess.run(["clang++", "-O3", "-std=c++17", "-pthread", "-Wall", "-Wextra", str(source), "-o", str(binary)], check=True)
    command = [str(binary), "--output", str(args.output), "--threads", str(args.threads),
               "--max-iterations", str(args.max_iterations), "--tolerance", str(args.tolerance)]
    if args.subsets_only:
        command.append("--subsets-only")
    if args.pilot:
        command += ["--pilot", str(args.pilot)]
    subprocess.run(command, check=True)
    if args.pilot:
        return
    subset = args.output/"subset_counts.dat"
    raw = subset.read_bytes()
    if len(raw) != 4449110 or raw[:8] != b"UXSUB01\0":
        raise RuntimeError("unexpected subset data format")
    result = {
        "schema":1, "table_sha256":hashlib.sha256(raw).hexdigest(), "table_bytes":len(raw), "category_order":CATEGORIES, "multiplier_order":MULTIPLIERS,
        "payouts":PAYOUTS, "card_encoding":"card=13*suit+rank-2; suits C,D,H,S; ranks2..14",
        "file":{"name":subset.name,"sha256":hashlib.sha256(raw).hexdigest(),"size":len(raw)},
        "subset_format":{"magic":"UXSUB01","version":1,"header_bytes":64,
                         "byte_order":"little","ranking":"colex sum C(card_i,i+1)","sections":SECTIONS},
        "method":"Exact category counts; tenfold multiplier convolution; average-reward relative value iteration",
        "sources":["https://www.playperfectllc.com/_files/ugd/d82604_9bbe3fae897f4b5791b730fa4acb09a2.pdf",
                   "https://wizardofodds.com/games/video-poker/tables/ultimate-x/"],
        "certification":{"probabilities":"enumerated integer counts, not sampling",
                         "arithmetic":"IEEE754 double precision",
                         "claim":"Numerically converged multiplier-aware long-run expected-value policy; ties within1e-9 credits use more held cards then lower hold mask",
                         "expected_return_reference_rounded":0.998663},
    }
    bias = args.output/"bias.json"
    if not args.subsets_only:
        result["bias"] = json.loads(bias.read_text())
        result["certification"]["average_gain_loss_bound_credits_per_round"] = result["bias"]["bellman_span"] + 1e-9
    target = args.output/"strategy.json"
    target.write_text(json.dumps(result, indent=2)+"\n")
    print(f"Metadata written: {target}", flush=True)

if __name__ == "__main__":
    main()
