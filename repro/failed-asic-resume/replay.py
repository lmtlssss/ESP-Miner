#!/usr/bin/env python3
"""Replay the complete production power task at controlled hardware boundaries."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--repo',type=Path,required=True)
    p.add_argument('--ref')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    def source(path):
        return subprocess.check_output(['git','show',a.ref+':'+path],cwd=a.repo,text=True) if a.ref else (a.repo/path).read_text()
    header=source('main/tasks/power_management_task.h')
    production='\n'.join(line for line in source('main/tasks/power_management_task.c').splitlines() if not line.startswith('#include'))
    prefix=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define portTICK_PERIOD_MS 1
#define UART_NUM_1 1
typedef unsigned TickType_t;
typedef enum { ASIC_INIT_RECOVERY } asic_init_mode_t;
enum { NVS_CONFIG_ASIC_VOLTAGE, NVS_CONFIG_ASIC_FREQUENCY, NVS_CONFIG_AUTO_FAN_SPEED, NVS_CONFIG_MANUAL_FAN_SPEED, NVS_CONFIG_OVERHEAT_MODE };
'''
    boundaries=r'''
typedef struct { bool mining_paused, hardware_fault, pools_unavailable, overheat_mode; } SystemModule;
struct GlobalState { PowerManagementModule POWER_MANAGEMENT_MODULE; SystemModule SYSTEM_MODULE; struct { bool is_active,is_finished; } SELF_TEST_MODULE; struct { bool emc_internal_temp; struct { unsigned asic_count; struct { unsigned small_core_count, default_voltage_mv; float default_frequency_mhz; } asic; } family; } DEVICE_CONFIG; bool ASIC_initalized; };
static jmp_buf done;
static GlobalState state;
static unsigned scenario, cycles, attempts, stops, post_failure_voltage_writes, delays;
static bool failed_this_cycle;
static uint64_t now_ms;
static float requested_frequency=600;
static uint16_t requested_voltage=1150;
static bool overheat;
static void vTaskDelay(TickType_t ticks) { now_ms+=ticks; delays++; }
static void vTaskDelete(void *arg) { (void)arg; longjmp(done,2); }
static void suffixString(double value,char *dest,size_t capacity,int decimals) { (void)value;(void)decimals;if(capacity)dest[0]=0; }
static uint16_t nvs_config_get_u16(int key) { (void)key;return requested_voltage; }
static float nvs_config_get_float(int key) { (void)key;return requested_frequency; }
static bool nvs_config_get_bool(int key) { (void)key;return overheat; }
static void nvs_config_set_bool(int key,bool value) { if(key==NVS_CONFIG_OVERHEAT_MODE)overheat=value; }
static void nvs_config_set_u16(int key,uint16_t value) { if(key==NVS_CONFIG_ASIC_VOLTAGE)requested_voltage=value; }
static void nvs_config_set_float(int key,float value) { (void)key;requested_frequency=value; }
static float Power_get_input_voltage(GlobalState *g) {
    if(++cycles>6)longjmp(done,1);
    failed_this_cycle=false;
    g->SYSTEM_MODULE.mining_paused=(cycles==1);
    g->SYSTEM_MODULE.pools_unavailable=false;
    g->SYSTEM_MODULE.hardware_fault=false;
    if(scenario==3) {g->SYSTEM_MODULE.mining_paused=false;g->SYSTEM_MODULE.pools_unavailable=(cycles==1);}
    if(scenario==4) {g->SYSTEM_MODULE.mining_paused=false;g->SYSTEM_MODULE.hardware_fault=true;}
    if(scenario==5 && (cycles==3 || cycles==4))g->SYSTEM_MODULE.mining_paused=true;
    return 5000;
}
static void Power_get_output(GlobalState *g,float *power,float *current) { (void)g;*power=20;*current=4; }
static float VCORE_get_voltage_mv(GlobalState *g) { (void)g;return 1150; }
static float Thermal_get_chip_temp(GlobalState *g) { (void)g;return 40; }
static float Thermal_get_chip_temp2(GlobalState *g) { (void)g;return 0; }
static float Power_get_vreg_temp(GlobalState *g) { (void)g;return 40; }
static void ASIC_set_frequency(GlobalState *g) { g->POWER_MANAGEMENT_MODULE.actual_frequency=g->POWER_MANAGEMENT_MODULE.frequency_value; }
static void ASIC_set_nonce_space(GlobalState *g) { (void)g; }
static int VCORE_set_voltage(GlobalState *g,float voltage) { (void)g;if(voltage>0 && failed_this_cycle)post_failure_voltage_writes++;return 0; }
static void asic_hold_reset_low(void) { stops++; }
static void uart_flush(int port) { (void)port; }
static uint8_t asic_initialize(GlobalState *g,asic_init_mode_t mode,uint32_t stabilize_ms) {
    (void)mode; attempts++;
    bool success=(scenario==0 || (scenario!=2 && attempts>=2));
    failed_this_cycle=!success; g->ASIC_initalized=success;
    if(success)now_ms+=stabilize_ms;
    return success?1:0;
}
static int16_t VCORE_get_voltage_min_mv(GlobalState *g) { (void)g;return 900; }
static void VCORE_check_fault(GlobalState *g) { (void)g; }
static void difficulty_controller_update(GlobalState *g) { (void)g; }
'''
    driver=r'''
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    scenario=strtoul(argv[1],NULL,10);
    state.DEVICE_CONFIG.family.asic_count=1;
    state.DEVICE_CONFIG.family.asic.small_core_count=2040;
    state.DEVICE_CONFIG.family.asic.default_voltage_mv=1150;
    state.DEVICE_CONFIG.family.asic.default_frequency_mhz=600;
    state.ASIC_initalized=true;
    int stop_reason=setjmp(done);
    if(stop_reason==0)POWER_MANAGEMENT_task(&state);
    bool pass=false;
    switch(scenario) {
        case 0:pass=attempts==1 && state.ASIC_initalized;break;
        case 1:case 3:pass=attempts==2 && state.ASIC_initalized && post_failure_voltage_writes==0;break;
        case 2:pass=attempts>1 && !state.ASIC_initalized && post_failure_voltage_writes==0;break;
        case 4:pass=attempts==0 && !state.ASIC_initalized;break;
        case 5:pass=attempts==2 && state.ASIC_initalized && post_failure_voltage_writes==0;break;
    }
    printf("{\"scenario\":%u,\"initialization_attempts\":%u,\"asic_initialized\":%s,\"ordinary_voltage_writes_after_failure\":%u,\"stop_commands\":%u,\"delay_calls\":%u,\"elapsed_ms\":%llu,\"pass\":%s}\n",scenario,attempts,state.ASIC_initalized?"true":"false",post_failure_voltage_writes,stops,delays,(unsigned long long)now_ms,pass?"true":"false");
    return 0;
}
'''
    a.output.mkdir(parents=True,exist_ok=True)
    c=a.output/'power_replay.c'
    c.write_text(prefix+header+boundaries+production+driver)
    binary=a.output/'power-replay'
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O1','-g','-Wall','-Wextra','-Wno-unused-variable','-fsanitize=address,undefined',str(c),'-o',str(binary)],check=True)
    cases=[]
    for case in range(6):
        result=subprocess.run([str(binary),str(case)],capture_output=True,text=True,check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
        if result.stderr:raise RuntimeError(result.stderr)
        cases.append(json.loads(result.stdout))
    receipt={'ref':a.ref or 'working-tree','boundary':'complete production power task and helpers; controlled sensors, NVS, ASIC initialization and RTOS delays','scenarios':cases}
    (a.output/'results.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
