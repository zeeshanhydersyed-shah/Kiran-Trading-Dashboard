"""TR-05 Blocker 2 observability -- serving-revision identity only, not a gate.

Split out of dashboard.py into its own module for one reason: dashboard.py
cannot be plain-imported (it runs st.set_page_config() and secrets/DB
bridging at module level -- every existing test that touches it uses
Streamlit's AppTest harness, never a bare `import dashboard`). Keeping this
logic here makes it a pure, dependency-free function that unit tests can
import and call directly, with temp directories standing in for .git --
no Streamlit, no database, no AppTest.
"""
from __future__ import annotations

import os


def get_serving_revision(repo_dir=None):
    """Read the exact git HEAD of the checkout serving this process.

    Reads live from disk on every call (no caching). Pure stdlib -- no
    GitPython, no new dependency, no subprocess/`git`-binary requirement:
    Streamlit Cloud deploys by cloning the repo, so .git is expected to be
    present on disk even if the `git` executable itself is not on PATH at
    runtime.

    Deliberately never falls back to origin/main, a cached value, a
    different checkout, or a manually maintained string: if .git can't be
    read for any reason, the caller must show an explicit UNKNOWN, not a
    guess -- this function returns None in every such case, never a
    substitute value.

    repo_dir: directory to look for .git in. Defaults to this file's own
    directory (i.e. the actual deployed checkout dashboard.py runs from),
    not the process cwd. Overridable so tests can point at a temp directory
    without touching the real repository.
    """
    try:
        if repo_dir is None:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
        git_dir = os.path.join(repo_dir, ".git")
        head_path = os.path.join(git_dir, "HEAD")
        if not os.path.isfile(head_path):
            return None
        with open(head_path, "r", encoding="utf-8") as f:
            head = f.read().strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1].strip()
            ref_path = os.path.join(git_dir, ref)
            sha = None
            if os.path.isfile(ref_path):
                with open(ref_path, "r", encoding="utf-8") as f:
                    sha = f.read().strip()
            else:
                packed_path = os.path.join(git_dir, "packed-refs")
                if os.path.isfile(packed_path):
                    with open(packed_path, "r", encoding="utf-8") as f:
                        for line in f:
                            parts = line.strip().split()
                            if len(parts) == 2 and parts[1] == ref:
                                sha = parts[0]
                                break
        else:
            sha = head  # detached HEAD -- HEAD itself is the SHA
        if sha and len(sha) == 40 and all(c in "0123456789abcdefABCDEF" for c in sha):
            return sha.lower()
        return None
    except Exception:
        return None
