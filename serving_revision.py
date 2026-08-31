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


def _is_sha40(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(c in "0123456789abcdef" for c in value.lower())
    )


def resolve_code_version(repo_dir=None):
    """The commit SHA of the code producing the current run, or None.

    Order of preference, each an exact fact, never a guess:
      1. $GITHUB_SHA -- set automatically on every GitHub Actions runner; the
         canonical identity of the commit a `schedule` / `workflow_dispatch`
         run checked out (always origin/main HEAD for those events, since the
         workflows use a bare `actions/checkout@v4`).
      2. get_serving_revision() -- the serving checkout's own .git/HEAD, for
         the Streamlit Cloud / local processes that are not Actions runners.
      3. None -- if neither is available. Never origin/main, never a cached
         string, never a substitute (same contract as get_serving_revision).

    Used to stamp pipeline_runs.code_version on every production run
    (KIRAN_CLEANUP_AUDIT.md 88, Trust Register OI-9 / TR-11).
    """
    try:
        sha = os.environ.get("GITHUB_SHA")
        if sha:
            sha = sha.strip().lower()
            if _is_sha40(sha):
                return sha
    except Exception:
        pass
    return get_serving_revision(repo_dir=repo_dir)


def describe_drift(serving_sha, pipeline_sha):
    """(level, message) for the Data Health "is the served code current?" check.

    Compares the code THIS dashboard process is serving (serving_sha, from
    get_serving_revision()) against the code the pipeline that produced the
    currently-displayed data actually ran (pipeline_sha, from
    data_health.latest_pipeline_code_version()).

    level is one of:
      'unknown' -- serving revision could not be read at all
      'pending' -- no pipeline run has recorded a code_version yet
      'match'   -- the two agree; the dashboard is serving current code
      'drift'   -- they differ; on Streamlit Cloud this means an in-place
                   redeploy did not recycle the serving process
                   (KIRAN_CLEANUP_AUDIT.md 62 / 78) and a full reboot is needed

    Pure -- no I/O, unit-testable in isolation.
    """
    if not serving_sha:
        return ("unknown",
                "Serving revision UNKNOWN -- cannot verify the dashboard is "
                "running current code.")
    if not pipeline_sha:
        return ("pending",
                "The pipeline has not recorded a code version yet -- the "
                "serving-vs-pipeline drift check becomes available after the "
                "next production run.")
    if serving_sha == pipeline_sha:
        return ("match",
                f"Serving code matches the pipeline ({serving_sha[:7]}).")
    return ("drift",
            f"The dashboard is serving {serving_sha[:7]} but the latest "
            f"pipeline run used {pipeline_sha[:7]}. A Cloud reboot (not a "
            f"redeploy) is needed to serve current code.")
