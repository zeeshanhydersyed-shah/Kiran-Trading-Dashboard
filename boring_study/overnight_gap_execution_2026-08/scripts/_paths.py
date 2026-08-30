"""Shared path resolution for the overnight-gap-execution archive.

Every script here is READ-ONLY against the databases and writes only into
this archive's own data/ directory. Layout assumed:

    psx_pipeline/
      psx_data.db                       <- SQLite (2005-2026, full history)
      .env                              <- SUPABASE_DB_URL (cloud, 2024-08+ only)
      boring_study/
        boring_heterogeneity_panel_*.csv
        boring_rf1_misclassification_detail.csv
        overnight_gap_execution_2026-08/
          scripts/  <- this file
          data/     <- all generated CSVs land here
          reports/
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.dirname(HERE)                       # overnight_gap_execution_2026-08/
BS = os.path.dirname(ARCHIVE)                         # psx_pipeline/boring_study/
REPO = os.path.dirname(BS)                            # psx_pipeline/

DATA = os.path.join(ARCHIVE, "data")
DB = os.path.join(REPO, "psx_data.db")                # SQLite, full history
ENV = os.path.join(REPO, ".env")                     # cloud Postgres URL

os.makedirs(DATA, exist_ok=True)


def cloud_conn(readonly=True):
    """Open a read-only psycopg2 connection to the cloud Postgres, parsing the
    SUPABASE_DB_URL / DATABASE_URL from psx_pipeline/.env (handles special
    characters in the password the same way database_pg._parse_pg_url does)."""
    from urllib.parse import unquote
    import psycopg2
    url = next(l.split("=", 1)[1].strip() for l in open(ENV, encoding="utf-8")
               if l.strip().startswith(("SUPABASE_DB_URL=", "DATABASE_URL=")))
    rest = url.split("://", 1)[-1]
    at = rest.rfind("@")
    ui, hi = rest[:at], rest[at + 1:]
    c = ui.index(":")
    user, pw = unquote(ui[:c]), unquote(ui[c + 1:])
    hp, db = hi.rsplit("/", 1)
    db = unquote(db.split("?")[0])
    host, port = hp.rsplit(":", 1)
    conn = psycopg2.connect(host=host, port=int(port), dbname=db, user=user,
                            password=pw, sslmode="require")
    if readonly:
        conn.set_session(readonly=True, autocommit=True)
    return conn
