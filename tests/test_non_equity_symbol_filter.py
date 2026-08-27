"""
Tests for config.is_non_equity_symbol() — the ingestion gate that keeps
futures / government paper / 786 out of prices, prices_adjusted and sectors.

The old scraper filter only caught bare SYMBOL-MON futures; every suffixed
variant plus all P0x paper and 786/786R leaked in. These cases lock the
broadened behaviour.
"""

import pytest

from config import is_non_equity_symbol


@pytest.mark.parametrize("sym", [
    # futures — bare month
    "HBL-JAN", "OGDC-DEC", "AGHA-APR", "YOUW-SEP",
    # futures — parallel series suffix
    "AKBL-AUGB", "BAFL-MAYC", "BAFL-MAYD", "AIRLINK-DECC",
    "MZNPETF-AUGB", "UBLPETF-JULB",   # ETF *futures* — contracts, not the ETF
    # futures — cash / hand-delivery series
    "AIRLINK-CJAN", "KEL-CAPR", "PPL-CDEC", "TELE-CJUN",
    # government paper
    "P01GIS200826", "P05FRR300530", "P10FRZ220136", "P03VRR280627",
    # misc
    "786", "786R", "786r",
])
def test_non_equity_symbols_are_flagged(sym):
    assert is_non_equity_symbol(sym) is True


@pytest.mark.parametrize("sym", [
    # ordinary equities
    "HBL", "OGDC", "SYM", "BML", "FCL", "WAVESAPP", "MSOT", "INKL", "IMAGE",
    # the 6 ETF whitelist + other bare ETFs — kept
    "JSGBETF", "JSMFETF", "MZNPETF", "NBPGETF", "NITGETF", "UPLPETF",
    "UBLPETF", "ACIETF", "HBLTETF", "MIIETF",
    # P-prefixed equities must NOT match the govt-paper pattern
    "PABC", "PACE", "PAEL", "PIOC", "POL", "PPL", "PIAHCLA", "PESC1",
    # hyphen but not a month
    "FOO-BAR",
    # empty / junk
    "", "   ", None,
])
def test_equities_and_etfs_are_not_flagged(sym):
    assert is_non_equity_symbol(sym) is False
