"""
logger.py
Minimal logging helper for the encyclopedia generator.

Goals:
- Provide consistent, readable console output.
- Optional file-based logging for debugging.
- No external dependencies.

This module is intentionally lightweight because the generator
must remain portable across GitHub Actions and local runs.
"""

from datetime import datetime
from pathlib import Path


class Logger:
    def __init__(self, logfile: str | None = None):
        self.logfile = Path(logfile) if logfile else None

        if self.logfile:
            self.logfile.parent.mkdir(parents=True, exist_ok=True)
            self._write_file("=== Log started ===\n")

    def _timestamp(self):
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    def _write_file(self, text: str):
        if self.logfile:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(text)

    def info(self, msg: str):
        line = f"[INFO {self._timestamp()}] {msg}"
        print(line)
        self._write_file(line + "\n")

    def warn(self, msg: str):
        line = f"[WARN {self._timestamp()}] {msg}"
        print(line)
        self._write_file(line + "\n")

    def error(self, msg: str):
        line = f"[ERROR {self._timestamp()}] {msg}"
        print(line)
        self._write_file(line + "\n")

    def success(self, msg: str):
        line = f"[OK {self._timestamp()}] {msg}"
        print(line)
        self._write_file(line + "\n")
