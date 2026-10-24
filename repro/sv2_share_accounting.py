#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Replay SV2 replies through actual parsers, receive cases and system counters.

This is a local host component replay. It has no sockets, Noise connection, ASIC
or RTOS. Production excerpts are compiled unchanged; only boundary types, clock,
logging, and latency storage are supplied by the harness. No third-party Python
packages are needed. Use --repo with a checkout to select that checkout's code.
"""
from __future__ import annotations
import argparse
import itertools
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def function(source: str, name: str) -> str:
    m = re.search(r'^.*\b' + re.escape(name) + r'\s*\([^;]*?\)\s*\{', source, re.M)
    if not m:
        raise ValueError(f'Production function not found: {name}')
    pos = source.index('{', m.start()) + 1
    depth = 1
    while depth:
        depth += (source[pos] == '{') - (source[pos] == '}')
        pos += 1
    return source[m.start():pos]

def from_repo(repo: Path) -> dict:
    c = (repo / 'main/tasks/stratum_v2_client.c').read_text()
    p = (repo / 'components/stratum_v2/sv2_protocol.c').read_text()
    s = (repo / 'main/system.c').read_text()
    start = c.index('            case SV2_MSG_SUBMIT_SHARES_SUCCESS:')
    end = c.index('\n            default:', start)
    return {'cases': c[start:end], 'protocol_functions': {
        n: function(p, n) for n in ('read_u32_le', 'read_str0255',
            'sv2_parse_submit_shares_success', 'sv2_parse_submit_shares_error')},
        'system_functions': {n: function(s, n) for n in ('update_pending_shares',
            'SYSTEM_notify_accepted_share', 'SYSTEM_notify_rejected_share',
            'compare_rejected_reason_stats')}}

PREAMBLE = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <stdbool.h>
#include <stdarg.h>
#define SV2_MSG_SUBMIT_SHARES_SUCCESS 0x1c
#define SV2_MSG_SUBMIT_SHARES_ERROR 0x1d
/* Logging is silenced but arguments remain evaluated. */
static void log_stub(const char *tag, const char *format, ...) {(void)tag;(void)format;}
#define ESP_LOGW log_stub
#define ESP_LOGI log_stub
static const char *TAG = "native-replay";
typedef struct {char message[64]; uint32_t count;} RejectedReasonStat;
typedef struct {
    uint64_t shares_submitted, shares_accepted, shares_rejected;
    uint16_t shares_pending;
    int rejected_reason_stats_count;
    RejectedReasonStat rejected_reason_stats[10];
} SystemModule;
typedef struct {SystemModule SYSTEM_MODULE;} GlobalState;
typedef struct {uint32_t channel_id, sequence_number, resolved_shares;} sv2_conn_t;
static int s_v2_timing;
static uint64_t latency_samples;
static int64_t esp_timer_get_time(void) {return 1000000;}
static float stratum_timing_calculate_ms(int *t, uint32_t seq, int64_t now) {
    (void)t;(void)seq;(void)now;return 1.0f;
}
static void SYSTEM_record_response_time(GlobalState *g, float v, uint16_t count) {
    (void)g;(void)v;latency_samples+=count;
}
'''
DRIVER = r'''
static void put32(uint8_t *p, uint32_t v) {
    for (int i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
int main(void) {
    GlobalState g={0};sv2_conn_t conn={.channel_id=7};char line[128];
    while (fgets(line,sizeof(line),stdin)) {
        char op;unsigned seq=0,count=0,channel=7,len=20;
        if (sscanf(line," %c",&op)!=1) continue;
        if (op=='R') {memset(&g,0,sizeof(g));conn=(sv2_conn_t){.channel_id=7};latency_samples=0;}
        else if (op=='N') {
            conn.sequence_number++;g.SYSTEM_MODULE.shares_submitted++;
            update_pending_shares(&g.SYSTEM_MODULE);
        }
        else if (op=='S') {
            if (sscanf(line," %c %u %u %u %u",&op,&seq,&count,&channel,&len)!=5) return 2;
            uint8_t b[20]={0};put32(b,channel);put32(b+4,seq);put32(b+8,count);
            if (len>sizeof(b)) return 2;
            receive_reply(&g,&conn,SV2_MSG_SUBMIT_SHARES_SUCCESS,b,len);
        }
        else if (op=='E') {
            if (sscanf(line," %c %u %u %u",&op,&seq,&channel,&len)!=4) return 2;
            uint8_t b[18]={0};put32(b,channel);put32(b+4,seq);b[8]=9;memcpy(b+9,"stale-job",9);
            if (len>sizeof(b)) return 2;
            receive_reply(&g,&conn,SV2_MSG_SUBMIT_SHARES_ERROR,b,len);
        }
        else return 2;
        printf("%u %u %"PRIu64" %"PRIu64" %u %"PRIu64"\n",conn.sequence_number,
          conn.resolved_shares,g.SYSTEM_MODULE.shares_accepted,g.SYSTEM_MODULE.shares_rejected,
          g.SYSTEM_MODULE.shares_pending,latency_samples);
    }
    return ferror(stdin)?2:0;
}
'''

def c_source(snapshot: dict) -> str:
    pieces = [PREAMBLE]
    pieces.extend(snapshot['protocol_functions'][n] for n in (
        'read_u32_le','read_str0255','sv2_parse_submit_shares_success','sv2_parse_submit_shares_error'))
    pieces.extend(snapshot['system_functions'][n] for n in (
        'update_pending_shares','compare_rejected_reason_stats',
        'SYSTEM_notify_accepted_share','SYSTEM_notify_rejected_share'))
    pieces.append('static void receive_reply(GlobalState *GLOBAL_STATE, sv2_conn_t *conn,\n'
        ' uint8_t message_type, const uint8_t *recv_buf, uint32_t payload_len) {\n'
        ' struct {uint32_t msg_length;} hdr={payload_len};\n switch(message_type) {\n')
    pieces.extend([snapshot['cases'], 'default: break;\n }\n}\n', DRIVER])
    return '\n'.join(pieces)

# The input traces are protocol stories, not descriptions of either implementation.
# N=one submitted share, S=success payload, E=one rejected share, R=new session.
def standard_trace(pattern: tuple[int,...], batch: int) -> list[str]:
    trace=['R'];waiting=[]
    for seq,ok in enumerate(pattern):
        trace.append('N')
        if ok:
            waiting.append(seq)
            if len(waiting)==batch:
                trace.append(f'S {waiting[-1]} {len(waiting)} 7 20');waiting=[]
        else:trace.append(f'E {seq} 7 18')
    if waiting:trace.append(f'S {waiting[-1]} {len(waiting)} 7 20')
    return trace

def scenarios():
    for n in range(1,9):
        for pattern in itertools.product((0,1),repeat=n):
            for batch in (1,3,10):
                yield f'exhaustive_{n}_{"".join(map(str,pattern))}_batch{batch}',standard_trace(pattern,batch)
    yield 'nine_good_one_error_one_good', standard_trace((1,)*9+(0,1),10)
    yield 'six_good_six_errors',standard_trace((1,0)*6,10)
    yield 'all_success_ten',standard_trace((1,)*10,10)
    yield 'all_error_ten',standard_trace((0,)*10,10)
    yield 'delayed_error', ['R','N','N','N','S 2 2 7 20','E 1 7 18']
    yield 'reversed_success_batches', ['R']+['N']*6+['S 5 3 7 20','S 2 3 7 20']
    yield 'error_then_older_success', ['R','N','N','E 1 7 18','S 0 1 7 20']
    yield 'success_then_older_error', ['R','N','N','S 1 1 7 20','E 0 7 18']
    yield 'two_errors_before_old_success', ['R']+['N']*5+['E 4 7 18','E 1 7 18','S 3 3 7 20']
    yield 'fresh_session_after_error', ['R','N','E 0 7 18','R','N','S 0 1 7 20']
    yield 'foreign_success', ['R','N','S 0 1 8 20','S 0 1 7 20']
    yield 'foreign_error', ['R','N','E 0 8 18','S 0 1 7 20']
    yield 'short_success', ['R','N','S 0 1 7 19','S 0 1 7 20']
    yield 'short_error', ['R','N','E 0 7 17','S 0 1 7 20']
    yield 'excess_accepted_count', ['R','N','N','S 1 100 7 20']
    yield 'empty_success_batch', ['R','N','S 0 0 7 20','S 0 1 7 20']


def expected(trace: list[str]) -> list[list[int]]:
    sent=accepted=rejected=timed=0;rows=[]
    for line in trace:
        z=line.split();op=z[0]
        if op=='R':sent=accepted=rejected=timed=0
        elif op=='N':sent+=1
        elif op=='S':
            _,seq,count,channel,length=map(int,['0']+z[1:])
            if channel==7 and length>=20:
                ack=min(count,max(0,sent-accepted-rejected));accepted+=ack;timed+=ack & 65535
        elif op=='E':
            _,seq,channel,length=map(int,['0']+z[1:])
            if channel==7 and length>=18:rejected+=1
        rows.append([sent,min(sent,accepted+rejected),accepted,rejected,
            min(65535,max(0,sent-accepted-rejected)),timed])
    return rows


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    source=ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--repo',type=Path)
    source.add_argument('--source-json',type=Path)
    ap.add_argument('--report',type=Path)
    ap.add_argument('--sanitize',action='store_true')
    ap.add_argument('--expect-failure',action='store_true',help='Exit zero if the original mixed-batch regression is reproduced')
    args=ap.parse_args()
    if args.repo:
        snapshot=from_repo(args.repo.resolve());origin=str(args.repo.resolve())
    else:
        path=args.source_json or ROOT/'fixtures/SOURCE_EXCERPTS.json'
        snapshot=json.loads(path.read_text());origin=str(path)
    cases=list(scenarios());all_input=''.join('\n'.join(t)+'\n' for _,t in cases)
    with tempfile.TemporaryDirectory(prefix='sv2-ack-') as tmp:
        src=Path(tmp)/'replay.c';exe=Path(tmp)/'replay';src.write_text(c_source(snapshot))
        flags=['-std=c11','-Wall','-Wextra','-O1','-g']
        if args.sanitize:flags+=['-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie']
        subprocess.run([os.environ.get('CC','cc'),*flags,str(src),'-o',str(exe)],check=True,timeout=30)
        run=subprocess.run([str(exe)],input=all_input,text=True,capture_output=True,timeout=30)
        if run.returncode:
            raise RuntimeError(f'Native replay exit {run.returncode}: {run.stderr}')
        got=[list(map(int,l.split())) for l in run.stdout.splitlines()]
    records=[];offset=0;trace_output={}
    for name,trace in cases:
        want=expected(trace);seen=got[offset:offset+len(trace)];offset+=len(trace)
        mismatches=[i for i,(a,b) in enumerate(zip(want,seen)) if a!=b]
        if len(want)!=len(seen):raise RuntimeError('Missing native output')
        records.append({'case':name,'events':len(trace),'failed_steps':len(mismatches),
                        'expected_final':want[-1],'observed_final':seen[-1]})
        if not name.startswith('exhaustive_'):
            trace_output[name]=[{'event':e,'expected':w,'observed':s} for e,w,s in zip(trace,want,seen)]
    if offset!=len(got):raise RuntimeError('Unexpected native output')
    failures=sum(r['failed_steps']>0 for r in records)
    summary={'source':origin,'case_count':len(cases),'events':offset,'failing_cases':failures,
        'failing_final_states':sum(r['expected_final']!=r['observed_final'] for r in records),
        'sanitizers':args.sanitize,'diagnostics':run.stderr,
        'columns':['submitted','resolved','accepted','rejected','pending_display','latency_samples'],
        'records':records,'traces':trace_output}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('records','traces')},indent=2))
    for name in ('nine_good_one_error_one_good','six_good_six_errors'):
        print(name,json.dumps(next(r for r in records if r['case']==name)))
    reproduced=next(r for r in records if r['case']=='nine_good_one_error_one_good')['observed_final'][2]==1
    return (0 if reproduced else 1) if args.expect_failure else (0 if failures==0 else 1)

if __name__=='__main__':
    raise SystemExit(main())
