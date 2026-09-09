"""Kiran Local-First Migration -- archive tooling (Phase 1 / DR-program SEQ-1).

Preservation-only utilities that build and verify the immutable historical
baseline. Nothing in this package writes to ``psx_data.db`` or mutates a
historical row (owner decision D7, 2026-09-09).
"""
