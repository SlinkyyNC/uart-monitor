"""
serial_reader.py
Handles real UART serial port connections using pyserial.
Runs reading in a background thread and fires a callback per line.
"""

import threading
import serial
import serial.tools.list_ports


def list_ports():
    """Returns list of available COM/serial ports."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in sorted(ports)]


class SerialReader:
    def __init__(self, port, baud_rate, callback, error_callback=None):
        self.port = port
        self.baud_rate = baud_rate
        self.callback = callback
        self.error_callback = error_callback
        self._ser = None
        self._thread = None
        self._running = False

    def connect(self):
        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baud_rate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def disconnect(self):
        self._running = False
        if self._ser and self._ser.is_open:
            self._ser.close()

    def send(self, data: str):
        if self._ser and self._ser.is_open:
            self._ser.write((data + "\r\n").encode("utf-8"))

    def _read_loop(self):
        while self._running:
            try:
                if self._ser.in_waiting:
                    raw = self._ser.readline()
                    line = raw.decode("utf-8", errors="replace").strip()
                    if line:
                        self.callback(line)
            except serial.SerialException as e:
                if self.error_callback:
                    self.error_callback(str(e))
                self._running = False
