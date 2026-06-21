"""
parser.py
Parses incoming UART lines:
- Classifies message type (SENSOR, STATUS, DUMP, ERROR, RAW)
- Extracts key=value numeric pairs for plotting
- Converts raw bytes to hex and ASCII representations
"""

import re
from datetime import datetime


def classify(line: str) -> str:
    l = line.upper()
    if l.startswith("SENSOR"):  return "SENSOR"
    if l.startswith("STATUS"):  return "STATUS"
    if l.startswith("DUMP"):    return "DUMP"
    if l.startswith("ERROR"):   return "ERROR"
    return "RAW"


def extract_numerics(line: str) -> dict:
    """
    Finds all key=value pairs where value is numeric.
    e.g. 'temp=23.4 vcc=3.31 rpm=1523' -> {'temp': 23.4, 'vcc': 3.31, 'rpm': 1523}
    """
    pattern = r'(\w+)=([-+]?\d+\.?\d*)'
    matches = re.findall(pattern, line)
    result = {}
    for key, val in matches:
        try:
            result[key] = float(val)
        except ValueError:
            pass
    return result


def to_hex(line: str) -> str:
    return " ".join(f"{ord(c):02X}" for c in line)


def to_ascii_safe(line: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 else "." for c in line)


def parse(line: str) -> dict:
    return {
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "raw": line,
        "type": classify(line),
        "numerics": extract_numerics(line),
        "hex": to_hex(line),
        "ascii": to_ascii_safe(line),
    }
