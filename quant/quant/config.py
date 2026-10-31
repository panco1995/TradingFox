"""Global configuration.

Everything is overridable through environment variables so the same code runs
locally, on the VPS and in tests.
"""

from __future__ import annotations

import os
from pathlib import Path

# Binance market data mirror: publicly reachable, no auth, no geo restrictions
# on most networks. Swap for https://api.binance.com if you prefer.
BINANCE_MARKET_BASE = os.getenv("BINANCE_MARKET_BASE", "https://data-api.binance.vision")
BINANCE_TESTNET_BASE = os.getenv("BINANCE_TESTNET_BASE", "https://testnet.binance.vision")
BINANCE_LIVE_BASE = os.getenv("BINANCE_LIVE_BASE", "https://api.binance.com")

DEFAULT_INTERVAL = "1m"
DEFAULT_EXCHANGE = "BINANCE"
DEFAULT_MARKET_TYPE = "spot"


_REPO_ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    """Root directory for market data.

    Defaults to ``<repo>/data`` so that every process (Python, Go, ops scripts)
    sees the same files regardless of its working directory.
    """
    env = os.getenv("QUANT_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (_REPO_ROOT / "data").resolve()
