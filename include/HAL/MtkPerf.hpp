// SPDX-License-Identifier: GPL-3.0-or-later
// Optional throughput counters. Normal updates require the main workloop gate.
#pragma once
#ifndef MTK_PERF
#define MTK_PERF 0
#endif
#if MTK_PERF
#include <stdint.h>
#ifndef MTK_PERF_HOST
#include <kern/clock.h>
#endif
enum { MP_SCHEMA = 2, MP_BOUNCE_SAMPLE_PERIOD = 64 };
#define MP_FIELDS(X) \
    X(rx_desc) \
    X(rx_desc_bytes) \
    X(rx_records) \
    X(rx_record_bytes) \
    X(rx_partial_drop) \
    X(rx_normal) \
    X(rx_normal_bytes) \
    X(rx_fill_drop) \
    X(rx_mpdu) \
    X(rx_mpdu_bytes) \
    X(rx_amsdu_sub) \
    X(rx_amsdu_sub_bytes) \
    X(rx_amsdu_flush) \
    X(rx_amsdu_alloc_fail) \
    X(rx_amsdu_chain) \
    X(rx_amsdu_copy_fail) \
    X(rx_amsdu_timer_flush) \
    X(rx_amsdu_timer_fail) \
    X(rx_amsdu_cross_batch_complete) \
    X(rx_amsdu_purge_sub) \
    X(rx_budget_more) \
    X(rx_refill_fail) \
    X(rx_bsd_packets) \
    X(rx_bsd_bytes) \
    X(rx_bsd_return_packets) \
    X(rx_bsd_flush_return) \
    X(rx_normalize_copy) \
    X(rx_normalize_drop) \
    X(tx_pull_packets) \
    X(tx_pull_bytes) \
    X(tx_enqueue_ok) \
    X(tx_enqueue_drop) \
    X(tx_dma_ok) \
    X(tx_dma_drop) \
    X(tx_dma_bytes) \
    X(tx_wtbl_ba_enable_submit) \
    X(tx_wtbl_ba_disable_submit) \
    X(tx_wtbl_ba_submit_fail) \
    X(tx_sta_ba_submit_fail) \
    X(gauge_tx_ba_agreements) \
    X(bounce_rx_calls) \
    X(bounce_rx_bytes) \
    X(bounce_tx_calls) \
    X(bounce_tx_bytes) \
    X(watchdog_busy) \
    X(gauge_state) \
    X(gauge_running) \
    X(gauge_tx_full) \
    X(gauge_tx_free) \
    X(gauge_txwi_free) \
    X(tx_full_token) \
    X(tx_full_ring) \
    X(tx_wake_below_threshold) \
    X(tx_pause_abort) \
    X(tx_pause_samples) \
    X(tx_pause_ticks) \
    X(tx_pause_max_ticks) \
    X(gauge_tx_oactive) \
    X(gauge_ba_gap_timeout) \
    X(gauge_ba_lost) \
    X(gauge_ba_below) \
    X(gauge_ba_above) \
    X(gauge_tooshort) \
    X(gauge_decap) \
    X(gauge_nombuf) \
    X(gauge_rx_fill_fail) \
    X(gauge_amsdu_pending) \
    X(rx_dequeue_samples) \
    X(rx_dequeue_ticks) \
    X(rx_dequeue_max_ticks) \
    X(rx_refill_samples) \
    X(rx_refill_ticks) \
    X(rx_refill_max_ticks) \
    X(rx_process_samples) \
    X(rx_process_ticks) \
    X(rx_process_max_ticks) \
    X(rx_if_input_samples) \
    X(rx_if_input_ticks) \
    X(rx_if_input_max_ticks) \
    X(rx_bsd_flush_samples) \
    X(rx_bsd_flush_ticks) \
    X(rx_bsd_flush_max_ticks) \
    X(tx_start_samples) \
    X(tx_start_ticks) \
    X(tx_start_max_ticks) \
    X(tx_gated_samples) \
    X(tx_gated_ticks) \
    X(tx_gated_max_ticks) \
    X(tx_gate_wait_samples) \
    X(tx_gate_wait_ticks) \
    X(tx_gate_wait_max_ticks) \
    X(rx_bounce_sample_samples) \
    X(rx_bounce_sample_ticks) \
    X(rx_bounce_sample_max_ticks) \
    X(rx_intr_samples) \
    X(rx_intr_ticks) \
    X(rx_intr_max_ticks)
enum MpField {
#define MP_ENUM(n) mp_##n,
    MP_FIELDS(MP_ENUM)
#undef MP_ENUM
    mp_count
};
extern uint64_t mp_values[mp_count];
inline void mp_add(MpField f, uint64_t n = 1) { mp_values[f] += n; }
// Fields written outside the gate must use atomic access exclusively.
inline void mp_async_add(MpField f, uint64_t n = 1) {
    __atomic_fetch_add(&mp_values[f], n, __ATOMIC_RELAXED);
}
inline void mp_set(MpField f, uint64_t n) { mp_values[f] = n; }
inline void mp_time(MpField first, uint64_t elapsed) {
    mp_add(first);
    mp_add(MpField(first + 1), elapsed);
    if (elapsed > mp_values[first + 2]) mp_values[first + 2] = elapsed;
}
// Time batches; sample the bounce-copy section once every 64 calls.
class MpTimer {
    MpField first;
    uint64_t start;
    bool enabled;
public:
    MpTimer(MpField f, bool on = true) : first(f),
        start(on ? mach_absolute_time() : 0), enabled(on) {}
    ~MpTimer() { if (enabled) mp_time(first, mach_absolute_time() - start); }
};
class IOService;
void mtk_perf_publish(IOService *);
#endif
