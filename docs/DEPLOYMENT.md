# Deployment — CI gate and staging environment

**Status:** repo-side work is done and verified (2026-08-12), and **`main` is
now protected** — PR required, all three checks required, no admin bypass;
verified by a real push from the repo owner being rejected with
`GH006 ... Changes must be made through a pull request`. What is still
outstanding from §3 is the Streamlit Cloud half: the `staging` branch, the
second Cloud app, and the staging-database decision.

Background: docs/KIRAN_CLEANUP_AUDIT.md §7.2 (structural gaps), §10 (deploy
strategy, Option A vs B), §22 (what the 2026-08-12 data-loss incident taught
us about this gap specifically).

---

## 1. What the pipeline looks like now

```
     you commit
         │
         ▼
   push to  staging ──────────► CI (.github/workflows/ci.yml)
         │                        ├─ clean-install   pip install on Python 3.11
         │                        ├─ unit-tests      pytest tests/
         │                        └─ app-boot        renders all 15 pages
         │                              │
         │                        all green?
         │                              │
         ▼                              ▼
   staging Streamlit Cloud app ── you click through it
         │
         │  open a PR into main, only after the above
         ▼
   PR to  main ────────────────► 3 checks must pass ──► merge ──► production
```

`main` is protected: PR required, all three checks required, **no admin
bypass**. A direct `git push origin main` is rejected.

Before 2026-08-12 the whole left column did not exist: `git push origin main`
put code in front of a live trader in ~60 seconds with nothing checking it.

## 2. The CI gate — what it actually catches

`.github/workflows/ci.yml`, on every push and PR to `main` and `staging`.

| Job | What it proves | Why it is a separate job |
|---|---|---|
| `clean-install` | `pip install -r requirements.txt` succeeds on a clean Python 3.11, `pip check` passes, and all 19 non-Streamlit production modules import | The old range pins were **not installable** on the dev machine; the workaround (installing unconstrained latest versions) is what hid a real crash for a week. Runs with no pip cache on purpose. |
| `unit-tests` | `pytest tests/` (excluding the boot test) passes | Regression cover for the silent-gap data-loss bug. That failure had already happened twice — the first fix shipped without a test, so the identical shape came back. |
| `app-boot` | Every one of the 15 dashboard pages renders with no uncaught exception, against a committed fixture database | Pure-logic tests would not have caught either bug that actually shipped. This one does — verified, see below. |

`clean-install` also uploads a `resolved-py311.txt` (`pip freeze`) artifact per
run — the durable record of what a clean 3.11 install really resolves, to
compare against Streamlit Cloud's own build log.

### The boot test is not theatre — it was checked against the real bugs

Run against the pre-fix code, `tests/test_app_boot.py` reproduces both bugs
that reached production undetected:

- **`set_page_config` ordering crash** (audit §21 root cause 3) — killed the
  entire app on the pinned Streamlit 1.39.1, tolerated by the drifted local
  1.57.0. The boot test fails with
  `StreamlitSetPageConfigMustBeFirstCommandError`.
- **`st.dataframe(..., width='stretch')`** (audit §8.3 Bug 1) — `TypeError:
  'str' object cannot be interpreted as an integer` on the pinned Streamlit.
  Found live on **3 of 15 pages** (`Setup Perf`, `Backtest`, `Portfolio`) when
  the page matrix was first run on 2026-08-12; fixed in the same change.

### The fixture database

`tests/fixtures/psx_fixture.db` (~14 MB, committed) is a slice of the real
local SQLite DB: full schema for all 49 tables, ~300 trading days, ~66
symbols (2 per sector), research/staging tables emptied.

It exists because `database.init_db()` cannot stand in for the production
schema — it creates 14 of 49 tables and has drifted from what the code
queries (a fresh `init_db()` database crashes the dashboard with `no such
column: p.open`). Copying the DDL out of `sqlite_master` means the fixture's
schema is, by construction, the schema production actually has.

**Regenerate it after any schema change**, from a machine with the local DB:

```bash
python tests/fixtures/build_fixture_db.py
```

Locally the tests use your real `psx_data.db` if it exists and never stage the
fixture over it; in CI (where `psx_data.db` is gitignored and absent) the
fixture is copied in for the session and removed afterwards. `DATABASE_URL`
and `SUPABASE_DB_URL` are forced empty for the whole test session, so CI can
never reach production Postgres.

### Running the gate locally

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

`pytest.ini` limits collection to `tests/` — the 18 loose `test_*.py` files in
the repo root are one-off research scripts, not a suite (audit §7.2).

## 3. One-time Streamlit Cloud setup — **needs the account owner**

Nothing below can be done from this repo; it is all in
[share.streamlit.io](https://share.streamlit.io) and GitHub's settings UI.

1. **Create the `staging` branch** (once):
   ```bash
   git checkout -b staging main
   git push -u origin staging
   ```
2. **Create a second Cloud app** — *Create app* → same repo
   (`zeeshanhydersyed-shah/Kiran-Trading-Dashboard`), **branch `staging`**,
   main file `dashboard.py`, and a distinct URL (e.g. `…-staging`).
3. **Give it secrets.** Copy the production app's secrets, *but see the
   warning below about which database it points at*.
4. ~~**Protect `main`**~~ — **DONE 2026-08-12.** Settings → Branches, rule on
   `main`: require a pull request, require the three checks (`Clean install on
   Python 3.11`, `Unit tests`, `App boot smoke test`), and **do not allow
   bypassing** — so it binds the repo owner too, who is the only person who
   pushes here. **Required approvals must be `0`**: GitHub defaults it to 1, a
   PR author cannot approve their own PR, and with bypass disabled that
   combination locks the sole maintainer out of merging entirely.

### Which database should staging point at?

| Option | Trade-off |
|---|---|
| Same `DATABASE_URL` as production (simplest) | Staging renders real, current data — the most faithful pre-flight check. **But every write path in the app writes to production**: saving/editing a trade in `Trade Log`, the `Agent` page's run buttons. Verifying on staging then means "look, don't touch". |
| A dedicated read-only Postgres role on the same Supabase database (**recommended**) | Same real data, and a misclick on staging cannot corrupt production. Costs one `CREATE ROLE … ; GRANT SELECT …` against the production database — which under this project's standing rule needs explicit sign-off before it runs. Write paths on staging will error visibly, which is the correct behaviour for a staging app. |
| A separate Supabase project seeded from a dump | Fully isolated, but a second database to keep fresh — most work, and stale staging data produces misleading verification. |

Not decided yet — flagged here rather than chosen unilaterally.

## 4. Day-to-day flow

**`main` is protected** (enabled 2026-08-12): a pull request is required, all
three CI jobs must pass, and the rule applies to admins too — there is no
bypass, deliberately. `git push origin main` is rejected outright. That is the
point: the gate binds the only person who pushes here, or it is decoration.

```bash
git checkout staging
# ... work, commit ...
git push origin staging          # CI runs; staging Cloud app redeploys
```

Then, once CI is green **and** the staging app has been clicked through, open a
PR from `staging` into `main` and merge it when the three checks go green:

```bash
# GitHub CLI is not installed on this machine -- open the PR in the browser,
# or install gh and use:
gh pr create --base main --head staging --fill
```

Merging promotes to production and Cloud redeploys in ~60s. Prefer a merge that
keeps `staging` and `main` identical afterwards; if they drift, fast-forward
`staging` back up to `main` so the next PR is a clean diff.

**What to click through on staging** before promoting (the boot test proves
pages render, not that they are *right*): the sidebar regime widget's date and
"days since" line, the landing page's gate tiles, and whichever page the change
actually touched.

### Hotfixes

There is no direct-push escape hatch any more — that was the deliberate
trade-off when admin bypass was disabled. A genuine emergency is still fast:

```bash
git checkout -b hotfix/<what> main
# ... fix, commit ...
git push -u origin hotfix/<what>
gh pr create --base main --fill    # or open the PR in the browser
```

CI takes about a minute (the three jobs run in parallel; the slowest, the
15-page boot test, finished in 58s on its first green run). Merge when green.

If CI is broken *and* production is on fire at the same time, the honest move is
to turn the protection rule off in Settings, push, and turn it back on —
a deliberate, visible act, not an accidental bypass. Do not leave it off.

### Rollback

Streamlit Cloud always serves the tip of the branch, so a rollback is a git
operation:

```bash
git checkout main
git revert <bad-commit>          # preferred - keeps history honest
git push origin main             # live again in ~60s
```

## 5. Known limits of this gate

Stated plainly so nobody reads more assurance into a green build than is there.

- **It does not test the Postgres path.** Every test runs against SQLite.
  `database_pg.py` / `dashboard_pg.py` — the code production actually runs on
  Cloud — is exercised by none of it. Postgres-only bugs (the `TEXT` vs `DATE`
  comparison class documented in CLAUDE.md) would pass CI clean. Closing this
  needs a disposable Postgres instance in CI, not a connection to Supabase.
- **It does not check correctness of what renders**, only that rendering
  raises nothing. A page showing confidently wrong numbers passes.
- **It does not know what Streamlit Cloud resolves at build time.** The
  `resolved-py311.txt` artifact is a CI runner's answer, not Cloud's. The
  staging app in §3 is what actually closes that gap (audit §22 A8).
- **The fixture ages.** It is a snapshot; a schema change without a
  regenerated fixture will show up as a CI failure, which is the intended
  behaviour, but the fix is to rerun the builder, not to relax the test.
- **The daily pipeline workflows are still ungated.** `daily_scraper.yml` and
  friends run on a schedule against production Supabase; CI does not simulate
  them. Two of them were found broken on 2026-08-12 by reading them, not by
  any check: `daily_scraper.yml` called `playwright install` after playwright
  had been removed from `requirements.txt`, and `weekly_ml_retrain.yml` lost
  scikit-learn the same way. Both fixed; nothing yet *prevents* the next one.
