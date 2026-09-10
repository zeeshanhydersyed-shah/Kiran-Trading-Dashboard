"""Kiran Local-First Migration -- archive tooling (Phase 1 / DR-program SEQ-1).

Preservation-only utilities that build and verify the immutable historical
baseline. Nothing in this package writes to ``psx_data.db`` or mutates a
historical row (owner decision D7, 2026-09-09).

Phase 2 (2026-09-10) adds ``scrape_capture`` -- the parallel contemporaneous
scrape path that writes immutable ``data/incoming/*.parquet`` capture files. It
still never touches ``psx_data.db``, Supabase, or ``daily_scraper.yml``.
"""
