# BLE DHK regeneration hypothesis test (temporary)

This experiment is isolated on `experiment/ble-raw-key-probe`.
The unchanged test baseline is commit `ea25e444779214662e36f7cd85025958cef0f167`
on `feature/rp2350-ble-security`.

## Hypothesis

BTstack derives IRK and DHK from an all-zero bootstrap IR on HCI startup.
Later `BLE.bond_db(snapshot)` restores the proper IR, but `sm_set_ir`
does not invalidate/rederive the cached DHK. Thus existing bonded
connections reconstruct a wrong legacy LTK.

The experimental patch `tools/ble_dhk_rederive.patch` modifies the
**pinned BTstack submodule source** (not MicroPython's tracked adapter file)
to schedule IRK/DHK regeneration when IR changes after HCI startup, and
exports `sm_derived_keys_ready()`. The experimental MicroPython adapter
waits for that state before completing bond restore.

## Apply and build (macOS)

From the MicroPython repository root:

```sh
git fetch origin
git switch experiment/ble-raw-key-probe
git submodule update --init lib/btstack
git -C lib/btstack apply --check ../../tools/ble_dhk_rederive.patch
git -C lib/btstack apply ../../tools/ble_dhk_rederive.patch
git -C lib/btstack status --short
cd ports/rp2
make BOARD=RPI_PICO2_W
```

This is intentionally a **two-file BTstack patch on a pinned submodule**.
Ordinary `git pull` does not apply it automatically. Do **not** run
`git submodule update --force` after applying, or the local patch will be
overwritten.

Flash the experimental UF2. Keep the existing mode-6 bond and Mac
pairing; run `import main; main.start()`. The expected native LTK is
`e154b79943b254f0555ed1518e22ea03` and HCI byte order
`03ea228e51d15e55f054b24399b754e1`.
Look for `BTstack SMP: IRK/DHK regeneration complete` before the
connection and `re-encryption complete ... status=0x00`. The entire
128-bit key agreement is the prediction; a successful connection alone
is insufficient confirmation.

## Revert / repeat baseline

To discard *only this experimental BTstack patch* from the submodule:

```sh
cd /path/to/micropython
git -C lib/btstack apply -R ../../tools/ble_dhk_rederive.patch
git -C lib/btstack status --short
git switch feature/rp2350-ble-security
git rev-parse HEAD
cd ports/rp2
make BOARD=RPI_PICO2_W
```

Do not erase or edit any `ble_settings_mode*.json`, forget any Mac
pairings, or change the controller application during this test. Keep
the original UF2 for an exact binary restore where possible.

The patch is an experiment, not an upstream BTstack fix. It has not been
validated with a local native build.

## Verification results (2026-11-11)

Pico 2 W running MicroPython v1.29.0-53.gd328f32bfd.dirty:
five consecutive bonded reconnections to macOS completed without re-pairing.
All five logs reported `IRK/DHK regeneration complete`, an unchanged
93-byte one-record bond database, `re-encryption complete ... status=0x00`,
128-bit key size, and GATT reads/writes. HID mouse operation was verified.
macOS PacketLogger traces `verification1.pklg` and `verification2.pklg`
were supplied for independent comparison. These captures are not committed
because they can contain security-sensitive key material. Reported host-side
disconnection reason 0x08 (connection timeout) followed Pico restarts.
The logs do not definitively categorize each restart as a soft reset or cold
power cycle.

The experimental build confirmed the entire native 128-bit legacy LTK and
its HCI byte-order representation matched the macOS encryption command.
Do not include raw keys in permanent documentation.

## Hardening review and remaining gates

The successful experiment isolates the stale-DHK root cause, but a clean
long-term fix still requires review of BTstack's DKG state-machine behavior:
- `sm_set_ir()` must preserve IRK/DHK consistency when IR changes after
  initialization, including a repeated update during an in-flight derivation.
- Determine whether an active security procedure can observe inconsistent
  keys during a change; do not trigger IR changes during active connections
  without an explicit safety policy.
- `sm_derived_keys_ready()` currently reports `dkg_state == DKG_READY`.
  Assess whether this can falsely report ready for the wrong IR generation.
- The MicroPython import waits up to 2000 ms with `mp_hal_delay_ms(1)`.
  Verify that run-loop progress is guaranteed in this context, and preserve
  a deterministic failure path if the cryptographic engine stalls.
- Bond import currently clears the peer database and updates local ER/IR
  *before* checking derivation completion, so failure is not transactional.
  A future change should avoid leaving partially restored state.
- Validate both existing bonded reconnect and brand-new pairing, including
  soft reset, power-cycle, and disconnect/reconnect.

## Safe diagnostic cleanup branch

`fix/rp2350-ble-dhk-hardening` branches from the validated experiment.
It removes raw ER, IR, and LTK diagnostic printing in the MicroPython adapter,
while retaining nonsecret SHA-256 fingerprints and encryption status messages.
The original experiment branch is deliberately untouched as a reproducible
reference. The BTstack patch and synchronous readiness wait are not changed
in this cleanup, because state-machine/scheduler modifications require
separate code review and device regression testing.

When using the hardening branch, first reverse the old patch in the local
BTstack submodule only if switching to a different patch revision. This branch now has a **revised** patch. If your local submodule still
has the original experimental patch applied, reverse that original patch
before applying this revision. `git pull` does not manage local submodule
source modifications.

Do not promote this branch to production until a clean RP2350 build and
on-device reconnect tests pass. An existing build made before the cleanup
still contains plaintext key diagnostics.

## State-machine hardening revision (unverified on hardware)

The hardened patch updates `sm_set_ir()` to skip identical IR values and
mark a changed IR as requiring fresh IRK/DHK derivation. The completion
callbacks check a pending-restart flag rather than unconditionally advancing
to `DKG_CALC_DHK` or `DKG_READY`. Starting the IRK AES request clears
the flag; another IR change during either asynchronous AES request sets it
again. `sm_derived_keys_ready()` requires both READY and no pending restart.

This addresses one identified callback-overwrites-state race. It does NOT
establish a safe API for arbitrary IR changes during active encrypted
connections, nor make bond imports atomic. Application code must continue
to restore bonds before advertising or accepting connections.

### Upgrade from the previously tested patch

From the repository root, with a local old experimental patch applied:

```sh
git fetch origin
git show origin/experiment/ble-raw-key-probe:tools/ble_dhk_rederive.patch > /tmp/ble-dhk-v1.patch
git -C lib/btstack apply --check -R /tmp/ble-dhk-v1.patch
git -C lib/btstack apply -R /tmp/ble-dhk-v1.patch
git switch fix/rp2350-ble-dhk-hardening
git -C lib/btstack apply --check ../../tools/ble_dhk_rederive.patch
git -C lib/btstack apply ../../tools/ble_dhk_rederive.patch
git -C lib/btstack diff --check
cd ports/rp2
make BOARD=RPI_PICO2_W
```

If `git -C lib/btstack status --short` is clean before starting, omit
the old-patch reverse operations. Do not run `git submodule update --force`
with local modifications present.

Flash, preserve the existing BLE bond and Mac pairing, and retest reconnect
and HID. The new revision has not been built or flashed by the assistant.

For additional race-focused tests, exercise repeated IR restores *before*
advertising (including duplicate snapshots) and verify that readiness
never signals before IRK/DHK both finish. A deliberate mid-AES IR update
requires a controlled native harness or explicitly instrumented firmware.

## Revised DKG guard: initial hardware validation (2026-11-11)

The RP2350/Pico 2 W hardening revision with the pending-restart guard was
built and flashed by the tester. The existing mode-6 bonded connection
succeeded and the HID mouse operated normally. This validates the ordinary
saved-bond reconnect path after the revision. It does **not** yet exercise
an intentional IR change during an active asynchronous AES request, nor
confirm all cold-power-cycle and new-pairing regression cases.

## Fail-closed bond restore revision (requires new device regression)

The MicroPython adapter now tracks incomplete bond mutations. A structurally
invalid snapshot is rejected before any state changes. Once a valid import
begins modifying the live peer database or local root keys, snapshot exports
and advertising remain blocked until every peer record has been restored and
the DKG reports ready. If an AES readiness timeout or database insert fails,
a subsequent advertising attempt returns EIO rather than using partial state.
An explicit successful `BLE.bond_db(None)` clear or successful re-import
recovers the state; a normal Bluetooth reinitialization also resets it.

This is **fail-closed**, not fully transactional: it does not roll back the
previous keys and peer records. Do not delete the saved JSON or invoke clear
while diagnosing a failure. The existing application's bond restore path
must check and propagate `BLE.bond_db(snapshot)` exceptions.

### Hardware regression procedure

1. Rebuild and flash the revision without deleting the original mode-6
   snapshot or forgetting the Mac's pairing.
2. Verify an ordinary bonded mode-6 reconnect, encrypted status 0x00,
   identical saved snapshot fingerprint, and working mouse HID.
3. Repeat after a full power disconnect/reconnect.
4. Before BLE advertising, attempt to import a deliberately malformed
   snapshot (e.g. altered magic) on a disposable test setup. Confirm
   `ValueError` and that this prevalidation failure does not poison the
   previously valid state. Do not mutate the persisted JSON file.
5. In a separate disposable test setup, inject a post-mutation failure
   (e.g. controlled timeout or database-add error) and confirm subsequent
   advertising returns EIO and bond export refuses the partial state.
   Do not simulate this with the production bond data.
6. Recover with a valid saved snapshot; verify encryption and HID again.

### Targeted mid-AES IR race test

The revised BTstack source contains a restart flag but normal HID tests do
not force the race. Use a native BTstack test harness with a queued/stubbed
AES engine. Start IRK derivation for IR=A; before its callback, install IR=B.
Verify readiness stays false, both IRK and DHK eventually derive from B, and
only then does readiness become true. Repeat with the change made during
DHK derivation, and with A->B->C changes. Assert an unchanged IR does not
schedule another derivation. A matching hardware reconnect is necessary but
not a substitute for these state-machine tests.

Release gate: the new fail-closed adapter code is NOT yet validated by a
local build, native race test, or Pico hardware run.

## Fail-closed revision: ordinary reconnect regression (2026-11-11)

Tester confirmed the latest fail-closed bond restoration build runs on Pico 2 W,
restores the existing bonded connection, and operates the BLE HID mouse.
This validates the normal success path after the fail-closed changes. It does
not establish that injected post-mutation failures are blocked, that the
mid-AES race is exercised, or that a fresh pairing has been tested.

## Non-destructive snapshot prevalidation test

The script `tools/ble_bond_prevalidation_test.py` tests six validation
failures without clearing or intentionally mutating any active bond. It uses
a *copy* of the existing in-memory snapshot, deliberately corrupts only
specific format bytes, expects a `ValueError`, and compares the full
subsequent in-memory export to the original bytes. It neither reads nor
writes persistent JSON files and does not log key material.

Use after the current application has loaded mode-6 bonds, while there is
no new pairing in progress. From the Mac repository root:

```sh
mpremote cp tools/ble_bond_prevalidation_test.py :
```

At the Pico REPL **after** `import main; main.start()` has restored the
bond and established a stable connection (or after a clean disconnect):

```python
import bluetooth
import ble_bond_prevalidation_test
ble_bond_prevalidation_test.run(bluetooth.BLE())
```

Expected: six `PASS:` case messages and a final preserved-snapshot PASS.
Do not use `BLE.bond_db(None)` or forget the macOS pairing.

This checks validation-before-mutation only. It does not inject a failure
after peer-record deletion or during DKG. Those cases require an isolated,
disposable test fixture or native mocking; testing them on the real bonded
device could lose the saved bond.

### Native asynchronous test integration target

The pinned BTstack repository has a CppUTest harness at
`lib/btstack/test/security_manager/` with an HCI/AES mock
(`mock.c`, `aes128_report_result()`) and a test runner
(`security_manager.cpp`). The target scenarios are:
- Start IRK derivation on IR=A; change to B while AES is outstanding.
  Complete A's callback and verify a fresh IRK request for B is sent,
  followed by a DHK request for B, with readiness false until completion.
- Change IR during the DHK request; verify a full restart from IRK.
- Change A -> B -> C before completion; verify final derived keys use C.
- Reinstall the identical IR; verify no unnecessary regeneration.
- Verify the final key output using a known AES d1 test vector, not merely
  a READY boolean.

The mock-based race tests are **specified, not yet implemented or run**.
The existing Pico reconnect/HID success is not a substitute for this test.
