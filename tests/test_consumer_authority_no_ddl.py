"""TR-01 Option B companion PR (ledger §114) -- the served dashboard must not
run DDL against the authoritative backend, and must not expose a manual
full-pipeline trigger there.

Two guarantees pinned here:

  1. dashboard.py structure (AST, deterministic -- no scrape/DB/Streamlit
     runtime needed): both init_db() calls are gated behind `not _PG_URL`;
     HAS_CMD_UPDATE / cmd_update are forced off under `if _PG_URL:`; and the
     "Refresh Data" button is not reachable when _PG_URL is set.

  2. database_pg.init_db() degrades to best-effort per statement -- a
     restricted role (kiran_dashboard) with no CREATE/ALTER grant makes
     individual statements fail; init_db() must not propagate, and must
     roll back the aborted transaction so the next statement can run.

See scratch_tr01_optionb_20260903/TR01_OPTION_B_DB_ROLE_DRAFT.md.
"""
from __future__ import annotations

import ast
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# 1. dashboard.py structure
# ---------------------------------------------------------------------------

def _dashboard_tree():
    with open(os.path.join(_ROOT, "dashboard.py"), encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _parent_map(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _mentions_pg_url(node) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id == "_PG_URL"
        for n in ast.walk(node)
    )


def _enclosing_if_tests(node, parents):
    """Yield the `test` expression of every `ast.If` that controls `node`,
    walking outward. Handles elif (an If sitting in another If's orelse)."""
    cur = node
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, ast.If):
            # `cur` is in parent.body (the taken branch) or parent.orelse.
            if any(cur is s or cur in ast.walk(s) for s in parent.body):
                yield parent.test, "body"
            else:
                yield parent.test, "orelse"
        cur = parent


def test_init_db_calls_are_gated_on_not_pg_url():
    tree = _dashboard_tree()
    parents = _parent_map(tree)
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "init_db"
    ]
    assert len(calls) >= 2, "expected the load_data() + Analytics init_db() calls"
    for call in calls:
        gated = False
        for test_expr, branch in _enclosing_if_tests(call, parents):
            if _mentions_pg_url(test_expr):
                # `if not _PG_URL: init_db()`  -> body of a negated test
                # `if _PG_URL: ... else: init_db()` -> orelse of a plain test
                negated = isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not)
                if (branch == "body" and negated) or (branch == "orelse" and not negated):
                    gated = True
                    break
        assert gated, (
            f"init_db() call at dashboard.py line {call.lineno} is not gated so "
            f"it only runs when _PG_URL is unset (ledger §114)"
        )


def test_has_cmd_update_forced_off_when_pg_url_set():
    tree = _dashboard_tree()
    parents = _parent_map(tree)
    # Find `HAS_CMD_UPDATE = False` assignments whose enclosing If tests _PG_URL
    # (non-negated) -- i.e. `if _PG_URL: HAS_CMD_UPDATE = False`.
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "HAS_CMD_UPDATE" not in targets:
            continue
        if not (isinstance(node.value, ast.Constant) and node.value.value is False):
            continue
        for test_expr, branch in _enclosing_if_tests(node, parents):
            negated = isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not)
            if _mentions_pg_url(test_expr) and branch == "body" and not negated:
                hits.append(node)
                break
    assert hits, (
        "dashboard.py must force HAS_CMD_UPDATE = False inside `if _PG_URL:` "
        "so the served Cloud app can never trigger main.cmd_update() (ledger §114)"
    )


def test_refresh_button_not_reachable_under_pg_url():
    tree = _dashboard_tree()
    parents = _parent_map(tree)
    btn = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "button" and node.args
                and isinstance(node.args[0], ast.Constant)
                and "Refresh Data" in str(node.args[0].value)):
            btn = node
            break
    assert btn is not None, "could not find the '🔄 Refresh Data' st.button call"
    # Its enclosing If must be the orelse (elif) branch of an `if _PG_URL:` test,
    # OR itself sit in the body of an `if not _PG_URL:` test.
    ok = False
    for test_expr, branch in _enclosing_if_tests(btn, parents):
        if not _mentions_pg_url(test_expr):
            continue
        negated = isinstance(test_expr, ast.UnaryOp) and isinstance(test_expr.op, ast.Not)
        if (branch == "orelse" and not negated) or (branch == "body" and negated):
            ok = True
            break
    assert ok, (
        "the '🔄 Refresh Data' button must be unreachable when _PG_URL is set "
        "(ledger §114 / OI-8 class) -- gate it behind `if _PG_URL: ... elif "
        "st.button(...)` or `if not _PG_URL and st.button(...)`"
    )


# ---------------------------------------------------------------------------
# 2. database_pg.init_db() best-effort behaviour
# ---------------------------------------------------------------------------

class _RaisingCursor:
    def __init__(self, fail_on):
        self.fail_on = fail_on
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if any(tok in sql for tok in self.fail_on):
            raise RuntimeError("permission denied for schema public")

    def close(self):
        pass


class _FakeConn:
    def __init__(self, fail_on):
        self._fail_on = fail_on
        self.rollbacks = 0
        self.commits = 0
        self.cursors = []

    def cursor(self, *a, **k):
        c = _RaisingCursor(self._fail_on)
        self.cursors.append(c)
        return c

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_init_db_pg_is_best_effort_under_a_restricted_role(monkeypatch):
    """A role that can't CREATE/ALTER makes every DDL statement raise. init_db()
    must swallow each, roll back, and return normally -- never propagate."""
    import contextlib
    import database_pg

    fake = _FakeConn(fail_on=["CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "DO $$"])

    @contextlib.contextmanager
    def _fake_get_conn():
        try:
            yield fake
            fake.commit()
        except Exception:
            fake.rollback()
            raise

    monkeypatch.setattr(database_pg, "get_conn", _fake_get_conn)

    database_pg.init_db()  # must not raise

    # Every DDL/ALTER statement was attempted (not short-circuited by the first
    # failure) and each failure was rolled back rather than propagated.
    assert fake.rollbacks >= 10
    assert any("CREATE TABLE IF NOT EXISTS trade_setups" in s
               for c in fake.cursors for s in c.executed)
    assert any("ALTER TABLE trade_setups ADD COLUMN IF NOT EXISTS quantity" in s
               for c in fake.cursors for s in c.executed)


def test_init_db_pg_still_runs_data_migrations_when_ddl_denied(monkeypatch):
    """The plain UPDATE data-migrations (which a restricted role with UPDATE on
    trade_setups CAN run) must still be attempted even though every preceding
    DDL statement was denied."""
    import contextlib
    import database_pg

    fake = _FakeConn(fail_on=["CREATE TABLE", "CREATE INDEX", "ALTER TABLE", "DO $$"])

    @contextlib.contextmanager
    def _fake_get_conn():
        try:
            yield fake
            fake.commit()
        except Exception:
            fake.rollback()
            raise

    monkeypatch.setattr(database_pg, "get_conn", _fake_get_conn)
    database_pg.init_db()

    assert any("UPDATE trade_setups SET status='Closed'" in s
               for c in fake.cursors for s in c.executed)
