# tools/cancel.py
"""Sinyal berhenti untuk run yang dijalankan dari dashboard (dicek di awal setiap kelompok skenario)."""
import threading

CANCEL = threading.Event()


class RunCancelled(Exception):
    """Run dihentikan oleh pengguna."""


def check() -> None:
    if CANCEL.is_set():
        raise RunCancelled()
