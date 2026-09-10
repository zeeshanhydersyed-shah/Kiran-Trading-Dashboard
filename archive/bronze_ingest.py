r"""
Kiran Local-First Migration -- Phase 3, Task 3.1: Bronze ingest.

Append the Phase 2 contemporaneous capture files (``data/incoming/*.parquet`` on
the ``data-captures`` branch) into the **live Bronze store**, one trading day at a
time. Append-only, deduped, gap-detecting; every consumed capture file is
recorded with its SHA-256.

Design note: docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md
Tracker:     docs/KIRAN_LOCAL_FIRST_MIGRATION.md  (Phase 3, tracker section 5)

Store layout under KIRAN_ARCHIVE_ROOT (default D:\KIRAN_ARCHIVE):

    bronze/ silver/ baseline/ ...      Phase 1 FROZEN seed -- immutable, manifested
    data-captures/                     --single-branch clone of the data-captures branch
    prices_archive/bronze/prices/year=YYYY/data.parquet        <- this script writes here
    prices_archive/bronze/index_prices/year=YYYY/data.parquet  <-
    prices_archive/_bronze_ingest_log.jsonl                    append-only lineage
    prices_archive/_bronze_gaps.json                           report-only, rewritten each run

The live Bronze is seeded once as a byte copy of the frozen ``bronze/`` tree,
then only ever grows by whole trading days. A partition is rewritten to add new
dates; an existing raw row is never altered (D7 / tracker section 3).

Never opens ``psx_data.db`` (not even read-only), Supabase, or ``daily_scraper.yml``.

    python -m archive.bronze_ingest [--captures-dir DIR] [--store-root DIR]
                                    [--no-pull] [--seed-only]

Outcome JSON is printed; ``$GITHUB_OUTPUT`` is written when set.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ARCHIVE_ROOT = Path(os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE"))

# Matches archive/build_store.py exactly -- a partition this script rewrites is
# byte-identical to what build_store.py would produce for the same row set.
PARQUET_OPTS = dict(compression="zstd", version="2.6", use_dictionary=True)

# Frozen column order/'schema' of the Phase 1 store (build_store.py output).
PRICES_COLUMNS = ["symbol", "date", "close", "volume", "high", "low", "open"]
INDEX_COLUMNS = ["symbol", "date", "high", "low", "close", "open"]
PRICES_SCHEMA = pa.schema([
    ("symbol", pa.string()), ("date", pa.string()),
    ("close", pa.float64()), ("volume", pa.int64()),
    ("high", pa.float64()), ("low", pa.float64()), ("open", pa.float64()),
])
INDEX_SCHEMA = pa.schema([
    ("symbol", pa.string()), ("date", pa.string()),
    ("high", pa.float64()), ("low", pa.float64()),
    ("close", pa.float64()), ("open", pa.float64()),
])
_TABLES = {
    "prices": (PRICES_COLUMNS, PRICES_SCHEMA),
    "index_prices": (INDEX_COLUMNS, INDEX_SCHEMA),
}


# --------------------------------------------------------------------------- io

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _sort(table: pa.Table) -> pa.Table:
    return table.sort_by([("symbol", "ascending"), ("date", "ascending")])


def _write_partition(table: pa.Table, fp: Path) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, **PARQUET_OPTS)
    os.replace(tmp, fp)


# ---------------------------------------------------------------------- layout

class Store:
    def __init__(self, store_root: Path):
        self.root = store_root
        self.bronze = store_root / "bronze"
        self.log_path = store_root / "_bronze_ingest_log.jsonl"
        self.gaps_path = store_root / "_bronze_gaps.json"

    def part_path(self, table: str, year: str) -> Path:
        return self.bronze / table / f"year={year}" / "data.parquet"

    def read_partition(self, table: str, year: str) -> pa.Table | None:
        fp = self.part_path(table, year)
        if not fp.exists():
            return None
        cols, schema = _TABLES[table]
        return pq.read_table(fp).select(cols).cast(schema)

    def dates_present(self, table: str) -> set[str]:
        base = self.bronze / table
        out: set[str] = set()
        if not base.exists():
            return out
        for fp in base.glob("year=*/data.parquet"):
            out |= set(pq.read_table(fp, columns=["date"]).column("date").to_pylist())
        return out

    # --- lineage log -----------------------------------------------------

    def log_append(self, entry: dict) -> None:
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")

    def log_entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(ln) for ln in self.log_path.read_text().splitlines() if ln.strip()]

    def seed_max_date(self) -> str | None:
        for e in self.log_entries():
            if e.get("action") == "seed":
                return e.get("seed_max_date")
        return None


# ------------------------------------------------------------------------ seed

def seed(store: Store) -> dict:
    """One-time: copy the frozen bronze/ tree into the live store. Idempotent."""
    if store.bronze.exists():
        return {"seeded": False, "reason": "already present"}

    frozen = ARCHIVE_ROOT / "bronze"
    if not frozen.exists():
        raise SystemExit(f"frozen seed not found: {frozen} -- run archive.build_store first")

    store.root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(frozen, store.bronze)
    # the frozen tree is read-only (archive_manifest protect); the live store
    # must be writable so ingest can rewrite year partitions.
    for p in store.bronze.rglob("*"):
        if p.is_file():
            os.chmod(p, os.stat(p).st_mode | 0o200)

    dates = store.dates_present("prices")
    seed_max = max(dates) if dates else None
    store_manifest = ARCHIVE_ROOT / "STORE_MANIFEST.json"
    entry = {
        "ts": _now(), "action": "seed",
        "source": str(frozen),
        "store_manifest_sha256": sha256(store_manifest) if store_manifest.exists() else None,
        "seed_max_date": seed_max,
        "prices_dates": len(dates),
        "index_dates": len(store.dates_present("index_prices")),
    }
    store.log_append(entry)
    return {"seeded": True, "seed_max_date": seed_max, "prices_dates": len(dates)}


# --------------------------------------------------------------------- capture

def _pull(captures_dir: Path) -> str:
    try:
        subprocess.run(["git", "-C", str(captures_dir), "pull", "--ff-only"],
                       check=True, capture_output=True, text=True, timeout=120)
        head = subprocess.run(["git", "-C", str(captures_dir), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
        return head
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        raise SystemExit(f"git pull of {captures_dir} failed: {detail}")


def _capture_files(captures_dir: Path) -> list[Path]:
    incoming = captures_dir / "data" / "incoming"
    return sorted(p for p in incoming.glob("*.parquet") if p.stem != "latest")


def _split_capture(fp: Path) -> tuple[str, dict, pa.Table, pa.Table]:
    """Return (source_date, metadata, prices_table, index_table) from a capture file."""
    pf = pq.ParquetFile(fp)
    meta = {k.decode(): v.decode() for k, v in (pf.schema_arrow.metadata or {}).items()}
    t = pf.read()

    tds = set(t.column("trading_date").to_pylist())
    src = meta.get("source_date")
    if src is None:
        if len(tds) != 1:
            raise SystemExit(f"{fp.name}: no source_date metadata and mixed trading_date {tds}")
        src = next(iter(tds))
    if tds - {src}:
        raise SystemExit(f"{fp.name}: trading_date {sorted(tds)} != source_date {src}")

    import pyarrow.compute as pc
    rt = t.column("record_type")
    stock = t.filter(pc.equal(rt, "stock"))
    index = t.filter(pc.equal(rt, "index"))

    def _rename_date(tb: pa.Table) -> pa.Table:
        return tb.rename_columns([("date" if n == "trading_date" else n) for n in tb.column_names])

    prices = _rename_date(stock).select(PRICES_COLUMNS).cast(PRICES_SCHEMA)
    idx = _rename_date(index).select(INDEX_COLUMNS).cast(INDEX_SCHEMA)
    return src, meta, prices, idx


# ----------------------------------------------------------------------- gaps

def detect_gaps(store: Store) -> dict:
    prices_dates = store.dates_present("prices")
    if not prices_dates:
        return {"window": None, "missing_capture": [], "nodata_or_holiday": []}

    seed_max = store.seed_max_date()
    lo = seed_max or min(prices_dates)
    hi = max(prices_dates)

    # capture-file dates that exist on disk (nodata days produce no file)
    cap_dates: set[str] = set()
    for e in store.log_entries():
        if e.get("action") == "ingest":
            cap_dates.add(e["source_date"])

    d = dt.date.fromisoformat(lo) + dt.timedelta(days=1)
    end = dt.date.fromisoformat(hi)
    missing_capture, nodata = [], []
    while d <= end:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in prices_dates:
            (missing_capture if iso not in cap_dates else nodata).append(iso)
        d += dt.timedelta(days=1)

    report = {
        "generated": _now(),
        "window": {"after": lo, "through": hi},
        "note": ("weekdays after the frozen seed's max date with no Bronze row. "
                 "No PSX holiday calendar exists in-repo -- 'missing_capture' entries "
                 "are for human review, not necessarily errors."),
        "missing_capture": missing_capture,
        "nodata_or_holiday": nodata,
    }
    store.gaps_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


# --------------------------------------------------------------------- ingest

def ingest(store: Store, captures_dir: Path, pull: bool = True) -> dict:
    captures_head = _pull(captures_dir) if pull else None

    present = {tbl: store.dates_present(tbl) for tbl in _TABLES}
    files = _capture_files(captures_dir)

    ingested, skipped = [], []
    for fp in files:
        src, cmeta, prices, idx = _split_capture(fp)
        if src in present["prices"] or src in present["index_prices"]:
            skipped.append(src)
            continue

        digest = sha256(fp)
        touched: dict[str, list[str]] = {}
        for tbl, new_t in (("prices", prices), ("index_prices", idx)):
            if new_t.num_rows == 0:
                continue
            year = src[:4]
            existing = store.read_partition(tbl, year)
            combined = _sort(pa.concat_tables([existing, new_t]) if existing is not None else new_t)
            _write_partition(combined, store.part_path(tbl, year))
            present[tbl].add(src)
            touched.setdefault(year, []).append(tbl)

        entry = {
            "ts": _now(), "action": "ingest",
            "capture_file": fp.name, "capture_sha256": digest,
            "source_date": src,
            "capture_code_version": cmeta.get("code_version", ""),
            "capture_coverage_status": cmeta.get("coverage_status", ""),
            "stock_rows_added": prices.num_rows,
            "index_rows_added": idx.num_rows,
            "years_touched": sorted(touched),
        }
        store.log_append(entry)
        ingested.append(entry)

    gaps = detect_gaps(store)
    return {
        "outcome": "ingested" if ingested else "up_to_date",
        "captures_head": captures_head,
        "capture_files_seen": len(files),
        "ingested_dates": [e["source_date"] for e in ingested],
        "skipped_present": skipped,
        "rows_added": sum(e["stock_rows_added"] + e["index_rows_added"] for e in ingested),
        "gaps": {"missing_capture": gaps["missing_capture"],
                 "nodata_or_holiday": gaps["nodata_or_holiday"]},
    }


# ------------------------------------------------------------------------- cli

_GITHUB_OUTPUT_KEYS = ("outcome", "capture_files_seen", "rows_added")


def _emit_github_output(result: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k in _GITHUB_OUTPUT_KEYS:
            if result.get(k) is not None:
                f.write(f"{k}={result[k]}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bronze ingest -- append capture files into the live Bronze store.")
    ap.add_argument("--captures-dir", default=str(ARCHIVE_ROOT / "data-captures"),
                    help="clone of the data-captures branch (default: %(default)s)")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "prices_archive"),
                    help="live Medallion store root (default: %(default)s)")
    ap.add_argument("--no-pull", action="store_true", help="skip 'git pull' of the captures clone")
    ap.add_argument("--seed-only", action="store_true", help="seed the live Bronze from the frozen store and stop")
    args = ap.parse_args(argv)

    store = Store(Path(args.store_root))
    seed_res = seed(store)

    if args.seed_only:
        result = {"outcome": "seeded", "seed": seed_res}
    else:
        result = ingest(store, Path(args.captures_dir), pull=not args.no_pull)
        result["seed"] = seed_res

    print(json.dumps(result, indent=2, sort_keys=True))
    _emit_github_output(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
