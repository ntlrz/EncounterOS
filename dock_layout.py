# dock_layout.py — Encode/decode QMainWindow geometry and dock state for config persistence.

from __future__ import annotations
from PySide6 import QtCore

# Bump when default dock arrangement changes so old saved state is ignored.
WINDOW_STATE_VERSION = 2


def encode_bytes(data: QtCore.QByteArray) -> str:
    return bytes(data.toBase64()).decode("ascii")


def decode_bytes(text: str) -> QtCore.QByteArray:
    if not text:
        return QtCore.QByteArray()
    return QtCore.QByteArray.fromBase64(text.encode("ascii"))
