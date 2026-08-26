"""TR-05 Blocker 2 observability -- serving_revision.get_serving_revision().

Pure unit tests: no Streamlit, no AppTest, no database of any kind. All
scenarios use temp directories standing in for .git, so nothing here can
touch the real repository or production data.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from serving_revision import get_serving_revision

VALID_SHA = "09cdfdb5be148f7da58cee20b8ee16049b36148a"
OTHER_SHA = "ffdccf9edf70692714f91b72b79e8302874c8c07"


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_returns_sha_for_symbolic_ref_head(tmp_path):
    """Normal case: HEAD -> refs/heads/main, ref file holds the SHA."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
    _write(os.path.join(repo, ".git", "refs", "heads", "main"), VALID_SHA + "\n")

    assert get_serving_revision(repo_dir=repo) == VALID_SHA


def test_returns_sha_for_detached_head(tmp_path):
    """CI/deploy checkouts are commonly detached HEAD -- HEAD holds the SHA directly."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), VALID_SHA + "\n")

    assert get_serving_revision(repo_dir=repo) == VALID_SHA


def test_falls_through_to_packed_refs(tmp_path):
    """Loose ref file absent (normal after `git gc`) -- must resolve via packed-refs."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
    _write(
        os.path.join(repo, ".git", "packed-refs"),
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{OTHER_SHA} refs/heads/some-other-branch\n"
        f"{VALID_SHA} refs/heads/main\n",
    )

    assert get_serving_revision(repo_dir=repo) == VALID_SHA


def test_no_git_directory_returns_none(tmp_path):
    """Fail-safe: no .git at all -> None, never a substitute value."""
    repo = str(tmp_path)  # empty directory, no .git

    assert get_serving_revision(repo_dir=repo) is None


def test_no_head_file_returns_none(tmp_path):
    repo = str(tmp_path)
    os.makedirs(os.path.join(repo, ".git"))  # .git exists but is empty

    assert get_serving_revision(repo_dir=repo) is None


def test_ref_target_missing_and_not_in_packed_refs_returns_none(tmp_path):
    """Dangling symbolic ref: no loose ref file, no matching packed-refs line."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
    # no refs/heads/main file, no packed-refs at all

    assert get_serving_revision(repo_dir=repo) is None


def test_malformed_head_content_returns_none(tmp_path):
    """Garbage in HEAD (not a valid ref line, not a 40-char hex SHA) -> None."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), "not a valid sha or ref\n")

    assert get_serving_revision(repo_dir=repo) is None


def test_never_substitutes_a_different_ref_for_the_requested_one(tmp_path):
    """packed-refs contains other branches -- must only ever match the exact ref HEAD points to."""
    repo = str(tmp_path)
    _write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
    _write(
        os.path.join(repo, ".git", "packed-refs"),
        f"{OTHER_SHA} refs/heads/main-old\n"  # must not fuzzy-match "main"
        f"{OTHER_SHA} refs/heads/staging\n",
    )

    assert get_serving_revision(repo_dir=repo) is None


def test_does_not_cache_between_calls(tmp_path):
    """Two consecutive calls against a changing HEAD must both reflect current disk state -- no memoization."""
    repo = str(tmp_path)
    head_path = os.path.join(repo, ".git", "HEAD")
    _write(head_path, VALID_SHA + "\n")
    assert get_serving_revision(repo_dir=repo) == VALID_SHA

    _write(head_path, OTHER_SHA + "\n")
    assert get_serving_revision(repo_dir=repo) == OTHER_SHA


def test_default_repo_dir_finds_this_actual_checkout():
    """No repo_dir given -- must resolve against dashboard.py's own real checkout, not cwd."""
    result = get_serving_revision()
    assert result is not None
    assert len(result) == 40
    assert all(c in "0123456789abcdef" for c in result)


def test_never_reads_origin_main_when_it_diverges_from_local_head(tmp_path):
    """The single most safety-relevant scenario: local HEAD and origin/main
    both exist and hold DIFFERENT SHAs. The function must report the local
    checkout's own HEAD target -- never the remote-tracking ref -- since
    "serving revision" means what this filesystem actually has checked out,
    not what the remote happens to say main is.
    """
    repo = str(tmp_path)
    local_sha = "1111111111111111111111111111111111111111"
    origin_sha = "2222222222222222222222222222222222222222"
    _write(os.path.join(repo, ".git", "HEAD"), "ref: refs/heads/main\n")
    _write(os.path.join(repo, ".git", "refs", "heads", "main"), local_sha + "\n")
    _write(os.path.join(repo, ".git", "refs", "remotes", "origin", "main"), origin_sha + "\n")

    result = get_serving_revision(repo_dir=repo)

    assert result == local_sha
    assert result != origin_sha


def test_read_permission_error_returns_none_not_a_crash_or_substitute(tmp_path, monkeypatch):
    """A HEAD file that exists but can't be read (permissions, locked file,
    transient I/O error) must fail exactly like a missing one -- an explicit
    None/UNKNOWN, never an exception escaping to the caller and never a
    fallback value.
    """
    repo = str(tmp_path)
    head_path = os.path.join(repo, ".git", "HEAD")
    _write(head_path, VALID_SHA + "\n")

    real_open = open

    def _raising_open(path, *args, **kwargs):
        if os.path.abspath(path) == os.path.abspath(head_path):
            raise PermissionError(f"simulated permission denial reading {path}")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _raising_open)

    assert get_serving_revision(repo_dir=repo) is None
