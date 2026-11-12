"""One-shot post-mutation BTstack bond restore fault regression.

Requires a *test-only* Pico 2 W firmware build compiled with
-DMICROPY_BTSTACK_BOND_IMPORT_FAULT_TEST. Never enable that flag in
release firmware. Run this at the REPL with the controller service stopped.

No saved JSON/file is read, modified, or erased. The snapshot is taken
from this BLE session; this test does not require an existing peer bond.
"""

import bluetooth


def _expect_exception(label, fn, exception_type):
    try:
        fn()
    except exception_type:
        print("PASS:", label)
        return
    except Exception as exc:
        raise AssertionError("{}: unexpected {}: {}".format(
            label, type(exc).__name__, exc))
    raise AssertionError("{}: operation unexpectedly succeeded".format(label))


def run():
    ble = bluetooth.BLE()
    if ble.active():
        raise RuntimeError("Stop the controller and deactivate BLE first")
    ble.active(True)
    try:
        if not hasattr(ble, "bond_db"):
            raise RuntimeError("firmware lacks BLE.bond_db")
        original = ble.bond_db()
        if original[:4] != b"BLB1":
            raise AssertionError("unexpected bond snapshot header")

        # A valid import starts changing live DB/keys, then the test hook
        # returns failure exactly once. Python maps this to ValueError.
        _expect_exception("injected import rejected",
                          lambda: ble.bond_db(original), ValueError)
        _expect_exception("snapshot export blocked",
                          lambda: ble.bond_db(), OSError)
        _expect_exception("advertising blocked",
                          lambda: ble.gap_advertise(100000, adv_data=b"\\x02\\x01\\x06"),
                          OSError)

        # Re-import the same snapshot. This is the required recovery path,
        # using already-present bytes and without clearing peer bonds.
        ble.bond_db(original)
        if ble.bond_db() != original:
            raise AssertionError("snapshot changed after recovery")
        print("PASS: successful reimport restores exact snapshot")

        ble.gap_advertise(100000, adv_data=b"\\x02\\x01\\x06")
        ble.gap_advertise(None)
        print("PASS: advertising unblocked after recovery")
        print("PASS: post-mutation fail-closed and recovery regression")
    finally:
        try:
            ble.gap_advertise(None)
        except Exception:
            pass
        ble.active(False)


if __name__ == "__main__":
    run()
