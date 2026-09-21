"""Official Coinbase Advanced SDK execution, wrapped by an AgentKit provider.

Live execution uses price-bounded fill-or-kill spot orders. Intent is persisted
before the request. An ambiguous result is never retried as a new order.
"""

import os
import time
from datetime import datetime, timezone

from .config import D
from .market import unwrap
from .risk import Veto

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "FAILED", "REJECTED"}


class UnresolvedOrder(RuntimeError):
    pass


class PaperBroker:
    mode = "paper"

    def __init__(self, settings, ledger):
        self.s = settings
        self.l = ledger

    def preflight(self):
        return {"mode": "paper", "network_execution": False}

    def verify_balances(self):
        pass

    def reconcile(self):
        # Paper requests never leave the process; the immutable plan contains
        # the execution quote, so an interrupted fill can settle exactly once.
        for row in self.l.pending():
            self._fill(row["plan"])

    def execute(self, plan, before_submit):
        try:
            before_submit(plan)
        except Exception:
            self.l.mark(plan["client_order_id"], "REJECTED")
            raise
        return self._fill(plan)

    def _fill(self, p):
        size = D(p["base_size"])
        price = D(p["observed_ask"] if p["side"] == "BUY" else p["observed_bid"])
        value = size * price
        fee = value * D(self.s.paper_fee)
        self.l.settle(p["client_order_id"], size, value, fee)
        return {
            "mode": "paper",
            "status": "FILLED",
            "base": str(size),
            "quote": str(value),
            "fee": str(fee),
        }


class CoinbaseBroker:
    mode = "live"

    def __init__(self, settings, ledger, client, portfolio):
        if not portfolio:
            raise ValueError("Dedicated Coinbase portfolio UUID required")
        self.s = settings
        self.l = ledger
        self.client = client
        self.portfolio = portfolio

    @classmethod
    def from_env(cls, settings, ledger):
        try:
            from pathlib import Path as _P
            envf = _P(".env")
            if envf.exists():
                for line in envf.read_text(encoding="utf-8").splitlines():
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass
        if os.environ.get("STONKFLY_LIVE") != "I_ACCEPT_REAL_TRADES":
            raise RuntimeError("Live opt-in missing")
        from coinbase.rest import RESTClient

        key = os.environ.get("COINBASE_KEY_FILE")
        portfolio = os.environ.get("COINBASE_PORTFOLIO_ID")
        if not key or not portfolio:
            raise RuntimeError(
                "Set COINBASE_KEY_FILE and COINBASE_PORTFOLIO_ID locally"
            )
        return cls(
            settings,
            ledger,
            RESTClient(api_key=None, api_secret=None, key_file=key, timeout=10),
            portfolio,
        )

    def accounts(self):
        result = {}
        cursor = None
        seen = set()
        while True:
            d = unwrap(
                self.client.get_accounts(
                    limit=250, cursor=cursor, retail_portfolio_id=self.portfolio
                )
            )
            for a in d.get("accounts", []):
                if a.get("retail_portfolio_id") != self.portfolio:
                    raise RuntimeError("Account portfolio mismatch")
                currency = a["currency"]
                available = D(a["available_balance"]["value"])
                hold = D(a["hold"]["value"])
                if min(available, hold) < 0 or hold:
                    raise RuntimeError("Negative or reserved external account balance")
                result[currency] = result.get(currency, D(0)) + available
            if not d.get("has_next"):
                break
            cursor = d.get("cursor")
            if not cursor or cursor in seen:
                raise RuntimeError("Invalid account pagination")
            seen.add(cursor)
        return result

    def preflight(self):
        permissions = unwrap(self.client.get_api_key_permissions())
        if (
            permissions.get("can_view") is not True
            or permissions.get("can_trade") is not True
            or permissions.get("can_transfer") is not False
        ):
            raise RuntimeError(
                "Require View + Trade, with Transfer explicitly disabled"
            )
        if permissions.get("portfolio_uuid") != self.portfolio:
            raise RuntimeError("API key is not scoped to the configured portfolio")
        self.reconcile()
        balances = self.accounts()
        if not self.l.get("live_initialized"):
            if (
                self.l.get("tick")
                or self.l.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            ):
                raise RuntimeError("Uninitialized live ledger already has activity")
            if any(v for k, v in balances.items() if k != "USDC"):
                raise RuntimeError("Start with only USDC in a dedicated portfolio")
            cash = balances.get("USDC", D(0))
            if not 0 < cash <= D(self.s.capital):
                raise RuntimeError(
                    "Fund dedicated portfolio with 0 < USDC <= configured $100 cap"
                )
            with self.l.transaction():
                for k in ["cash", "initial_cash", "anchor"]:
                    self.l.put(k, str(cash))
                self.l.put("live_initialized", True)
        self.verify_balances()
        return {"mode": "live", "portfolio_scoped": True, "withdrawals_disabled": True}

    def verify_balances(self):
        actual = self.accounts()
        expected = {"USDC": self.l.cash}
        for p, amount in self.l.positions.items():
            expected[p.split("-")[0]] = amount
        for currency in set(actual) | set(expected):
            tolerance = D(".02") if currency == "USDC" else D(".00000001")
            if (
                abs(actual.get(currency, D(0)) - expected.get(currency, D(0)))
                > tolerance
            ):
                raise RuntimeError(
                    "External balance change; stop and reconcile rather than treat deposits as profit"
                )
        open_orders = unwrap(
            self.client.list_orders(
                order_status=["OPEN"], retail_portfolio_id=self.portfolio, limit=1
            )
        )
        if open_orders.get("orders"):
            raise RuntimeError("External/open order in dedicated portfolio")

    def execute(self, p, before_submit):
        cid = p["client_order_id"]
        side = p["side"]
        common = {
            "product_id": p["product"],
            "base_size": p["base_size"],
            "limit_price": p["limit_price"],
            "retail_portfolio_id": self.portfolio,
        }
        try:
            preview = unwrap(self.client.preview_limit_order_fok(side=side, **common))
            if preview.get("errs") or preview.get("warning"):
                raise Veto("Coinbase preview rejected or warned")
            if "commission_total" not in preview:
                raise Veto("Preview did not include fees")
            fee = D(preview["commission_total"])
            if fee < 0 or fee > D(p["fee_ceiling"]):
                raise Veto("Fee ceiling exceeded")
            if time.time() - p["quote_timestamp"] > self.s.max_quote_age:
                raise Veto("Quote expired during preview")
            self.verify_balances()
            before_submit(p)
        except Exception:
            self.l.mark(cid, "REJECTED")
            raise
        # This durable transition precedes any request that can place an order.
        self.l.mark(cid, "UNKNOWN")
        try:
            r = unwrap(
                self.client.limit_order_fok(client_order_id=cid, side=side, **common)
            )
        except Exception as e:
            raise UnresolvedOrder(
                "Submission outcome unknown; reconcile before any further trade"
            ) from e
        if r.get("success") is False:
            self.l.mark(cid, "REJECTED")
            return {"status": "REJECTED", "mode": "live"}
        oid = r.get("success_response", {}).get("order_id")
        if r.get("success") is not True or not oid:
            raise UnresolvedOrder("Exchange response lacks an unambiguous order ID")
        self.l.mark(cid, "ACCEPTED", oid)
        deadline = time.monotonic() + 30
        while True:
            if self._settle(cid, oid, p):
                return {"mode": "live", "status": "SETTLED", "client_order_id": cid}
            if time.monotonic() >= deadline:
                break
            time.sleep(1)
        # FOK should be terminal. Do not assume that a timeout implies no fill.
        raise UnresolvedOrder("Order is not terminal; live execution stopped")

    def _settle(self, cid, oid, p):
        r = unwrap(self.client.get_order(oid)).get("order", {})
        if (
            r.get("order_id") != oid
            or r.get("client_order_id") != cid
            or r.get("product_id") != p["product"]
            or r.get("side") != p["side"]
        ):
            raise UnresolvedOrder("Order identity mismatch")
        if r.get("status") not in TERMINAL:
            return False
        for key in ["filled_size", "filled_value", "total_fees"]:
            if key not in r:
                raise UnresolvedOrder("Final order lacks fill/fee accounting")
        self.l.settle(cid, r["filled_size"], r["filled_value"], r["total_fees"])
        return True

    def reconcile(self):
        for row in self.l.pending():
            cid = row["id"]
            p = row["plan"]
            oid = row["exchange_id"]
            if row["status"] == "PREPARED":
                # Network submission cannot have happened before UNKNOWN.
                self.l.mark(cid, "REJECTED")
                continue
            if not oid:
                cursor = None
                seen = set()
                found = []
                while True:
                    r = unwrap(
                        self.client.list_orders(
                            start_date=datetime.fromtimestamp(
                                row["created"] - 60, timezone.utc
                            ).isoformat(),
                            retail_portfolio_id=self.portfolio,
                            cursor=cursor,
                            limit=100,
                        )
                    )
                    found += [
                        o
                        for o in r.get("orders", [])
                        if o.get("client_order_id") == cid
                    ]
                    if not r.get("has_next"):
                        break
                    cursor = r.get("cursor")
                    if not cursor or cursor in seen:
                        raise UnresolvedOrder("Order pagination failed")
                    seen.add(cursor)
                if len(found) != 1:
                    raise UnresolvedOrder(
                        "Uncertain submission not uniquely found. Check Coinbase; no automatic resubmission."
                    )
                oid = found[0]["order_id"]
                self.l.mark(cid, "ACCEPTED", oid)
            if not self._settle(cid, oid, p):
                raise UnresolvedOrder("Order still pending at Coinbase")


# ==================== Binance Broker ====================

import hashlib
import hmac
import json
import urllib.parse
import urllib.request


class BinanceBroker:
    """Binance Spot API execution with HMAC-signed REST calls.

    Uses market orders for immediate fill. Requires API key with Spot Trading
    (READ + TRADE) but MUST NOT have withdrawal permission.
    Defaults to testnet; set BINANCE_TESTNET=false for real trading.
    """
    mode = "live"

    TESTNET_BASE = "https://testnet.binance.vision"
    MAINNET_BASE = "https://api.binance.com"

    def __init__(self, settings, ledger, api_key, api_secret, base_url, symbol="BTCUSDT"):
        self.s = settings
        self.l = ledger
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8")
        self.base_url = base_url
        self.symbol = symbol

    @classmethod
    def from_env(cls, settings, ledger):
        if os.environ.get("STONKFLY_LIVE") != "I_ACCEPT_REAL_TRADES":
            raise RuntimeError("Live opt-in missing: set STONKFLY_LIVE=I_ACCEPT_REAL_TRADES")
        api_key = os.environ.get("BINANCE_API_KEY")
        api_secret = os.environ.get("BINANCE_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError("Set BINANCE_API_KEY and BINANCE_API_SECRET")
        testnet = os.environ.get("BINANCE_TESTNET", "true").lower() != "false"
        base_url = cls.TESTNET_BASE if testnet else cls.MAINNET_BASE
        symbol = os.environ.get("BINANCE_SYMBOL", "BTCUSDT")
        return cls(settings, ledger, api_key, api_secret, base_url, symbol)

    def _sign(self, params):
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    def _request(self, method, path, params=None, signed=False):
        url = f"{self.base_url}{path}"
        headers = {"User-Agent": "stonkfly/1.0", "X-MBX-APIKEY": self.api_key}
        if signed:
            if params is None:
                params = {}
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            url = f"{url}?{self._sign(params)}"
        else:
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, data=None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Binance {method} {path} -> {e.code}: {body}")

    def _get_account(self):
        return self._request("GET", "/api/v3/account", signed=True)

    def _get_open_orders(self):
        return self._request("GET", "/api/v3/openOrders", {"symbol": self.symbol}, signed=True)

    def accounts(self):
        acc = self._get_account()
        result = {}
        for b in acc.get("balances", []):
            free = D(b["free"])
            locked = D(b["locked"])
            total = free + locked
            if total > 0:
                result[b["asset"]] = total
        return result

    def preflight(self):
        balances = self.accounts()
        open_orders = self._get_open_orders()
        if open_orders:
            raise RuntimeError("Open orders exist on Binance; cancel them first")
        if not self.l.get("live_initialized"):
            if self.l.get("tick") or self.l.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
                raise RuntimeError("Uninitialized live ledger already has activity")
            usdt = balances.get("USDT", D(0))
            if usdt <= 0:
                raise RuntimeError("No USDT balance in Binance account")
            if usdt > D(self.s.capital):
                raise RuntimeError(f"Binance USDT balance (${usdt}) exceeds configured cap (${self.s.capital})")
            with self.l.transaction():
                for k in ["cash", "initial_cash", "anchor"]:
                    self.l.put(k, str(usdt))
                self.l.put("live_initialized", True)
                self.l.put("exchange", "binance")
                self.l.put("symbol", self.symbol)
        self.verify_balances()
        network = "testnet" if "testnet" in self.base_url else "mainnet"
        return {"mode": "live", "exchange": "binance", "network": network, "symbol": self.symbol}

    def verify_balances(self):
        actual = self.accounts()
        expected = {"USDT": self.l.cash}
        for p, amount in self.l.positions.items():
            base = p.split("-")[0].replace("USDT", "").replace("USDC", "")
            expected[base] = amount
        for currency in set(actual) | set(expected):
            if currency not in ("USDT", "BTC", "ETH", "SOL", "BNB"):
                continue
            tolerance = D("0.01") if currency == "USDT" else D("0.00000001")
            diff = abs(actual.get(currency, D(0)) - expected.get(currency, D(0)))
            if diff > tolerance:
                raise RuntimeError(
                    f"Balance mismatch {currency}: actual={actual.get(currency, 0)} expected={expected.get(currency, 0)}"
                )

    def execute(self, plan, before_submit):
        cid = plan["client_order_id"]
        side = plan["side"]
        base_size = D(plan["base_size"])
        params = {
            "symbol": self.symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(base_size),
            "newClientOrderId": cid,
            "newOrderRespType": "FULL",
        }
        try:
            self.verify_balances()
            before_submit(plan)
        except Exception:
            self.l.mark(cid, "REJECTED")
            raise
        self.l.mark(cid, "UNKNOWN")
        try:
            result = self._request("POST", "/api/v3/order", params, signed=True)
        except Exception as e:
            raise UnresolvedOrder(f"Binance order submission unknown: {e}") from e
        status = result.get("status", "")
        if status in ("REJECTED", "EXPIRED"):
            self.l.mark(cid, "REJECTED")
            return {"status": "REJECTED", "mode": "live", "error": result.get("msg", "")}
        oid = result.get("orderId")
        if not oid:
            raise UnresolvedOrder("Binance response lacks orderId")
        self.l.mark(cid, "ACCEPTED", str(oid))
        fills = result.get("fills", [])
        if fills:
            total_qty = D(0)
            total_value = D(0)
            total_fee = D(0)
            for f in fills:
                total_qty += D(f["qty"])
                total_value += D(f["qty"]) * D(f["price"])
                total_fee += D(f["commission"])
            self.l.settle(cid, str(total_qty), str(total_value), str(total_fee))
            return {"mode": "live", "status": "SETTLED", "client_order_id": cid, "order_id": oid}
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(1)
            order = self._request("GET", "/api/v3/order", {"symbol": self.symbol, "orderId": oid}, signed=True)
            if order.get("status") in TERMINAL:
                self.l.settle(cid, order["executedQty"], str(D(order["executedQty"]) * D(order["price"])), "0")
                return {"mode": "live", "status": "SETTLED", "client_order_id": cid}
        raise UnresolvedOrder("Binance order not terminal after 30s")

    def reconcile(self):
        for row in self.l.pending():
            cid = row["id"]
            p = row["plan"]
            oid = row["exchange_id"]
            if row["status"] == "PREPARED":
                self.l.mark(cid, "REJECTED")
                continue
            if not oid:
                orders = self._request("GET", "/api/v3/allOrders", {"symbol": self.symbol, "limit": 50}, signed=True)
                found = [o for o in orders if o.get("clientOrderId") == cid]
                if len(found) != 1:
                    raise UnresolvedOrder(f"Order {cid} not uniquely found on Binance")
                oid = str(found[0]["orderId"])
                self.l.mark(cid, "ACCEPTED", oid)
            order = self._request("GET", "/api/v3/order", {"symbol": self.symbol, "orderId": int(oid)}, signed=True)
            if order.get("status") not in TERMINAL:
                raise UnresolvedOrder(f"Order {cid} still pending at Binance")
            self.l.settle(cid, order["executedQty"], str(D(order["executedQty"]) * D(order["price"])), "0")
