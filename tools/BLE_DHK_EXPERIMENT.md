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

Call the test **inside the active controller service**, from its normal
application loop after the bond has been restored and before the service
stops Bluetooth. Do not call from the REPL after `main.start()` returns
and prints `Controller service stopped`: Bluetooth may already be inactive,
causing `BLE.bond_db()` to raise `OSError: EIO`.

Temporarily insert the following in the application code immediately after
the existing successful bond restore, using the application's existing BLE
instance (the restore must not be inside a Bluetooth IRQ callback):

```python
import ble_bond_prevalidation_test
ble_bond_prevalidation_test.run(ble)
```

Remove the temporary call after recording the result. Do not call
`ble.active(True)` just to circumvent an inactive-service error: that starts
a new BTstack session whose saved identity and peer records have not
necessarily been restored.

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

## Prevalidation test lifecycle correction (2026-11-11)

A test invocation after `main.start()` returned failed on its initial
`ble.bond_db()` export with `OSError: [Errno 5] EIO`; this was before any
malformed inputs were submitted. The preceding service run showed successful
bond restoration and encrypted reconnect, then `Controller service stopped`.
Likely cause is inactive Bluetooth at the REPL. The script now reports a
clear error for this condition. No six-case PASS result is claimed yet.

## Snapshot prevalidation: hardware PASS (2026-11-11)

On Pico 2 W running the hardening firmware, the in-service
`ble_bond_prevalidation_test.run(self.ble)` invocation passed all six
malformed-snapshot cases: magic, truncation, reserved byte, record count,
key size, and authentication flag. The script confirmed that the complete
93-byte in-memory snapshot remained unchanged across each rejected import.
Its existing single-bond fingerprint stayed `5fa26f6348995d5a`.

After the test, the Mac reconnected using the existing bond without
re-pairing. BTstack reported re-encryption status `0x00`,
`encrypted=1`, and `key_size=16`; the live snapshot still matched the
saved fingerprint. This proves format prevalidation does not disturb the
normal bonded reconnect path. It does **not** exercise post-mutation
failure injection, native mid-AES IR-change races, or fresh pairing.

The temporary test invocation in the controller repository's
`feature/ble-modes-7-9:controller_box/ble_mouse.py` should be removed
after validation. No bond clear or firmware rebuild is needed.

## Deterministic BTstack DKG race harness (new patch; not yet executed)

A separate patch, `tools/ble_dhk_native_race.patch`, augments the pinned
BTstack `test/security_manager` CppUTest mock with
`DkgRekeyDuringAsyncAES`. It uses explicit mock HCI LE Encrypt completions
to test IR changes in flight during IRK and DHK regeneration, checks that
the encrypted command uses the newest IR, checks readiness stays false
until both final requests finish, and tests duplicate-IR idempotency.

The existing native fixture normally compiles software AES (and secure
connections). The patch adds a separate `make dkg-race` configuration
with mocked HCI controller AES, without changing the default `make`
target or Pico firmware. It is **not** safe to run this race test against
real saved bonds.

From the MicroPython repository root, with
`tools/ble_dhk_rederive.patch` already applied in the submodule:

```sh
git fetch origin
git switch fix/rp2350-ble-dhk-hardening
git pull --ff-only

# In the pinned BTstack submodule; apply this additional TEST-only patch.
git -C lib/btstack apply --check ../../tools/ble_dhk_native_race.patch
git -C lib/btstack apply ../../tools/ble_dhk_native_race.patch
git -C lib/btstack diff --check

# Requires CppUTest installed, e.g. brew install cpputest on macOS.
cd lib/btstack/test/security_manager
make dkg-race
```

The patch is separate from the already verified firmware patch. Remove
only the test patch with:

```sh
git -C lib/btstack apply -R ../../tools/ble_dhk_native_race.patch
```

Run that revert from the MicroPython repository root. Do **not** reverse
the firmware `ble_dhk_rederive.patch` inadvertently.

The new test patch was checked against source at pinned BTstack commit
`18eab1b37d5319489a49150d17cf9a5b28d99c70` for exact hunk
positions and old context. **The native test has not yet compiled or
executed** here; a local GitHub clone and CppUTest were unavailable.
A passing native result is still needed before integrating into the
main feature branch. Post-mutation failure injection and fresh pairing
remain independent validation gates.

## Native mid-AES DKG race regression: PASS (2026-11-11)

On an Apple Silicon Mac with CppUTest installed, the dedicated
`make dkg-race` target built and executed successfully after the
test-only mock packet-buffer-length accessor was added in
`tools/ble_dhk_native_race.patch` (commit `410730c`).

Reported result:

```text
build-dkg/security_manager -n DkgRekeyDuringAsyncAES
OK (2 tests, 1 ran, 144 checks, 0 ignored, 1 filtered out, 0 ms)
```

The test exercises IR changes during mocked asynchronous IRK and DHK
derivation, verifies that the newest IR is used for restarted AES
commands, checks that readiness remains false until derivation finishes,
and verifies reapplying the same IR does not restart derivation.

This validates the native race handling **under the test mock**, not an
actual radio race. No Pico firmware or pairing state was altered by
this host-only test. The outstanding gates are post-mutation bond-import
failure injection and fresh-pairing validation before merging into
`feature/rp2350-ble-security`.

## Post-mutation fail-closed test: prepared, not yet executed (2026-11-11)

A one-shot fault-injection hook was added to
`extmod/btstack/modbluetooth_btstack.c`, **disabled in all normal
builds**. It is compiled only with
`MICROPY_BTSTACK_BOND_IMPORT_FAULT_TEST`. On the first structurally
valid bond import after BLE activation, it returns failure just after
clearing the live LE database and setting the restored ER/IR, leaving
the existing fail-closed state asserted. Subsequent imports run
normally. It does not write to filesystem or modify saved JSON.

The standalone test `tools/ble_bond_postmutation_test.py` creates
a snapshot of the live BLE session before injection (no real
paired peer required), then tests:
1. The first valid import fails with `ValueError` after mutation.
2. Bond export fails with `OSError` while restore is incomplete.
3. Advertising fails with `OSError` while restore is incomplete.
4. A second import of the identical snapshot succeeds and exports
   exactly the same bytes.
5. Advertising is available again after recovery.

**Use only a separate test build and run with the controller service
stopped**, preferably booting in mode 0. The fault build is intentionally
incompatible with normal first-attempt saved-bond restoration: the
controller will initially reject it. Keep a known-good UF2 and restore
that firmware after testing. Never turn this define on in a production
firmware build.

Example out-of-tree build from the MicroPython repository root,
using the existing patched BTstack submodule:

```sh
cmake -S ports/rp2 -B ports/rp2/build-RPI_PICO2_W-bond-fault-v2 \
    -DMICROPY_BOARD=RPI_PICO2_W \
    -DMICROPY_BOARD_DIR="$PWD/ports/rp2/boards/RPI_PICO2_W" \
    -DPICO_BUILD_DOCS=0 \
    -DMICROPY_BTSTACK_BOND_IMPORT_FAULT_TEST=ON
cmake --build ports/rp2/build-RPI_PICO2_W-bond-fault-v2 -j 4
```

The firmware output should be
`ports/rp2/build-RPI_PICO2_W-bond-fault-v2/firmware.uf2`.
Keep any existing user filesystem intact; do not format or clear bonds.

Copy the script onto the Pico root (from the repository root), then
with the controller stopped and BLE inactive:

```sh
mpremote cp tools/ble_bond_postmutation_test.py :ble_bond_postmutation_test.py
```

At the REPL:

```python
import ble_bond_postmutation_test
ble_bond_postmutation_test.run()
```

The script deactivates BLE on exit. A passed test means fail-closed
behavior and successful recovery were verified on the fault-injection
firmware. It does not prove the 2000 ms timeout path specifically;
that remains a separate scenario if required.

**Status: test implementation committed; compilation and hardware
execution still pending.**

**Build correction (2026-11-11):** The initial global
`-DCMAKE_C_FLAGS=...` approach produced Pico SDK spin-lock errors
because it interfered with the RP2350 target compiler configuration.
The test option is now implemented as a target-local CMake definition
and defaults to OFF. Use a **new** `-bond-fault-v2` build directory,
so cached global compiler flags from the failed build cannot persist.
Do not work around the error by disabling software spin locks.

## Post-mutation fail-closed hardware test: PASS (2026-11-11)

The dedicated RP2350 fault-injection firmware was tested on the Pico 2 W.
The console reported the expected test hook after generating a local ER
fingerprint, followed by all six checks:

```text
BTstack SMP: TEST injected post-mutation bond import failure
PASS: injected import rejected
PASS: snapshot export blocked
BTstack SMP: advertising blocked after failed bond restore
PASS: advertising blocked
BTstack SMP: IRK/DHK regeneration complete
PASS: successful reimport restores exact snapshot
PASS: advertising unblocked after recovery
PASS: post-mutation fail-closed and recovery regression
```

This demonstrates the production fail-closed guards work in the
fault-enabled test build after live database mutation, and a subsequent
valid import can recover. The test uses a session-local snapshot; it does
not establish that an existing paired peer could reconnect to this test
identity. No raw key material is recorded.

**Important:** Replace the fault-injection UF2 with the known-good normal
hardening firmware before running the controller or performing fresh
pairing. The normal build must omit the
`MICROPY_BTSTACK_BOND_IMPORT_FAULT_TEST` CMake option (default OFF).
Fresh pairing remains the final planned hardware validation gate.

## Fresh pairing on second Mac: PASS, cold-reconnect pending (2026-11-11)

With a separately backed-up mode-6 settings file removed (other mode
settings untouched), a normal hardening Pico 2 W build generated a
new local ER and 40-byte empty-bond snapshot. The second Mac paired using
Just Works, with `pairing complete ... status=0x00 reason=0x00`,
`key_size=16`, and `authenticated=0` (expected for Just Works).
The live bond database changed from `count=0 len=40` to
`count=1 len=93`, and the application reported
`BLE BOND FLUSH ... ok=True ... match_memory=True`. A subsequent live
security event reported `encrypted-1-bonded-1` and the new saved bond
fingerprint `5fc875da86c81fda`. This establishes first-time pairing,
bond insertion, and persistence to disk.

Cold-start restoration and re-encryption of this *new* bond remain to be
verified. Do not conflate the initial `bonded-0` security event during
pairing with the final persisted `bonded-1` state; the intermediate event
precedes the new bond record being saved.

The previous first-Mac bond was backed up separately and must be
restored only after the second-Mac cold-start validation. Never
commit raw bond snapshots or key material.

## Second Mac cold-start bonded reconnect: PASS (2026-11-11)

After successful pairing from a new, empty mode-6 identity and
persistence of the one-record bond, the user power-cycled the Pico 2 W.
The second Mac reconnected successfully without re-pairing. This
completes the clean-identity pairing + persistence + cold-start
reconnection hardware regression.

The cold-start reconnect result was reported as successful; no new
per-event console trace was supplied for this particular cycle, so
do not claim individual status fields or fingerprints beyond the prior
fresh-pairing output. The earlier first-Mac bonded reconnect tests
independently provided detailed HCI encryption status.
Keep both machines' bond files and credentials out of the repo.

**Validation summary:** Existing legacy bond reconnects, six malformed
snapshot rejection cases with unchanged live snapshot, native
mid-AES IR-change race (144 checks), one-shot post-mutation failure
injection with fail-closed advertising/export and recovery, and
second-Mac fresh pairing plus cold-start reconnect have passed.
Merge preparation/review remains, including removing temporary
test-only hooks from production configuration and checking the working
BTstack submodule patch against the source branch.
