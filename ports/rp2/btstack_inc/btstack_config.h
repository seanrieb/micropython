#ifndef MICROPY_INCLUDED_BTSTACK_BTSTACK_CONFIG_H
#define MICROPY_INCLUDED_BTSTACK_BTSTACK_CONFIG_H

#define HCI_OUTGOING_PRE_BUFFER_SIZE 4
#define HCI_ACL_CHUNK_SIZE_ALIGNMENT 4

// CYW43 on RP2350 accepts BLE traffic but does not complete HCI LE Encrypt.
// Keep AES-128 on the host, using BTstack's bundled Rijndael implementation.
#if PICO_RP2350 && MICROPY_PY_BLUETOOTH_CYW43
#define ENABLE_SOFTWARE_AES128
#define HAVE_BTSTACK_CRYPTO_PLATFORM_RANDOM
#endif

#include "btstack_config_common.h"

#endif
