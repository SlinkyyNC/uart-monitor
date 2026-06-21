"""
simulator.py
Simulates a UART device sending realistic embedded-system style messages.
Used for development and demo when no real hardware is connected.
"""

import threading
import time
import random
import math


class UARTSimulator:
    """
    Mimics a microcontroller sending mixed serial output:
    - Sensor readings (temperature, voltage, RPM)
    - Status messages
    - Hex debug dumps
    - Occasional error frames
    """

    def __init__(self, callback):
        self.callback = callback  # called with each new line of data
        self._running = False
        self._thread = None
        self.t = 0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        messages = [
            self._sensor_line,
            self._sensor_line,
            self._sensor_line,
            self._status_line,
            self._hex_dump,
            self._error_line,
        ]
        while self._running:
            fn = random.choice(messages)
            line = fn()
            self.callback(line)
            time.sleep(random.uniform(0.3, 1.2))
            self.t += 1

    def _sensor_line(self):
        temp = round(22 + 4 * math.sin(self.t / 30) + random.gauss(0, 0.3), 2)
        voltage = round(3.3 + random.gauss(0, 0.05), 3)
        rpm = int(1500 + 200 * math.sin(self.t / 20) + random.gauss(0, 10))
        return f"SENSOR temp={temp} vcc={voltage} rpm={rpm}"

    def _status_line(self):
        statuses = [
            "STATUS OK heartbeat",
            "STATUS OK buffer_free=512",
            "STATUS OK uptime={}s".format(self.t * 2),
            "STATUS WARN adc_noise_high",
            "STATUS OK watchdog_reset",
        ]
        return random.choice(statuses)

    def _hex_dump(self):
        n = random.randint(4, 8)
        bytes_ = [random.randint(0, 255) for _ in range(n)]
        hex_str = " ".join(f"{b:02X}" for b in bytes_)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in bytes_)
        return f"DUMP [{hex_str}] |{ascii_str}|"

    def _error_line(self):
        if random.random() > 0.3:
            return self._sensor_line()
        errors = [
            "ERROR framing_error rx_overflow",
            "ERROR checksum_fail expected=0xAB got=0xCD",
            "ERROR timeout waiting_for_ack",
        ]
        return random.choice(errors)
