# DFRobot Beetle RP2350 (DFR1188)

RP2350A, 2 MiB QSPI flash, 1 MiB default filesystem. No wireless hardware.
Board pinout: https://wiki.dfrobot.com/dfr1188/

Build from the repository root:

    make -C mpy-cross
    make -C ports/rp2 BOARD=DFROBOT_BEETLE_RP2350 submodules
    make -C ports/rp2 BOARD=DFROBOT_BEETLE_RP2350

Hold BOOT while resetting, then copy build-DFROBOT_BEETLE_RP2350/firmware.uf2
(from ports/rp2) to the RP2350 USB drive.

GPIO25 is the user LED; GPIO29 is battery sense. UART0 uses GPIO0/1,
UART1 uses GPIO8/9, I2C0 uses GPIO4/5, and SPI0 uses GPIO16/18/19.
SPI chip select is application-defined. The BOOT button is on QSPI_SS,
not a normal GPIO. Standard MicroPython USB configuration is retained.

Initial board definition; compilation and hardware testing are pending.
