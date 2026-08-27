# Kiran — Maintenance Log

Append-only record of **routine operational maintenance** on the Kiran production
system: manual data backfills, Supabase console changes, one-off scraper runs,
config/dependency changes, restarts — anything operational that does **not** go
through a Pull Request. (Code and data-pipeline changes are logged by their PR;
they do not belong here.)

Governed by `CLAUDE.md` → "Standing rule — log routine maintenance as it happens".
Pending / not-yet-done items live in the **Open Items Ledger** in
`docs/KIRAN_BORING_STATE_TRUST_REGISTER.md` (kept local), not here — this file is
**completed work only**.

## Format

Newest first. A few lines per entry:

    ### YYYY-MM-DD — <short title>
    - **What:** what was done
    - **Why:** trigger / reason
    - **DB writes:** none  |  table(s), row counts, and where the backup is
    - **Verification:** how it was confirmed to have worked
    - **By:** who

A DB write with **no backup location recorded** is a red flag — if that ever
happens, say so explicitly and why.

---

## Entries

### 2026-08-27 — Working branch `feat/tr05-freshness-gates` reconciled to `main`
- **What:** The local repo had sat on a 2-week-old working branch while 8 PRs
  (#21–#28) merged all this session's work into `main`. Reconciled the branch:
  backup marker `backup/feat-tr05-758f866` → stash → `git checkout main` →
  `git stash pop` (3 trivial conflicts resolved) → deleted the old branch. Local
  repo is now on `main` (`d800a4d`). `git status` went from 28 items to 2
  (`breadth_data.csv` and `local_cloud_price_reconciliation.py`, both deliberate).
- **Why:** Close out the TR-11 arc-classification work; get onto the simple
  PR-per-task workflow going forward.
- **DB writes:** none (git only).
- **Verification:** all 5 runtime files (`main.py` etc.) confirmed byte-identical
  to `origin/main`; modules import; 37-test subset + full suite green. Safety
  nets (`backup/feat-tr05-758f866` branch, `stash@{0}`) retained until the next
  successful nightly run.
- **By:** Claude Code. Full detail: audit ledger §76.8.

### 2026-08-27 — Maintenance log established
- **What:** Created this file, added the governing standing rule to `CLAUDE.md`,
  and seeded the Open Items Ledger in the Trust Register. Closeout of the TR-11
  arc-classification work (audit ledger §76).
- **Why:** No single standard existed for recording routine maintenance going
  forward, and the audit/Trust-Register/RESEARCH_LOG split left "what did I do
  last week" unanswerable at a glance.
- **DB writes:** none.
- **Verification:** n/a — documentation only.
- **By:** Claude Code.
