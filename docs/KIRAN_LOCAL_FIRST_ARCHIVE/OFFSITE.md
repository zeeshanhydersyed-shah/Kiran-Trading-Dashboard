# Kiran Local-First archive — off-site Object-Lock copy

Phase 1, sub-task 4 of the [local-first migration](../KIRAN_LOCAL_FIRST_MIGRATION.md).
Records where the immutable baseline lives off this machine and how to get it back.

## Where it is

| | |
|---|---|
| Provider | Backblaze B2, S3-compatible API |
| Bucket | `kiran-psx-archive` (`allPrivate`, **Object Lock enabled**) |
| Endpoint | `https://s3.us-east-005.backblazeb2.com` |
| Layout | one object per file, key = path relative to `D:\KIRAN_ARCHIVE\` (e.g. `baseline/psx_data_baseline_KIRAN_LFM_P1_<ts>.db`) |
| Retention | **COMPLIANCE** mode, **3000 days** per object (B2's maximum), set at upload |
| Credentials | `B2_ARCHIVE_KEY_ID` / `B2_ARCHIVE_KEY` — local user env vars, key scoped to this one bucket, never committed |

**COMPLIANCE mode = the copy cannot be deleted or its retention shortened by
anyone — not this key, not the account owner, not Backblaze — before the
retain-until date.** `deleteObject` without a version id only writes a
delete-marker (a visibility hide, fully reversible); every real version stays
locked and is recoverable by `list_object_versions` + `VersionId`.

## Why not restic

The daily `psx_data.db` backup (`backup_to_b2.py`) uses restic in the separate
`kiran-psx-backups` bucket. restic constantly creates and deletes lock/index
objects — a COMPLIANCE rule would pin those permanently and wedge the repo. A
flat one-object-per-file upload with per-object retention has no moving parts
and matches the write-once nature of a baseline.

## Tooling

| Command | Does |
|---|---|
| `python -m archive.offsite_push` | Upload every archive file with COMPLIANCE lock + retain-until; resumable (skips objects already present with a matching size and `x-amz-meta-sha256`); writes `D:\KIRAN_ARCHIVE\OFFSITE_MANIFEST.json` |
| `python -m archive.offsite_push --verify` | Verify only — every local file has a locked bucket version whose stored hash matches |
| `python -m archive.restore_drill_archive` | Restore drill: lock check on every object + download & hash-verify the critical path (baseline `.db` + all small files) + `integrity_check` the restored `.db` |
| `python -m archive.restore_drill_archive --full` | …plus download & hash-check the 882 MB DR-006 baseline |
| `python restore_drill_b2.py` | Runs the restic daily-backup drill **and** the archive drill above — one command, combined verdict |

## Recovery, from nothing

1. Set `B2_ARCHIVE_KEY_ID` / `B2_ARCHIVE_KEY` (or any B2 key that can read the bucket).
2. `pip install boto3`
3. `python -m archive.restore_drill_archive --full` — this downloads everything
   into a temp dir and verifies it; copy it out, or adapt the few `download_file`
   lines. The committed `BASELINE_MANIFEST.sha256` is the hash authority.

## `_probe/lock_test.txt`

A 32-byte object written once while verifying that COMPLIANCE lock actually
blocks deletes. It is itself locked (~3000 days) and cannot be removed. Ignored
by all archive tooling. Harmless.
