#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    float current_hashrate;
    int64_t start_time_us;
    uint64_t uptime_seconds;
} SystemModule;

typedef struct {
    uint64_t total_uptime;
    uint64_t cumulative_hashes_high;
    uint64_t cumulative_hashes_low;
    uint32_t sentinel;
} NoinitState;

static NoinitState noinit_state;
static uint64_t last_update_time_ms;
static uint64_t last_nvs_write_time_ms;
static uint64_t total_uptime_at_system_start;
static uint64_t clock_us;
static unsigned nvs_writes;
static uint64_t nvs_values[3];

#define NVS_COUNTER_UPDATE_INTERVAL_MS (60 * 60 * 1000)
enum {
    NVS_CONFIG_TOTAL_UPTIME,
    NVS_CONFIG_CUMULATIVE_HASHES_HIGH,
    NVS_CONFIG_CUMULATIVE_HASHES_LOW
};

static int64_t esp_timer_get_time(void) { return (int64_t)clock_us; }
static void nvs_config_set_u64(int key, uint64_t value)
{
    nvs_writes++;
    nvs_values[key] = value;
}

#include "production_counter.inc"

static unsigned failures;

static void reset_state(SystemModule *module, uint64_t initial_low, uint64_t initial_high)
{
    memset(&noinit_state, 0, sizeof(noinit_state));
    memset(nvs_values, 0, sizeof(nvs_values));
    noinit_state.cumulative_hashes_low = initial_low;
    noinit_state.cumulative_hashes_high = initial_high;
    noinit_state.total_uptime = 100;
    total_uptime_at_system_start = 100;
    last_update_time_ms = 0;
    last_nvs_write_time_ms = 0;
    nvs_writes = 0;
    clock_us = 1000000;
    *module = (SystemModule){ .current_hashrate = 1000.0f, .start_time_us = 1000000 };
    SYSTEM_noinit_update(module);
}

static void trace(const char *name, const uint32_t *intervals, size_t interval_count,
                  unsigned steps, bool pause_first_half, uint64_t initial_low,
                  uint64_t initial_high, uint64_t expected_ms, unsigned expected_writes)
{
    SystemModule module;
    reset_state(&module, initial_low, initial_high);
    bool baseline_ok = noinit_state.cumulative_hashes_low == initial_low &&
                       noinit_state.cumulative_hashes_high == initial_high &&
                       nvs_writes == 0;
    for (unsigned i = 0; i < steps; i++) {
        clock_us += (uint64_t)intervals[i % interval_count] * 1000;
        module.current_hashrate = pause_first_half && i < steps / 2 ? 0.0f : 1000.0f;
        SYSTEM_noinit_update(&module);
    }
    const uint64_t expected_delta = expected_ms * 1000000000ULL;
    const uint64_t expected_low = initial_low + expected_delta;
    const uint64_t expected_high = initial_high + (expected_low < initial_low);
    const uint64_t duration_ms = clock_us / 1000 - 1000;
    const uint64_t expected_uptime = 100 + duration_ms / 1000;
    bool persisted_ok = expected_writes == 0 ||
        (nvs_values[NVS_CONFIG_TOTAL_UPTIME] == expected_uptime &&
         nvs_values[NVS_CONFIG_CUMULATIVE_HASHES_LOW] == expected_low &&
         nvs_values[NVS_CONFIG_CUMULATIVE_HASHES_HIGH] == expected_high);
    bool passed = baseline_ok && noinit_state.cumulative_hashes_low == expected_low &&
                  noinit_state.cumulative_hashes_high == expected_high &&
                  noinit_state.total_uptime == expected_uptime &&
                  nvs_writes == expected_writes && persisted_ok;
    failures += !passed;
    printf("{\"case\":\"%s\",\"elapsed_ms\":%" PRIu64 ","
           "\"expected_low\":%" PRIu64 ",\"actual_low\":%" PRIu64 ","
           "\"expected_high\":%" PRIu64 ",\"actual_high\":%" PRIu64 ","
           "\"expected_uptime\":%" PRIu64 ",\"actual_uptime\":%" PRIu64 ","
           "\"nvs_writes\":%u,\"persisted_low\":%" PRIu64 ",\"passed\":%s}\n",
           name, duration_ms, expected_low, noinit_state.cumulative_hashes_low,
           expected_high, noinit_state.cumulative_hashes_high,
           expected_uptime, noinit_state.total_uptime, nvs_writes,
           nvs_values[NVS_CONFIG_CUMULATIVE_HASHES_LOW], passed ? "true" : "false");
}

int main(void)
{
    const uint32_t steady[] = {1000};
    const uint32_t jitter[] = {999, 1001};
    const uint32_t short_polls[] = {500};
    const uint32_t delayed[] = {5000};
    const uint32_t carry[] = {2000};
    trace("steady_one_second", steady, 1, 20, false, 0, 0, 20000, 0);
    trace("alternating_999_1001_ms", jitter, 2, 20, false, 0, 0, 20000, 0);
    trace("repeated_500_ms", short_polls, 1, 40, false, 0, 0, 20000, 0);
    trace("delayed_poll", delayed, 1, 4, false, 0, 0, 20000, 0);
    trace("zero_rate_then_resume", steady, 1, 20, true, 0, 0, 10000, 0);
    trace("low_word_carry", carry, 1, 2, false,
          UINT64_MAX - 2000000000000ULL + 1, 7, 4000, 0);
    trace("hourly_persistence_with_jitter", jitter, 2, 3600, false, 0, 0, 3600000, 3);
    return failures ? 1 : 0;
}
