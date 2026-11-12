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
