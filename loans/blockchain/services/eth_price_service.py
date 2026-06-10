"""
ETH/PHP exchange rate service.

Primary: CryptoCompare API (free, no key required, cached 5 min)
If the rate cannot be fetched, wallet transactions are blocked.
"""

import logging
import time

import requests

logger = logging.getLogger("blockchain")

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

_cache = {"rate": None, "source": None, "fetched_at": 0}
_CACHE_TTL = 300  # 5 minutes


class ExchangeRateUnavailableError(Exception):
    """Raised when the ETH/PHP exchange rate cannot be fetched."""

    pass


def get_eth_php_rate():
    """
    Return the current ETH/PHP exchange rate from CryptoCompare.

    Rate is cached for 5 minutes. If the API is unreachable and no
    valid cached rate exists, raises ExchangeRateUnavailableError
    to block the transaction.

    Returns:
        dict with keys: rate (float), source (str), fetched_at (float)

    Raises:
        ExchangeRateUnavailableError: If rate cannot be determined
    """
    now = time.time()
    if _cache["rate"] and (now - _cache["fetched_at"]) < _CACHE_TTL:
        return _cache.copy()

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": "ethereum", "vs_currencies": "php"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["ethereum"]["php"])
        _cache.update(rate=rate, source="coingecko", fetched_at=now)
        logger.info("ETH/PHP rate fetched: %.2f (CoinGecko)", rate)
        return _cache.copy()
    except Exception as exc:
        logger.error("CoinGecko unavailable: %s", exc)
        raise ExchangeRateUnavailableError(
            "ETH/PHP exchange rate is currently unavailable. "
            "Wallet transactions are disabled until the rate can be fetched."
        ) from exc


def php_to_eth(php_amount):
    """
    Convert a PHP amount to ETH using the current exchange rate.

    Returns:
        dict with keys: eth_amount (float), rate (float), source (str)

    Raises:
        ExchangeRateUnavailableError: If rate cannot be determined
    """
    rate_info = get_eth_php_rate()
    eth_amount = float(php_amount) / rate_info["rate"]
    return {
        "eth_amount": eth_amount,
        "rate": rate_info["rate"],
        "source": rate_info["source"],
    }
