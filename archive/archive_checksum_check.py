r"""
Kiran Local-First Migration -- Phase 1, scheduled integrity check.

Thin wrapper around ``archive.archive_manifest verify`` for Task Scheduler:
re-hashes every file under the archive root, compares to the git-committed
``BASELINE_MANIFEST.sha256``, and pushes an ntfy alert on any drift (missing,
untracked, or changed file). Exit code 0 = clean, 1 = drift, 2 = no manifest.

Schedule (local machine only, weekly is plenty for a write-once baseline):
    schtasks /Create /TN "KIRAN_Archive_Checksum" /TR ^
      "python -m archive.archive_checksum_check" /SC WEEKLY /D SUN /ST 21:30

Reuses the existing ntfy topic from TR-18 / backup_to_b2.py -- a routing
address, not a secret.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

from archive import archive_manifest

NTFY_TOPIC = "kiran-psx-alerts-7g3k9qx2mp"


def _alert(title: str, body: str) -> None:
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "warning"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001 -- alert failure must not mask the result
        print(f"ntfy alert failed (not fatal): {exc}")


def main() -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = archive_manifest.cmd_verify()
    out = buf.getvalue()
    print(out)
    if rc != 0:
        tail = "\n".join(out.strip().splitlines()[-15:])
        _alert("Kiran archive checksum DRIFT", f"verify rc={rc}\n{tail}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
