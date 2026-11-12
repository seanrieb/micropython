"""Non-destructive RP2350 BTstack bond snapshot validation regression.

Run after the controller's BLE application has restored its existing bond:
    import bluetooth
    import ble_bond_prevalidation_test
    ble_bond_prevalidation_test.run(bluetooth.BLE())

No file writes, no bond clear, and no raw key output. This deliberately
tests only pre-mutation rejection paths. Do NOT call with an uninitialized
BLE instance or before your application restores its saved snapshot.
"""

def run(ble):
    snapshot = ble.bond_db()
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
