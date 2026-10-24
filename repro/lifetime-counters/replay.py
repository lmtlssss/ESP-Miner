#!/usr/bin/env python3
"""Compile unchanged lifetime counter functions with a controlled clock."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def function(source, name):
    start = re.search(r"^(?:void|double|uint64_t) " + name + r"\(", source, re.M).start()
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--ref", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.ref:
        source = subprocess.check_output(["git", "show", args.ref + ":main/system.c"], cwd=args.repo, text=True)
    else:
        source = (args.repo / "main/system.c").read_text()
    state_start = source.index("typedef struct\n{")
    state_end = source.index('static const char * TAG = "system";', state_start)
    state = source[state_start:state_end]
    constants = "\n".join(line for line in source.splitlines() if line.startswith(("#define NVS_COUNTER_UPDATE_INTERVAL_MS", "#define NOINIT_SENTINEL_VALUE")))
    selected = "\n\n".join(function(source, name) for name in (
        "SYSTEM_noinit_update", "SYSTEM_noinit_get_total_uptime_seconds",
        "SYSTEM_noinit_get_total_hashes", "SYSTEM_noinit_get_total_log2_work"))
    prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define __NOINIT_ATTR
#define BITS64 0x1.0p64
enum { NVS_CONFIG_TOTAL_UPTIME, NVS_CONFIG_CUMULATIVE_HASHES_HIGH, NVS_CONFIG_CUMULATIVE_HASHES_LOW };
typedef struct { float current_hashrate; int64_t start_time_us; uint64_t uptime_seconds; } SystemModule;
static int64_t clock_us;
static unsigned writes;
static uint64_t saved[3];
static int64_t esp_timer_get_time(void) { return clock_us; }
static void nvs_config_set_u64(int key, uint64_t value) { writes++; saved[key] = value; }
'''
    driver = r'''
static void reset_state(uint64_t low) {
    noinit_state = (NoinitState){.sentinel=NOINIT_SENTINEL_VALUE, .cumulative_hashes_low=low};
    last_update_time_ms = 0; last_nvs_write_time_ms = 0; total_uptime_at_system_start = 17;
    writes = 0; memset(saved, 0, sizeof(saved)); clock_us = 1000000;
}
static void scenario(const char *name, unsigned interval_a, unsigned interval_b, unsigned count, float rate, uint64_t low) {
    reset_state(low);
    SystemModule sys = {.current_hashrate=rate, .start_time_us=clock_us};
    SYSTEM_noinit_update(&sys);
    uint64_t elapsed_ms = 0;
    for (unsigned i=0; i<count; i++) {
        unsigned delta_ms = i % 2 ? interval_b : interval_a;
        elapsed_ms += delta_ms; clock_us += (int64_t)delta_ms * 1000;
        SYSTEM_noinit_update(&sys);
    }
    unsigned __int128 observed_integer = ((unsigned __int128)noinit_state.cumulative_hashes_high << 64) + noinit_state.cumulative_hashes_low - low;
    long double observed = (long double)observed_integer;
    long double expected = (long double)elapsed_ms * 1000000.L * rate;
    bool work_ok = fabsl(observed - expected) <= fmaxl(1.L, expected * 1e-12L);
    bool uptime_ok = sys.uptime_seconds == elapsed_ms / 1000;
    bool carry_ok = low == 0 || noinit_state.cumulative_hashes_high == 1;
    bool persist_ok = elapsed_ms < 3600000 || (writes == 3 && saved[0] == 3617 && saved[1] == noinit_state.cumulative_hashes_high && saved[2] == noinit_state.cumulative_hashes_low);
    printf("{\"scenario\":\"%s\",\"elapsed_ms\":%llu,\"observed_hashes\":%.0Lf,\"expected_hashes\":%.0Lf,\"uptime_seconds\":%llu,\"expected_uptime_seconds\":%llu,\"nvs_writes\":%u,\"pass\":%s}\n", name, (unsigned long long)elapsed_ms, observed, expected, (unsigned long long)sys.uptime_seconds, (unsigned long long)(elapsed_ms/1000), writes, work_ok && uptime_ok && carry_ok && persist_ok ? "true":"false");
}
int main(void) {
    scenario("regular_1000_ms", 1000, 1000, 60, 1000.f, 0);
    scenario("alternating_999_1001_ms", 999, 1001, 60, 1000.f, 0);
    scenario("regular_900_ms", 900, 900, 60, 1000.f, 0);
    scenario("alternating_900_1100_ms", 900, 1100, 60, 1000.f, 0);
    scenario("zero_rate", 999, 1001, 60, 0.f, 0);
    scenario("hourly_persistence", 999, 1001, 3600, 1000.f, 0);
    scenario("low_counter_carry", 1000, 1000, 1, 1000.f, UINT64_MAX-1000);
    return 0;
}
'''
    args.output.mkdir(parents=True, exist_ok=True)
    code = args.output / "selected_counter_replay.c"
    code.write_text(prefix + constants + "\n" + state + selected + driver)
    binary = args.output / "counter-replay"
    subprocess.run([os.environ.get("CC", "cc"), "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-fsanitize=undefined,float-cast-overflow", str(code), "-lm", "-o", str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True, check=True)
    if result.stderr:
        raise RuntimeError(result.stderr)
    traces = [json.loads(line) for line in result.stdout.splitlines()]
    output = {"source": str(args.repo.resolve()), "ref": args.ref or "working-tree", "boundary": "actual updater/getters; controlled monotonic clock and NVS", "scenarios": traces}
    (args.output / "results.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
