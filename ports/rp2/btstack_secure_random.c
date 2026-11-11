/*
 * Copyright (c) 2026 Sean Rieb
 * SPDX-License-Identifier: MIT
 *
 * RP2350 hardware-entropy-backed CTR_DRBG for BTstack.
 *
 * The CYW43 controller in the Pico 2 W build does not return the Command
 * Complete event for HCI LE Rand.  This source avoids that command rather
 * than replacing secure randomness with Pico SDK's non-cryptographic PRNG.
 *
 * The entropy callback samples the RP2350 TRNG with its built-in health
 * checks enabled.  Failure to obtain healthy entropy is fatal to the
 * random request: we deliberately do not use a time-based fallback.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "hardware/structs/trng.h"
#include "hardware/sync.h"
#include "pico/rand.h"
#include "pico/time.h"
#include "mbedtls/ctr_drbg.h"

#if !PICO_RP2350
#error "BTstack secure random implementation requires an RP2350 TRNG"
#endif

#define RP2350_TRNG_TIMEOUT_US (100000u)
#define RP2350_TRNG_BLOCK_BYTES (24u)
#define RP2350_TRNG_ERROR_MASK (0x0eu)

// Single BTstack event-loop context owns the DRBG. Pico SDK's RNG accesses
// the same hardware TRNG, so coordinate register access using its spinlock.
static mbedtls_ctr_drbg_context btstack_drbg;
static bool btstack_drbg_initialized;

static bool rp2350_read_healthy_entropy(uint8_t output[RP2350_TRNG_BLOCK_BYTES]) {
    spin_lock_t *lock = spin_lock_instance(PICO_SPINLOCK_ID_RAND);
    uint32_t irq_state = spin_lock_blocking(lock);

    // Reset any state left by other SDK TRNG clients. Do not bypass the
    // hardware Von Neumann, continuous, or autocorrelation health checks.
    trng_hw->rnd_source_enable = 0;
    trng_hw->trng_sw_reset = 1;
    trng_hw->trng_sw_reset = 0;
    trng_hw->trng_debug_control = 0;
    trng_hw->sample_cnt1 = 256;
    trng_hw->rng_icr = 0x0f;
    trng_hw->rnd_source_enable = 1;

    const uint64_t deadline = time_us_64() + RP2350_TRNG_TIMEOUT_US;
    bool valid = false;
    while (time_us_64() < deadline) {
        if ((trng_hw->rng_isr & RP2350_TRNG_ERROR_MASK) != 0) {
            break;
        }
        if ((trng_hw->trng_valid & 1u) != 0) {
            valid = true;
            break;
        }
    }

    if (valid && (trng_hw->rng_isr & RP2350_TRNG_ERROR_MASK) == 0) {
        uint32_t nonzero = 0;
        for (size_t i = 0; i < 6; ++i) {
            uint32_t word = trng_hw->ehr_data[i];
            nonzero |= word;
            memcpy(output + i * sizeof(word), &word, sizeof(word));
        }
        valid = nonzero != 0;
    }

    const uint32_t trng_status = trng_hw->rng_isr;
    const uint32_t trng_ready = trng_hw->trng_valid;
    trng_hw->rnd_source_enable = 0;
    spin_unlock(lock, irq_state);
    if (!valid) {
        // Diagnostic metadata only; entropy and keys are never printed.
        printf("BLE RNG: TRNG sample failed ISR=0x%02x valid=%u\n",
            (unsigned)trng_status, (unsigned)trng_ready);
        memset(output, 0, RP2350_TRNG_BLOCK_BYTES);
    }
    return valid;
}

static int rp2350_btstack_entropy(void *data, unsigned char *output, size_t len) {
    (void)data;
    while (len != 0) {
        uint8_t block[RP2350_TRNG_BLOCK_BYTES];
        if (!rp2350_read_healthy_entropy(block)) {
            return -1;
        }
        size_t count = len < sizeof(block) ? len : sizeof(block);
        memcpy(output, block, count);
        memset(block, 0, sizeof(block));
        output += count;
        len -= count;
    }
    return 0;
}

// Called synchronously from BTstack's event loop. Never log, write flash,
// or invoke Python from the entropy callback.
bool btstack_crypto_platform_random_generate(uint8_t *output, uint16_t len) {
    if (!btstack_drbg_initialized) {
        printf("BLE RNG: initializing RP2350 TRNG-seeded CTR_DRBG\n");
        static const unsigned char personalization[] = "RP2350 Pico 2 W BTstack SMP";
        mbedtls_ctr_drbg_init(&btstack_drbg);
        int result = mbedtls_ctr_drbg_seed(
            &btstack_drbg, rp2350_btstack_entropy, NULL,
            personalization, sizeof(personalization) - 1);
        if (result != 0) {
            printf("BLE RNG: CTR_DRBG seed failure, error=%d\n", result);
            mbedtls_ctr_drbg_free(&btstack_drbg);
            return false;
        }
        btstack_drbg_initialized = true;
        printf("BLE RNG: CTR_DRBG seeded\n");
    }
    while (len != 0) {
        size_t n = len < MBEDTLS_CTR_DRBG_MAX_REQUEST ?
            len : MBEDTLS_CTR_DRBG_MAX_REQUEST;
        int result = mbedtls_ctr_drbg_random(&btstack_drbg, output, n);
        if (result != 0) {
            printf("BLE RNG: CTR_DRBG generation failure, error=%d\n", result);
            return false;
        }
        output += n;
        len -= n;
    }
    return true;
}
