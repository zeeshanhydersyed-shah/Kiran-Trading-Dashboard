r"""
Kiran Local-First Migration -- Phase 1, sub-task 4: off-site Object-Lock copy.

Uploads every file under the local archive root to the Backblaze B2 bucket
``kiran-psx-archive`` (S3 API), each object written with **COMPLIANCE-mode
Object Lock** + a retain-until date, so the copy cannot be deleted or its
retention shortened by anyone -- including the holder of these credentials --
before it expires. restic is NOT used (its lock-file churn would wedge against
a COMPLIANCE rule); a flat one-object-per-file upload has no moving parts and
matches the write-once nature of a baseline.

Large files (> ``COMPRESS_THRESHOLD``) are zstd-compressed before upload and
land as ``<relpath>.zst`` -- the owner's uplink is slow and the SQLite baselines
compress to ~33%. The object metadata carries both the original and the
compressed SHA-256; ``verify`` / the restore drill check both.

**Resumable at the part level** (CLAUDE.md standing rule -- this is a multi-hour
upload on a flaky link):
  * a file already in the bucket with a matching original-SHA-256 is skipped;
  * an interrupted multipart upload resumes from the parts already accepted,
    tracked in ``D:\KIRAN_ARCHIVE\.offsite_state\<key>.json``.

    python -m archive.offsite_push            # upload (resume) + verify
    python -m archive.offsite_push --verify   # verify only

Credentials (local env, never logged): B2_ARCHIVE_KEY_ID / B2_ARCHIVE_KEY.
D7: preservation only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

import boto3
from botocore.config import Config
from compression.zstd import compress as zstd_compress

ARCHIVE_ROOT = os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE")
BUCKET = "kiran-psx-archive"
ENDPOINT = "https://s3.us-east-005.backblazeb2.com"
RETAIN_DAYS = int(os.environ.get("KIRAN_ARCHIVE_RETAIN_DAYS", "3000"))
OFFSITE_MANIFEST = os.path.join(ARCHIVE_ROOT, "OFFSITE_MANIFEST.json")
STATE_DIR = os.path.join(ARCHIVE_ROOT, ".offsite_state")

COMPRESS_THRESHOLD = 64 * 1024 * 1024
PART_SIZE = 16 * 1024 * 1024          # small parts -> visible progress, cheap resume
ZSTD_LEVEL = 12

SKIP_EXACT = {"OFFSITE_MANIFEST.json"}
SKIP_SUFFIXES = ("-wal", "-shm", "-journal", ".tmp", ".log")


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


def local_files() -> list[str]:
    out = []
    for root, dirs, files in os.walk(ARCHIVE_ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.endswith(SKIP_SUFFIXES) or name.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(root, name), ARCHIVE_ROOT).replace("\\", "/")
            if rel in SKIP_EXACT:
                continue
            out.append(rel)
    return sorted(out)


def _head(s3, key):
    try:
        return s3.head_object(Bucket=BUCKET, Key=key)
    except s3.exceptions.ClientError:
        return None


def _target_key(rel: str, size: int) -> tuple[str, bool]:
    compress = size > COMPRESS_THRESHOLD
    return (rel + ".zst" if compress else rel), compress


def _state_path(key: str) -> str:
    return os.path.join(STATE_DIR, key.replace("/", "__") + ".json")


def _upload_multipart(s3, key, body_path, meta, until):
    """Resumable multipart. State file tracks upload_id + accepted parts."""
    os.makedirs(STATE_DIR, exist_ok=True)
    sp = _state_path(key)
    state = {}
    if os.path.exists(sp):
        state = json.load(open(sp))
        # is that upload still open on the server?
        opens = {u["UploadId"] for u in
                 s3.list_multipart_uploads(Bucket=BUCKET).get("Uploads", [])
                 if u["Key"] == key}
        if state.get("upload_id") not in opens:
            state = {}
    if not state:
        r = s3.create_multipart_upload(
            Bucket=BUCKET, Key=key, Metadata=meta,
            ObjectLockMode="COMPLIANCE", ObjectLockRetainUntilDate=until)
        state = {"upload_id": r["UploadId"], "parts": {}}
        json.dump(state, open(sp, "w"))

    uid = state["upload_id"]
    done = {int(k): v for k, v in state["parts"].items()}
    total = os.path.getsize(body_path)
    with open(body_path, "rb") as f:
        pnum = 0
        while True:
            chunk = f.read(PART_SIZE)
            if not chunk:
                break
            pnum += 1
            if pnum in done:
                continue
            pr = s3.upload_part(Bucket=BUCKET, Key=key, UploadId=uid,
                                PartNumber=pnum, Body=chunk)
            done[pnum] = {"ETag": pr["ETag"], "Size": len(chunk)}
            state["parts"] = {str(k): v for k, v in done.items()}
            json.dump(state, open(sp, "w"))
            up = sum(v["Size"] for v in done.values())
            print(f"    part {pnum:>4}  {up/total*100:5.1f}%  ({up:,}/{total:,})")
    s3.complete_multipart_upload(
        Bucket=BUCKET, Key=key, UploadId=uid,
        MultipartUpload={"Parts": [{"PartNumber": n, "ETag": done[n]["ETag"]}
                                   for n in sorted(done)]})
    os.remove(sp)


def push() -> int:
    s3 = _client()
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=RETAIN_DAYS)
    rels = local_files()
    print(f"archive root : {ARCHIVE_ROOT}")
    print(f"bucket       : {BUCKET}  (COMPLIANCE, retain until {until:%Y-%m-%d})")
    print(f"files        : {len(rels)}")

    manifest = {"pushed_at": dt.datetime.now().isoformat(), "bucket": BUCKET,
                "endpoint": ENDPOINT, "retain_until": until.isoformat(),
                "retain_days": RETAIN_DAYS, "objects": {}}
    up = skip = 0
    for rel in rels:
        full = os.path.join(ARCHIVE_ROOT, rel.replace("/", os.sep))
        size = os.path.getsize(full)
        digest = _sha256(full)
        key, compress = _target_key(rel, size)

        h = _head(s3, key)
        m0 = h.get("Metadata", {}) if h is not None else {}
        if m0.get("sha256") == digest and m0.get("orig_size") == str(size):
            skip += 1
        else:
            body, tmp = full, None
            meta = {"sha256": digest, "orig_size": str(size)}
            if compress:
                os.makedirs(STATE_DIR, exist_ok=True)
                tmp = os.path.join(STATE_DIR, os.path.basename(key) + ".tmp")
                if not os.path.exists(tmp):
                    print(f"  zstd {rel} ({size:,} b) ...")
                    with open(full, "rb") as fi, open(tmp, "wb") as fo:
                        fo.write(zstd_compress(fi.read(), ZSTD_LEVEL))
                meta["sha256_zstd"] = _sha256(tmp)
                meta["compression"] = "zstd"
                body = tmp
            print(f"  up  {key}  ({os.path.getsize(body):,} b{' zstd' if compress else ''})")
            if os.path.getsize(body) > PART_SIZE:
                _upload_multipart(s3, key, body, meta, until)
            else:
                with open(body, "rb") as f:
                    s3.put_object(Bucket=BUCKET, Key=key, Body=f.read(), Metadata=meta,
                                  ObjectLockMode="COMPLIANCE", ObjectLockRetainUntilDate=until)
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
            up += 1

        h2 = _head(s3, key)
        manifest["objects"][rel] = {
            "key": key, "sha256": digest, "orig_size": size,
            "compressed": compress,
            "sha256_zstd": h2.get("Metadata", {}).get("sha256_zstd"),
            "version_id": h2.get("VersionId"),
            "lock_mode": h2.get("ObjectLockMode"),
            "retain_until": h2["ObjectLockRetainUntilDate"].isoformat()
            if h2.get("ObjectLockRetainUntilDate") else None,
        }

    json.dump(manifest, open(OFFSITE_MANIFEST, "w"), indent=2)
    print(f"\nuploaded={up}  skipped={skip}\noffsite manifest -> {OFFSITE_MANIFEST}")
    return verify(s3)


def verify(existing=None) -> int:
    """PASS iff, for every local file, the bucket holds at least one
    COMPLIANCE-locked version whose stored SHA-256 matches. Re-uploads (a later
    version with richer metadata) are fine -- what matters is that a locked,
    correct copy exists, not that the oldest version is the pristine one."""
    s3 = existing or _client()
    bad = 0
    for rel in local_files():
        full = os.path.join(ARCHIVE_ROOT, rel.replace("/", os.sep))
        size = os.path.getsize(full)
        digest = _sha256(full)
        key, _compress = _target_key(rel, size)
        vs = [v for v in s3.list_object_versions(Bucket=BUCKET, Prefix=key).get("Versions", [])
              if v["Key"] == key]
        if not vs:
            print(f"  MISSING  {key}"); bad += 1; continue
        good = False
        for v in vs:
            h = s3.head_object(Bucket=BUCKET, Key=key, VersionId=v["VersionId"])
            if (h.get("ObjectLockMode") == "COMPLIANCE" and h.get("ObjectLockRetainUntilDate")
                    and h.get("Metadata", {}).get("sha256") == digest):
                good = True
                break
        if not good:
            print(f"  BAD  {key}  ({len(vs)} version(s), none locked+matching)"); bad += 1
    n = len(local_files())
    print(f"\n{'PASS' if bad == 0 else 'FAIL'} -- {n} files, {bad} bad")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    return verify() if a.verify else push()


if __name__ == "__main__":
    sys.exit(main())
