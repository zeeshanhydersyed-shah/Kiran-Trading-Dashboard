r"""
Kiran Local-First Migration -- Phase 1, sub-task 6: restore drill for the
Object-Lock archive copy (the widened backup set).

Proves the off-site copy in ``kiran-psx-archive`` can actually be brought back,
not merely that it exists:

  1. Every object carries COMPLIANCE Object-Lock retention (cheap head, no
     download) -- the immutability guarantee is real, not assumed.
  2. The critical artifact -- the whole-DB baseline -- is downloaded to an
     isolated temp dir, decompressed if needed, SHA-256-checked against the
     committed manifest, opened read-only and run through
     ``PRAGMA integrity_check``.
  3. Every small file (Parquet store, both manifests, the 17-file BI set) is
     downloaded and SHA-256-checked.
  4. ``--full`` additionally downloads the folded-in DR-006 baseline and
     hash-checks it.

Large files were zstd-compressed on upload and live as ``<relpath>.zst``; the
drill decompresses and checks the *original* SHA-256 from the manifest.

Never touches the live ``psx_data.db`` or the live ``D:\KIRAN_ARCHIVE``.

    python -m archive.restore_drill_archive           # critical path + all small files
    python -m archive.restore_drill_archive --full    # everything, incl. the big DR-006 .db

Exit 0 if every check passes, 1 otherwise. Callable from ``restore_drill_b2.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile

import boto3
from botocore.config import Config
from compression.zstd import decompress as zstd_decompress

ARCHIVE_ROOT = os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE")
BUCKET = "kiran-psx-archive"
ENDPOINT = "https://s3.us-east-005.backblazeb2.com"
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHA_FILE = os.path.join(REPO_DIR, "docs", "KIRAN_LOCAL_FIRST_ARCHIVE", "BASELINE_MANIFEST.sha256")

_BASELINE = "baseline/psx_data_baseline"
_DR006 = "backup_set/dr006_rehabilitation_baseline/psx_data_baseline_DR006"


def _client():
    return boto3.client(
        "s3", endpoint_url=ENDPOINT,
        aws_access_key_id=os.environ["B2_ARCHIVE_KEY_ID"],
        aws_secret_access_key=os.environ["B2_ARCHIVE_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                      retries={"max_attempts": 8, "mode": "adaptive"},
                      connect_timeout=30, read_timeout=300))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _load_manifest() -> dict[str, str]:
    want = {}
    for line in open(SHA_FILE):
        line = line.strip()
        if line and not line.startswith("#"):
            digest, rel = line.split(None, 1)
            want[rel] = digest
    return want


def _restore_one(s3, key: str, want_sha: str, scratch: str) -> tuple[bool, str]:
    """Download key (maybe .zst), decompress if needed, return (ok, local_path)."""
    dest = os.path.join(scratch, key.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    s3.download_file(BUCKET, key, dest)
    if key.endswith(".zst"):
        raw = dest[:-4]
        with open(dest, "rb") as f:
            data = zstd_decompress(f.read())
        with open(raw, "wb") as f:
            f.write(data)
        dest = raw
    return (_sha256(dest) == want_sha, dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full", action="store_true", help="also download the big DR-006 .db")
    args = ap.parse_args()

    if not os.path.exists(SHA_FILE):
        print(f"FAIL: no committed manifest at {SHA_FILE}")
        return 1
    want = _load_manifest()
    s3 = _client()

    # bucket key -> manifest rel  (accounting for the .zst suffix)
    bkeys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
        for o in page.get("Contents", []):
            if not o["Key"].startswith("_probe/"):
                bkeys.append(o["Key"])
    key_for_rel = {}
    for rel in want:
        key_for_rel[rel] = rel + ".zst" if (rel not in bkeys and rel + ".zst" in bkeys) else rel

    checks: list[tuple[str, bool, str]] = []
    scratch = tempfile.mkdtemp(prefix="kiran_archive_drill_")
    print(f"scratch dir: {scratch}")

    missing = sorted(r for r, k in key_for_rel.items() if k not in bkeys)
    checks.append(("every manifest file present in the bucket", not missing,
                   f"{len(bkeys)} objects; missing: {missing[:5]}"))

    unlocked = []
    for k in bkeys:
        h = s3.head_object(Bucket=BUCKET, Key=k)
        if h.get("ObjectLockMode") != "COMPLIANCE" or not h.get("ObjectLockRetainUntilDate"):
            unlocked.append(k)
    checks.append(("every object under COMPLIANCE Object-Lock", not unlocked,
                   f"unlocked: {unlocked[:5]}" if unlocked else "all locked"))

    # restore set: all small files + the LFM baseline always; DR-006 only with --full
    to_get = []
    for rel, k in key_for_rel.items():
        if k not in bkeys:
            continue
        if rel.startswith(_DR006) and not args.full:
            continue
        to_get.append(rel)

    bad = []
    baseline_local = None
    for rel in to_get:
        ok, path = _restore_one(s3, key_for_rel[rel], want[rel], scratch)
        if not ok:
            bad.append(rel)
        if rel.startswith(_BASELINE) and rel.endswith(".db"):
            baseline_local = path
    checks.append((f"restored files hash-match the manifest ({len(to_get)} files)",
                   not bad, f"mismatched: {bad[:5]}" if bad else "all match"))

    if baseline_local:
        try:
            con = sqlite3.connect(f"file:{baseline_local}?mode=ro", uri=True)
            integ = con.execute("PRAGMA integrity_check").fetchone()[0]
            n = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
            mx = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
            con.close()
            checks.append(("restored baseline .db integrity_check", integ == "ok", integ))
            checks.append(("restored baseline .db plausible",
                           n > 1_000_000 and mx is not None, f"{n:,} price rows, MAX(date)={mx}"))
        except Exception as e:  # noqa: BLE001
            checks.append(("restored baseline .db opens as SQLite", False, str(e)))
    else:
        checks.append(("baseline .db in restore set", False, "not found"))

    print("\n=== Archive restore drill ===")
    ok = True
    for label, passed, detail in checks:
        ok = ok and passed
        print(f"[{'PASS' if passed else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    if ok:
        print("\nOverall: PASS -- off-site archive restore verified.")
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"\nOverall: FAIL -- scratch kept: {scratch}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
