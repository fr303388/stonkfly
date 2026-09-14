"""Public Coinbase observations. Synthetic fixtures are explicit test inputs."""

import json
import math
import urllib.parse
import urllib.request
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from .config import D


@dataclass(frozen=True)
class Quote:
    product: str
    bid: Decimal
    ask: Decimal
    timestamp: float
    base_increment: Decimal
    quote_increment: Decimal
    price_increment: Decimal
    minimum_quote: Decimal
    minimum_base: Decimal

    def __post_init__(self):
        if (
            not self.bid.is_finite()
            or not self.ask.is_finite()
            or not 0 < self.bid <= self.ask
            or not math.isfinite(self.timestamp)
        ):
            raise ValueError("Invalid quote")
        for k in [
            "base_increment",
            "quote_increment",
            "price_increment",
            "minimum_quote",
            "minimum_base",
        ]:
            if not getattr(self, k).is_finite() or getattr(self, k) <= 0:
                raise ValueError("Invalid market increment")

    def json(self):
        return {
            k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()
        }


def unwrap(value):
    return value.to_dict() if hasattr(value, "to_dict") else value


def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Exchange timestamp requires a timezone")
    return parsed.timestamp()


class CoinbaseMarket:
    def __init__(self, products, client=None):
        if client is None:
            from coinbase.rest import RESTClient

            # Override SDK environment defaults: public observations never need
            # an account key, even when a live broker exists in this process.
            client = RESTClient(api_key=None, api_secret=None, timeout=10)
        self.client = client
        self.products = products
        self.meta = {}
        self.history = {p: [] for p in products}

    def snapshot(self):
        result = {}
        for product in self.products:
            if not self.history[product]:
                # Seed only completed, past one-minute candles. No future samples.
                end = int(time.time() // 60) * 60
                candles = unwrap(
                    self.client.get_public_candles(
                        product, str(end - 120 * 60), str(end), "ONE_MINUTE", limit=120
                    )
                ).get("candles", [])
                past = sorted(
                    (c for c in candles if int(c["start"]) < end),
                    key=lambda c: int(c["start"]),
                )
                if not past:
                    raise RuntimeError("No historical candles available")
                self.history[product] = [float(D(c["close"])) for c in past]
                if any(not math.isfinite(v) or v <= 0 for v in self.history[product]):
                    raise RuntimeError("Invalid historical price")
            # Refresh tradeability at every observation, not just startup.
            m = unwrap(self.client.get_public_product(product))
            self.meta[product] = m
            if (
                m.get("product_id") != product
                or m.get("product_type") != "SPOT"
                or m.get("quote_currency_id") != "USDC"
            ):
                raise RuntimeError("Unexpected product")
            if any(
                m.get(k, False)
                for k in [
                    "is_disabled",
                    "trading_disabled",
                    "cancel_only",
                    "view_only",
                    "limit_only",
                    "auction_mode",
                ]
            ):
                raise RuntimeError("Product unavailable for immediate spot execution")
            b = unwrap(self.client.get_public_product_book(product, limit=1))[
                "pricebook"
            ]
            if b.get("product_id") != product or not b.get("bids") or not b.get("asks"):
                raise RuntimeError("Empty or mismatched book")
            quote = Quote(
                product,
                D(b["bids"][0]["price"]),
                D(b["asks"][0]["price"]),
                utc_timestamp(b["time"]),
                D(m["base_increment"]),
                D(m["quote_increment"]),
                D(m.get("price_increment", m["quote_increment"])),
                D(m["quote_min_size"]),
                D(m["base_min_size"]),
            )
            result[product] = quote
        return result

    def record(self, quotes):
        for p, q in quotes.items():
            self.history[p].append(float((q.bid + q.ask) / 2))
            self.history[p] = self.history[p][-120:]


class FixtureMarket:
    """Deterministic prices for offline verification, never used in live mode."""

    def __init__(self, products):
        self.products = products
        self.tick = 0
        self.history = {p: [] for p in products}

    def snapshot(self):
        base = {"BTC-USDC": 60000, "ETH-USDC": 2500, "SOL-USDC": 100, "PEPE-USDT": 0.000012, "BTC-USDT": 60000, "BNB-USDT": 580}
        quotes = {}
        for j, p in enumerate(self.products):
            price = D(base[p]) * D(1 + 0.025 * math.sin(self.tick * 0.6 + j))
            quotes[p] = Quote(
                p,
                price * D(".9995"),
                price * D("1.0005"),
                time.time(),
                D(".00000001"),
                D(".01"),
                D(".01"),
                D("1"),
                D(".00000001"),
            )
            if not self.history[p]:
                self.history[p] = [
                    float(D(base[p]) * D(1 + 0.01 * math.sin(i * 0.4 + j)))
                    for i in range(80)
                ]
        self.tick += 1
        return quotes

    record = CoinbaseMarket.record



class BinanceMarket:
    """Binance public market data for live trading."""

    def __init__(self, products, base_url="https://api.binance.com"):
        self.base_url = base_url
        self.products = products
        self.meta = {}
        self.history = {p: [] for p in products}
        self._symbol_map = {
            "BTC-USDT": "BTCUSDT", "BNB-USDT": "BNBUSDT",
            "ETH-USDT": "ETHUSDT",
            "SOL-USDT": "SOLUSDT",
            "BTC-USDC": "BTCUSDC",
        }

    def _get(self, path, params=None):
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "stonkfly/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def snapshot(self):
        result = {}
        for product in self.products:
            symbol = self._symbol_map.get(product, product.replace("-", ""))
            if not self.history[product]:
                klines = self._get("/api/v3/klines", {
                    "symbol": symbol, "interval": "15m", "limit": 120
                })
                self.history[product] = [float(k[4]) for k in klines]
            ticker = self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})
            exchange_info = self._get("/api/v3/exchangeInfo", {"symbol": symbol})
            sym_info = exchange_info["symbols"][0]
            filters = {f["filterType"]: f for f in sym_info["filters"]}
            lot_size = filters.get("LOT_SIZE", {})
            price_filter = filters.get("PRICE_FILTER", {})
            min_notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
            quote = Quote(
                product,
                D(ticker["bidPrice"]),
                D(ticker["askPrice"]),
                time.time(),
                D(lot_size.get("stepSize", "0.00000001")),
                D(price_filter.get("tickSize", "0.01")),
                D(price_filter.get("tickSize", "0.01")),
                D(min_notional.get("minNotional", "10")),
                D(lot_size.get("minQty", "0.00000001")),
            )
            result[product] = quote
        return result

    def record(self, quotes):
        for p, q in quotes.items():
            self.history[p].append(float((q.bid + q.ask) / 2))
            self.history[p] = self.history[p][-120:]
