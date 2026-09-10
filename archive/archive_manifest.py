r"""
Kiran Local-First Migration -- Phase 1 immutable-baseline manifest (SEQ-1).

Two modes:

    python -m archive.archive_manifest generate    # (re)write the manifest files
    python -m archive.archive_manifest verify      # re-hash every file, compare

The archive lives OUTSIDE the repo (default ``D:\KIRAN_ARCHIVE`` -- C: is space
constrained). Only the two manifest files are committed to git:

    docs/KIRAN_LOCAL_FIRST_ARCHIVE/BASELINE_MANIFEST.sha256   (machine-checkable)
    docs/KIRAN_LOCAL_FIRST_ARCHIVE/BASELINE_MANIFEST.md       (human-readable)

The bulk artifacts (the whole-DB baseline, the Parquet store, the folded-in
DR-006 baseline and BI preservation set) are protected by (a) these committed
hashes, (b) a Backblaze B2 Object-Lock copy, and (c) a scheduled run of
``verify`` (see ``archive_checksum_check`` / Task Scheduler).

D7 (owner, 2026-09-09): SEQ-1 is preservation only. Nothing here mutates,
corrects, or re-scrapes a historical row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import sys

ARCHIVE_ROOT = os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE")
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_DIR = os.path.join(REPO_DIR, "docs", "KIRAN_LOCAL_FIRST_ARCHIVE")
SHA_FILE = os.path.join(MANIFEST_DIR, "BASELINE_MANIFEST.sha256")
MD_FILE = os.path.join(MANIFEST_DIR, "BASELINE_MANIFEST.md")

# Transient / non-baseline paths under ARCHIVE_ROOT (dot-dirs and dot-files are
# excluded wholesale -- .offsite_state/, .offsite_push.log, etc.).
EXCLUDE_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".log")
EXCLUDE_EXACT = {"BASELINE_MANIFEST.sha256", "BASELINE_MANIFEST.md",
                 "OFFSITE_MANIFEST.json"}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_archive() -> list[str]:
    out = []
    for root, dirs, files in os.walk(ARCHIVE_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.endswith(EXCLUDE_SUFFIXES) or name.startswith("."):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, ARCHIVE_ROOT).replace("\\", "/")
            if rel in EXCLUDE_EXACT:
                continue
            out.append(rel)
    return sorted(out)


def hash_all() -> list[tuple[str, str, int]]:
    rows = []
    for rel in walk_archive():
        full = os.path.join(ARCHIVE_ROOT, rel.replace("/", os.sep))
        rows.append((rel, sha256(full), os.path.getsize(full)))
    return rows


def cmd_generate() -> int:
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    rows = hash_all()
    now = dt.datetime.now().isoformat(timespec="seconds")
    total = sum(sz for _, _, sz in rows)

    with open(SHA_FILE, "w", newline="\n") as f:
        f.write(f"# Kiran Local-First archive -- BASELINE_MANIFEST.sha256\n")
        f.write(f"# generated {now}  root={ARCHIVE_ROOT}  files={len(rows)}  bytes={total}\n")
        for rel, digest, _ in rows:
            f.write(f"{digest}  {rel}\n")

    groups: dict[str, list[tuple[str, str, int]]] = {}
    for rel, digest, sz in rows:
        top = rel.split("/", 1)[0]
        groups.setdefault(top, []).append((rel, digest, sz))

    with open(MD_FILE, "w", newline="\n") as f:
        f.write("# Kiran Local-First Migration -- Immutable Baseline Manifest (SEQ-1)\n\n")
        f.write(f"- **Generated:** {now}\n")
        f.write(f"- **Archive root:** `{ARCHIVE_ROOT}` (off-repo; C: is space-constrained)\n")
        f.write(f"- **Files:** {len(rows)} &nbsp;|&nbsp; **Total bytes:** {total:,}\n")
        f.write("- **Authorization:** `KIRAN_LOCAL_FIRST_MIGRATION` Phase 1 / DR-program SEQ-1. "
                "Owner decision D7 (2026-09-09): *preservation only* -- no historical row is "
                "mutated, corrected, or re-scraped.\n")
        f.write("- **Machine-checkable copy:** `BASELINE_MANIFEST.sha256` (same directory).\n")
        f.write("- **Verify:** `python -m archive.archive_manifest verify` "
                "(re-hashes every file under the archive root and compares).\n\n")

        f.write("## Contents\n\n")
        f.write("| Group | What it is | Files | Bytes |\n|---|---|---|---|\n")
        desc = {
            "baseline": "Whole-DB immutable point-in-time snapshot of live `psx_data.db` "
                        "(all 53 tables) captured via the SQLite Online Backup API + its capture report",
            "bronze": "Raw OHLCV substrate as Parquet (`prices`, `index_prices`), partitioned by year -- source of truth for price",
            "silver": "CA-adjusted prices + universe as Parquet (`prices_adjusted`, `sectors`, `stock_metadata`), as-captured",
            "backup_set": "Folded-in prior frozen artifacts: the DR-006 rehabilitation baseline and the 17-file BI source-preservation set",
            "STORE_MANIFEST.json": "Per-table row counts / column lists / per-file hashes for the Parquet store",
        }
        for top in sorted(groups):
            g = groups[top]
            f.write(f"| `{top}` | {desc.get(top, '')} | {len(g)} | {sum(s for _,_,s in g):,} |\n")

        f.write("\n## Provenance of the folded-in members\n\n")
        f.write("- **`backup_set/dr006_rehabilitation_baseline/`** -- the DR program's frozen "
                "rehabilitation baseline, captured 2026-09-04 (elevated session). Canonical original "
                "remains at `C:\\Users\\Lenovo\\ZH_Research_PSX\\trading_edge_program\\rehabilitation_baseline\\`. "
                "Expected SHA-256 of the `.db`: `c03a393f44e4d3a73978784e8c47a0dc6729c2af8362377f7daee76859c9a8e0`. "
                "NOTE: the capture *report* in `loop_dr_006/` still reads 'STOPPED -- no baseline captured'; "
                "that report predates the successful elevated attempt and is stale.\n")
        f.write("- **`backup_set/bi_source_preservation_20260903/`** -- DR-003 Phase A BI application + "
                "data preservation set (17 files). Verified here against its own "
                "`PRESERVATION_MANIFEST.sha256` (17/17 match) before folding in. Canonical original at "
                "`...\\trading_edge_program\\loop_dr_003\\bi_source_preservation_20260903\\`.\n\n")

        f.write("## Full file list\n\n")
        for top in sorted(groups):
            f.write(f"### `{top}`\n\n```\n")
            for rel, digest, sz in groups[top]:
                f.write(f"{digest}  {rel}  ({sz:,} b)\n")
            f.write("```\n\n")

    print(f"wrote {SHA_FILE}")
    print(f"wrote {MD_FILE}")
    print(f"{len(rows)} files, {total:,} bytes")
    return 0


def cmd_verify() -> int:
    if not os.path.exists(SHA_FILE):
        print(f"NO MANIFEST at {SHA_FILE} -- run `generate` first")
        return 2
    want: dict[str, str] = {}
    for line in open(SHA_FILE):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        want[rel] = digest

    have = {rel: digest for rel, digest, _ in hash_all()}
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    changed = sorted(r for r in want.keys() & have.keys() if want[r] != have[r])

    for r in missing:
        print(f"  MISSING   {r}")
    for r in extra:
        print(f"  UNTRACKED {r}")
    for r in changed:
        print(f"  CHANGED   {r}")

    ok = not (missing or extra or changed)
    print(f"\n{'PASS' if ok else 'FAIL'} -- {len(want)} tracked, "
          f"{len(missing)} missing, {len(extra)} untracked, {len(changed)} changed")
    return 0 if ok else 1


def cmd_protect(readonly: bool) -> int:
    """Set (or clear) the read-only bit on every baseline payload file, so
    nothing modifies the archive in place. Operational metadata
    (OFFSITE_MANIFEST.json, .offsite_state/) is left writable -- walk_archive()
    already excludes it."""
    import stat
    n = 0
    for rel in walk_archive():
        p = os.path.join(ARCHIVE_ROOT, rel.replace("/", os.sep))
        cur = os.stat(p).st_mode
        os.chmod(p, (cur & ~0o222) if readonly else (cur | 0o200))
        n += 1
    print(f"{'read-only' if readonly else 'writable'} set on {n} files under {ARCHIVE_ROOT}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["generate", "verify", "protect", "unprotect"])
    args = ap.parse_args()
    if args.mode == "generate":
        return cmd_generate()
    if args.mode == "verify":
        return cmd_verify()
    return cmd_protect(readonly=(args.mode == "protect"))


if __name__ == "__main__":
    sys.exit(main())
