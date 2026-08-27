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
