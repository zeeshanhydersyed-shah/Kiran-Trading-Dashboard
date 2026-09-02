"""
TR-01 / TR-09 -- daily offsite backup of Kiran's local, durable state to
Backblaze B2 via restic.

Why this exists: `psx_data.db` is the permanent full-history archive (per
CLAUDE.md -- Postgres is the rolling ~2-year operational copy, SQLite is the
one with the full history back to 2005 and no automated recreation path).
Losing this machine's disk without an independent copy would be a real,
currently-unrecovered historical-data loss (flagged repeatedly in the TR-01
ledger entries, never actually closed until now). Three more files are
`.gitignore`'d and exist ONLY on this machine -- the Trust Register itself
and two other audit docs -- found while scoping this exact task (2026-09-02)
and folded in, since TR-09's own acceptance criterion names "the audit
ledger" as a required-to-keep asset, not just the database.

Deliberately excludes backups/ (34 manual pre-write snapshots, ~11GB) --
owner decision 2026-09-02: those are one-off undo points for specific past
operations, most already superseded, not an ongoing archive. Backing them
all up would ~10x the transfer for little real protection; psx_data.db
itself is the thing whose loss would actually be catastrophic.

Credentials: B2_ACCOUNT_ID / B2_ACCOUNT_KEY (a restricted key scoped to one
bucket, not the master key -- owner decision, TR-01 spec) and
RESTIC_PASSWORD (the repo's own client-side encryption key -- unrelated to
B2 auth; losing it makes the backup permanently unrecoverable even with
valid B2 credentials) are all read from the environment, set once as local
user environment variables by the owner. This script never sees, logs, or
handles the actual values -- it maps them onto the AWS_* names restic's S3
backend expects (see _restic_env()) and passes them straight through.

Backend note (2026-09-02, ledger §105.4): restic's *native* `b2:` backend
returned `b2_list_buckets: 401` against this account's restricted key even
though the key's own capabilities genuinely include listBuckets (confirmed
directly against B2's API) -- restic's own docs name this as a known class
of issue ("issues with error handling in the current B2 library that restic
uses") and recommend B2's S3-compatible API instead, which is what this
script actually uses. B2_ACCOUNT_ID/B2_ACCOUNT_KEY work unchanged as
S3-style credentials -- Backblaze accepts the same application key pair for
both APIs, no new key needed.

Usage:
    python backup_to_b2.py              # real backup + prune
    python backup_to_b2.py --dry-run    # restic --dry-run, no data moved/deleted
    python backup_to_b2.py --init-only  # just ensure the repo exists, do nothing else

Exit code: 0 on success, 1 on any failure -- Task Scheduler / a human
checking `echo %errorlevel%` both need this to be honest.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backup_to_b2")

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Not secrets -- a bucket name, this account's fixed B2 S3-compatible
# endpoint (confirmed directly against the b2_authorize_account API,
# 2026-09-02 -- tied to which storage cluster the account was provisioned
# on, does not change), and a repo path prefix inside the bucket. Same
# comfort level as this repo already hardcodes non-secret config (config.py).
B2_BUCKET = "kiran-psx-backups"
B2_S3_ENDPOINT = "s3.us-east-005.backblazeb2.com"
RESTIC_REPO = f"s3:https://{B2_S3_ENDPOINT}/{B2_BUCKET}/restic-repo"

# The actual backup scope, owner-agreed 2026-09-02 -- see module docstring.
BACKUP_TARGETS = [
    os.path.join(_PROJECT_DIR, "psx_data.db"),
    os.path.join(_PROJECT_DIR, "docs", "KIRAN_BORING_STATE_TRUST_REGISTER.md"),
    os.path.join(_PROJECT_DIR, "docs", "KIRAN_CLOUD_RELIABILITY_AUDIT.md"),
    os.path.join(_PROJECT_DIR, "docs", "KIRAN_SQLITE_ONLY_SCOPING.md"),
]

# Generous, not enterprise -- TR-09's own framing ("the bar is 'can Kiran
# actually get back', proven once, not merely asserted"). 30 daily + 12
# weekly + 12 monthly snapshots comfortably covers the 24h RPO the owner set
# while keeping years of monthly checkpoints without unbounded growth.
RETENTION_ARGS = [
    "--keep-daily", "30",
    "--keep-weekly", "12",
    "--keep-monthly", "12",
]

# Shared infra from TR-18 (ledger §100/§102) -- not a secret, a routing
# address; reused rather than provisioning a second channel for the same
# owner's phone.
NTFY_TOPIC = "kiran-psx-alerts-7g3k9qx2mp"


def _restic_env() -> dict:
    """restic's S3 backend reads AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, not
    B2_ACCOUNT_ID/B2_ACCOUNT_KEY -- Backblaze's own application keys work
    unchanged as S3-style credentials (confirmed live against the account),
    so this just renames them in the subprocess's env without ever reading
    or logging the actual values in this process."""
    env = os.environ.copy()
    env["RESTIC_REPOSITORY"] = RESTIC_REPO
    if env.get("B2_ACCOUNT_ID"):
        env["AWS_ACCESS_KEY_ID"] = env["B2_ACCOUNT_ID"]
    if env.get("B2_ACCOUNT_KEY"):
        env["AWS_SECRET_ACCESS_KEY"] = env["B2_ACCOUNT_KEY"]
    return env


def _run_restic(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """One restic invocation. Never logs the command's env (credentials
    live there, not in argv) -- only the argv itself, which never contains
    a secret (restic takes all three credentials from the environment)."""
    cmd = ["restic"] + args
    logger.info("restic %s", " ".join(args))
    return subprocess.run(
        cmd, env=_restic_env(), check=check,
        capture_output=True, text=True, timeout=1800,
    )


def _missing_credentials() -> list[str]:
    return [name for name in ("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY", "RESTIC_PASSWORD")
            if not os.environ.get(name)]


def ensure_repo_initialized() -> None:
    """Idempotent: `restic snapshots` succeeding means the repo already
    exists; only `restic init` if that check fails. Never re-initializes an
    existing repo (which would be a silent no-op anyway, but the explicit
    check makes the log line honest about what actually happened)."""
    probe = _run_restic(["snapshots", "--json"], check=False)
    if probe.returncode == 0:
        logger.info("Repository already initialized.")
        return
    logger.info("Repository not found -- initializing %s", RESTIC_REPO)
    _run_restic(["init"])
    logger.info("Repository initialized.")


def run_backup(dry_run: bool = False) -> subprocess.CompletedProcess:
    missing = [t for t in BACKUP_TARGETS if not os.path.exists(t)]
    if missing:
        raise FileNotFoundError(f"Backup target(s) not found: {missing}")

    args = ["backup"] + BACKUP_TARGETS + ["--tag", "kiran-daily"]
    if dry_run:
        args.append("--dry-run")
    result = _run_restic(args)
    logger.info(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "backup: no output")
    return result


def prune_old_snapshots(dry_run: bool = False) -> None:
    args = ["forget"] + RETENTION_ARGS + ["--tag", "kiran-daily"]
    if not dry_run:
        args.append("--prune")
    else:
        args.append("--dry-run")
    _run_restic(args)
    logger.info("Retention policy applied (%s).", "dry-run" if dry_run else "pruned")


def _alert_failure(reason: str) -> None:
    """Best-effort push via the already-provisioned ntfy topic. Never raises
    -- an alert failing must not mask the real backup failure it's reporting."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"Kiran B2 backup FAILED: {reason}".encode("utf-8"),
            headers={
                "Title": "Kiran B2 backup FAILED",
                "Priority": "high",
                "Tags": "warning",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        logger.warning("ntfy alert failed (not fatal): %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="restic --dry-run for both backup and forget -- moves/deletes nothing")
    parser.add_argument("--init-only", action="store_true",
                         help="only ensure the repository exists, do not back up or prune")
    args = parser.parse_args()

    missing = _missing_credentials()
    if missing:
        logger.error("Missing required environment variable(s): %s -- "
                      "see README/CLAUDE.md for setup.", ", ".join(missing))
        return 1

    try:
        ensure_repo_initialized()
        if args.init_only:
            return 0
        run_backup(dry_run=args.dry_run)
        prune_old_snapshots(dry_run=args.dry_run)
        logger.info("Backup complete.")
        return 0
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()[-500:]
        logger.error("Backup FAILED (restic exit %s): %s", exc.returncode, detail)
        _alert_failure(f"restic exit {exc.returncode}: {detail[:200]}")
        return 1
    except Exception as exc:
        logger.error("Backup FAILED: %s", exc)
        _alert_failure(str(exc)[:200])
        return 1


if __name__ == "__main__":
    sys.exit(main())
