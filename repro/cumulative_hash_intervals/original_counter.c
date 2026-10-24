void SYSTEM_noinit_update(SystemModule * SYSTEM_MODULE)
{
    uint64_t current_time_ms = esp_timer_get_time() / 1000;
    
    // Initialize last_update_time on first call
    if (last_update_time_ms == 0) {
        last_update_time_ms = current_time_ms;
        last_nvs_write_time_ms = current_time_ms;
        return;
    }

    uint64_t elapsed_ms = current_time_ms - last_update_time_ms;
    last_update_time_ms = current_time_ms;
    
    // Only update if at least 1 second has passed
    if (elapsed_ms < 1000) {
        return;
    }
    
    SYSTEM_MODULE->uptime_seconds = (esp_timer_get_time() - SYSTEM_MODULE->start_time_us) / 1000000;
    noinit_state.total_uptime = total_uptime_at_system_start + SYSTEM_MODULE->uptime_seconds;
    
    // Update cumulative hashes: hashrate (GH/s) × milliseconds × 1e6 = raw hashes
    uint64_t hashes_done = elapsed_ms * 1e6 * SYSTEM_MODULE->current_hashrate;
    uint64_t new_low = noinit_state.cumulative_hashes_low + hashes_done;
    if (new_low < noinit_state.cumulative_hashes_low) {
        noinit_state.cumulative_hashes_high++;
    }
    noinit_state.cumulative_hashes_low = new_low;

    // Persist to NVS once per hour to reduce wear
    if (current_time_ms - last_nvs_write_time_ms >= NVS_COUNTER_UPDATE_INTERVAL_MS) {
        nvs_config_set_u64(NVS_CONFIG_TOTAL_UPTIME, noinit_state.total_uptime);
        nvs_config_set_u64(NVS_CONFIG_CUMULATIVE_HASHES_HIGH, noinit_state.cumulative_hashes_high);
        nvs_config_set_u64(NVS_CONFIG_CUMULATIVE_HASHES_LOW, noinit_state.cumulative_hashes_low);
        last_nvs_write_time_ms = current_time_ms;
    }
}
