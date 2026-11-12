"""Non-destructive RP2350 BTstack bond snapshot validation regression.

Call from inside the running controller service after it has restored the
saved bond and before it deinitializes Bluetooth. Example at that point:
    import ble_bond_prevalidation_test
    ble_bond_prevalidation_test.run(ble)

If main.start() has returned and printed "Controller service stopped",
Bluetooth may already be inactive and bond export will fail with EIO.

This test never writes files or clears bonds. Do not run it before the
service restores the original bond.
"""

def run(ble):
    if not ble.active():
        raise RuntimeError(
            "BLE inactive: run inside the active controller service after "
            "bond restore, before Bluetooth shutdown"
        )
    try:
        snapshot = ble.bond_db()
    except OSError as exc:
        raise RuntimeError(
            "BLE bond export failed: run after the service has restored "
            "its bond, while Bluetooth is still active"
        ) from exc
    if len(snapshot) < 40 or snapshot[:4] != b"BLB1":
        raise AssertionError("Expected active, restored BLB1 bond snapshot")
    count = snapshot[4]
    if not count or len(snapshot) != 40 + 53 * count:
        raise AssertionError("Require at least one existing restored bond")

    cases = []

    modified = bytearray(snapshot)
    modified[0] ^= 1
    cases.append(("magic", bytes(modified)))

    cases.append(("truncated", snapshot[:-1]))

    modified = bytearray(snapshot)
    modified[5] = 1
    cases.append(("reserved", bytes(modified)))

    modified = bytearray(snapshot)
    modified[4] = (count + 1) & 0xff
    cases.append(("count", bytes(modified)))

    modified = bytearray(snapshot)
    modified[40 + 49] = 0
    cases.append(("key_size", bytes(modified)))

    modified = bytearray(snapshot)
    modified[40 + 50] = 2
    cases.append(("authenticated", bytes(modified)))

    for name, invalid in cases:
        try:
            ble.bond_db(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(name + ": expected ValueError")
        if ble.bond_db() != snapshot:
            raise AssertionError(name + ": original in-memory bond changed")
        print("PASS:", name)

    print("PASS: all", len(cases), "prevalidation cases, snapshot preserved")
    return True
