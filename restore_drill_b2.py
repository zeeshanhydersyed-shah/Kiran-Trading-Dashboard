"""
TR-09 restoration drill -- actually restore the latest B2 backup and verify
it, not just confirm a backup file exists.

TR-09's amended acceptance criterion is explicit that routine backup
existence "only proves routine existence, not actual disaster recovery
capability" -- it requires "at least one successful, evidenced restoration
test: actually restoring from a backup and verifying the result." This
script is that test, meant to be run once to produce the evidence, and
re-run periodically to keep it current (a backup mechanism can silently rot
-- credentials expire, the bucket gets misconfigured -- exactly like any
other unmonitored path in this codebase).

Restores into an isolated temp directory -- never touches or overwrites the
live psx_data.db or the live docs. Two layers of verification:
  1. restic's own restore already re-verifies every chunk's content hash
     (BLAKE2b) against what was stored -- a corrupted backup fails the
     restore itself, loudly, before this script's own checks even run.
  2. This script adds the semantic layer restic can't: does the restored
     SQLite file actually open and pass PRAGMA integrity_check, does it
     have a plausible amount of data and a plausible latest date, and did
     the three docs restore as non-empty readable text.

Usage:
    python restore_drill_b2.py

Exit code: 0 if every check passes, 1 if any fails. Prints a clear
PASS/FAIL line per check either way -- this is meant to be read by a human,
not just trusted from the exit code.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from backup_to_b2 import RESTIC_REPO, _missing_credentials, _restic_env, BACKUP_TARGETS

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def _run_restic(args: list[str]) -> subprocess.CompletedProcess:
    cmd = ["restic"] + args
    return subprocess.run(cmd, env=_restic_env(), check=True,
                           capture_output=True, text=True, timeout=1800)


def _latest_snapshot_id() -> str:
    import json
    result = _run_restic(["snapshots", "--json", "--tag", "kiran-daily"])
    snapshots = json.loads(result.stdout)
    if not snapshots:
        raise RuntimeError("No snapshots found in the repository -- run backup_to_b2.py first.")
    snapshots.sort(key=lambda s: s["time"])
    latest = snapshots[-1]
    print(f"Latest snapshot: {latest['short_id']} ({latest['time']})")
    return latest["id"]


def _restored_path(restore_root: str, original_path: str) -> str:
    """restic restores preserving the original path structure under the
    target dir (Windows: <target>\\C\\Users\\...). Reconstruct it rather
    than hardcode, so this keeps working if the project ever moves."""
    drive, tail = os.path.splitdrive(os.path.abspath(original_path))
    drive_letter = drive.rstrip(":\\/")
    return os.path.join(restore_root, drive_letter, tail.lstrip("\\/"))


def main() -> int:
    missing = _missing_credentials()
    if missing:
        print(f"FAIL: missing environment variable(s): {', '.join(missing)}")
        return 1

    checks: list[tuple[str, bool, str]] = []
    restore_root = tempfile.mkdtemp(prefix="kiran_restore_drill_")
    print(f"Restoring into isolated scratch dir: {restore_root}")

    try:
        snapshot_id = _latest_snapshot_id()
        _run_restic(["restore", snapshot_id, "--target", restore_root])
        checks.append(("restic restore completed (content-hash verified internally)", True, ""))
    except Exception as exc:
        print(f"FAIL: restore itself failed -- {exc}")
        return 1

    # --- psx_data.db ---
    db_path = _restored_path(restore_root, os.path.join(_PROJECT_DIR, "psx_data.db"))
    if not os.path.exists(db_path):
        checks.append(("psx_data.db restored", False, "file not found after restore"))
    else:
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        checks.append(("psx_data.db restored", True, f"{size_mb:.1f} MB"))
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                result = con.execute("PRAGMA integrity_check").fetchone()[0]
                checks.append(("PRAGMA integrity_check", result == "ok", result))

                price_rows = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
                max_date = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
                checks.append((
                    "prices table plausible",
                    price_rows > 100_000 and max_date is not None,
                    f"{price_rows:,} rows, MAX(date)={max_date}",
                ))
            finally:
                con.close()
        except Exception as exc:
            checks.append(("psx_data.db readable as SQLite", False, str(exc)))

    # --- the 3 gitignored docs ---
    for target in BACKUP_TARGETS[1:]:
        restored = _restored_path(restore_root, target)
        name = os.path.basename(target)
        if not os.path.exists(restored):
            checks.append((f"{name} restored", False, "file not found after restore"))
            continue
        try:
            with open(restored, "r", encoding="utf-8") as f:
                text = f.read()
            checks.append((f"{name} restored", len(text) > 100, f"{len(text):,} chars"))
        except Exception as exc:
            checks.append((f"{name} readable as text", False, str(exc)))

    print()
    print("=== Restoration drill results ===")
    all_ok = True
    for label, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        all_ok = all_ok and ok
        print(f"[{status}] {label}" + (f" -- {detail}" if detail else ""))
    print()

    if all_ok:
        print("Overall: PASS -- restoration verified end-to-end.")
        shutil.rmtree(restore_root, ignore_errors=True)
    else:
        print(f"Overall: FAIL -- scratch dir kept for inspection: {restore_root}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
