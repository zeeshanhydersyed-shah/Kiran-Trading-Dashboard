"""
Locate the owner's personal Excel trading journal without hardcoding its path.

Resolution order:
  1. KIRAN_JOURNAL_XLSX environment variable
  2. KIRAN_JOURNAL_XLSX=... line in the project's .env (gitignored)

Returns "" when neither is set, so callers can treat it exactly like a missing
file (os.path.exists("") is False) -- e.g. in CI, where the workbook never exists.
The workbook holds personal financial data and must never be committed.
"""
import os
from pathlib import Path

ENV_VAR = "KIRAN_JOURNAL_XLSX"


def get_journal_path() -> str:
    value = os.environ.get(ENV_VAR, "").strip()
    if value:
        return value

    env_file = Path(__file__).resolve().parent / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == ENV_VAR:
                return val.strip().strip("\"'")
    except OSError:
        pass
    return ""
