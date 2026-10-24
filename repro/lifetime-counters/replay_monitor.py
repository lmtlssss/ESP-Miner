#!/usr/bin/env python3
"""Replay the real monitor task and counter updater with controlled RTOS calls."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from replay import function


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--ref')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()

    def source(path):
        if a.ref:
            return subprocess.check_output(['git', 'show', a.ref + ':' + path], cwd=a.repo, text=True)
        return (a.repo / path).read_text()

    system = source('main/system.c')
    monitor = source('main/tasks/hashrate_monitor_task.c')
    monitor = '\n'.join(l for l in monitor.splitlines() if not l.startswith('#include'))
    counter_start = system.index('typedef struct\n{')
    counter_end = system.index('static const char * TAG = "system";', counter_start)
    constants = '\n'.join(l for l in system.splitlines() if l.startswith(('#define NVS_COUNTER_UPDATE_INTERVAL_MS', '#define NOINIT_SENTINEL_VALUE')))
    counter = constants + '\n' + system[counter_start:counter_end] + function(system, 'SYSTEM_noinit_update')
    prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>
#include <setjmp.h>
#include <inttypes.h>
#define __NOINIT_ATTR
#define MALLOC_CAP_SPIRAM 0
#define portTICK_PERIOD_MS 1
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define isnanf isnan
enum { NVS_CONFIG_TOTAL_UPTIME, NVS_CONFIG_CUMULATIVE_HASHES_HIGH, NVS_CONFIG_CUMULATIVE_HASHES_LOW };
typedef unsigned TickType_t;
typedef enum { REGISTER_INVALID, REGISTER_HASHRATE, REGISTER_TOTAL_COUNT, REGISTER_DOMAIN_0_COUNT, REGISTER_DOMAIN_1_COUNT, REGISTER_DOMAIN_2_COUNT, REGISTER_DOMAIN_3_COUNT, REGISTER_DOMAIN_4_COUNT, REGISTER_DOMAIN_5_COUNT, REGISTER_DOMAIN_6_COUNT, REGISTER_DOMAIN_7_COUNT, REGISTER_ERROR_COUNT, REGISTER_PLL_PARAM } register_type_t;
typedef struct { uint32_t value; uint64_t time_us; float hashrate; } measurement_t;
typedef struct { measurement_t *total_measurement; measurement_t **domain_measurements; measurement_t *error_measurement; pthread_mutex_t lock; bool is_initialized; } HashrateMonitorModule;
typedef struct { float current_hashrate, error_percentage, hashrate_1m, hashrate_10m, hashrate_1h; uint64_t uptime_seconds; int64_t start_time_us; } SystemModule;
typedef struct { struct { struct { int asic_count; struct { int hash_domains; } asic; } family; } DEVICE_CONFIG; bool ASIC_initalized; HashrateMonitorModule HASHRATE_MONITOR_MODULE; SystemModule SYSTEM_MODULE; } GlobalState;
static jmp_buf finished;
static int64_t clock_us = 1000000;
static unsigned polls, jitter_ms;
static uint64_t first_sample_us;
static float rate;
static int64_t esp_timer_get_time(void) { return clock_us; }
static void nvs_config_set_u64(int key, uint64_t value) { (void)key; (void)value; }
static void *heap_caps_malloc(size_t size, int caps) { (void)caps; return malloc(size); }
static TickType_t xTaskGetTickCount(void) { return clock_us / 1000; }
static void vTaskDelay(TickType_t ticks) { clock_us += (int64_t)(ticks + ((polls % 2) ? jitter_ms : 0)) * 1000; }
static void vTaskDelayUntil(TickType_t *wake, TickType_t interval) {
    if (polls++ == 0) first_sample_us = clock_us;
    if (polls == 61) longjmp(finished, 1);
    *wake += interval; clock_us = (int64_t)*wake * 1000;
}
static void ASIC_read_registers(GlobalState *g) { g->HASHRATE_MONITOR_MODULE.total_measurement[0].hashrate = rate; }
'''
    conversion = '\n'.join(l for l in source('components/asic/bm_hashrate.c').splitlines() if not l.startswith('#include'))
    driver = r'''
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    jitter_ms = strtoul(argv[1], NULL, 10); rate = strtof(argv[2], NULL);
    static GlobalState g;
    g.DEVICE_CONFIG.family.asic_count = 1; g.DEVICE_CONFIG.family.asic.hash_domains = 4;
    g.ASIC_initalized = true; g.SYSTEM_MODULE.start_time_us = clock_us;
    if (setjmp(finished) == 0) hashrate_monitor_task(&g);
    uint64_t elapsed_us = clock_us - first_sample_us;
    uint64_t pending_ms = clock_us / 1000 - last_update_time_ms;
    uint64_t expected = (uint64_t)((long double)(elapsed_us - pending_ms * 1000) * 1000.L * rate);
    printf("{\"task_polls\":%u,\"jitter_ms\":%u,\"rate_ghs\":%.0f,\"elapsed_ms\":%llu,\"pending_ms\":%llu,\"observed_hashes\":%llu,\"expected_committed_hashes\":%llu,\"pass\":%s}\n", polls, jitter_ms, rate, (unsigned long long)(elapsed_us/1000), (unsigned long long)pending_ms, (unsigned long long)noinit_state.cumulative_hashes_low, (unsigned long long)expected, pending_ms < 1000 && noinit_state.cumulative_hashes_low == expected ? "true":"false");
    HashrateMonitorModule *m = &g.HASHRATE_MONITOR_MODULE;
    free(m->total_measurement); free(m->domain_measurements[0]); free(m->domain_measurements); free(m->error_measurement); pthread_mutex_destroy(&m->lock);
    return 0;
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    code = a.output / 'monitor_replay.c'
    code.write_text(prefix + counter + '\n' + conversion + '\n' + monitor + '\n' + driver)
    binary = a.output / 'monitor-replay'
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Wno-unused-variable', '-Wno-sign-compare', '-fsanitize=address,undefined,float-cast-overflow', str(code), '-lm', '-pthread', '-o', str(binary)], check=True)
    cases = []
    for jitter, rate_value in [(0, 1000), (1, 1000), (10, 1000), (1, 0)]:
        environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=0')
        r = subprocess.run([str(binary), str(jitter), str(rate_value)], text=True, capture_output=True, check=True, env=environment)
        if r.stderr:
            raise RuntimeError(r.stderr)
        cases.append(json.loads(r.stdout))
    result = {'source': str(a.repo.resolve()), 'ref': a.ref or 'working-tree', 'boundary': 'complete production monitor task plus unchanged counter updater; controlled ASIC reads, RTOS wake times and NVS', 'scenarios': cases}
    (a.output / 'monitor_results.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
