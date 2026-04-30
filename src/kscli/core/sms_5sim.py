"""Unified 5SIM API client.

Replaces the three separate wrappers (sms_5sim.FiveSimAPI,
register_flow.FiveSimClient, account_manager.FiveSim) with a single
implementation.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://5sim.net/v1"
REQUEST_TIMEOUT = 15


@dataclass
class PhoneOrder:
    """Represents a 5SIM phone order."""
    order_id: int
    phone: str
    status: str
    country: str
    operator: str
    product: str


class FiveSimAPI:
    """Single 5SIM API wrapper used across the entire project."""

    def __init__(self, token: str):
        if not token:
            raise ValueError("5SIM API token must not be empty")
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _get(self, path: str) -> dict:
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers=self.headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Profile ───────────────────────────────────────────────

    def get_profile(self) -> dict:
        return self._get("/user/profile")

    def get_balance(self) -> float:
        return self.get_profile().get("balance", 0)

    # ── Orders ────────────────────────────────────────────────

    def buy_number(
        self,
        country: str = "england",
        operator: str = "any",
        product: str = "kwai",
    ) -> PhoneOrder:
        """Buy a virtual phone number for activation."""
        data = self._get(f"/user/buy/activation/{country}/{operator}/{product}")
        return PhoneOrder(
            order_id=data["id"],
            phone=data.get("phone", ""),
            status=data.get("status", ""),
            country=data.get("country", country),
            operator=data.get("operator", operator),
            product=data.get("product", product),
        )

    def check_order(self, order_id: int) -> dict:
        return self._get(f"/user/check/{order_id}")

    def finish_order(self, order_id: int) -> dict:
        return self._get(f"/user/finish/{order_id}")

    def cancel_order(self, order_id: int) -> dict:
        return self._get(f"/user/cancel/{order_id}")

    # ── SMS polling ───────────────────────────────────────────

    def wait_for_sms(self, order_id: int, timeout: int = 180) -> str | None:
        """Poll until an SMS code arrives or *timeout* seconds elapse.

        Returns the OTP code string, or ``None`` on timeout / cancellation.
        """
        deadline = time.time() + timeout
        log.info(f"[5SIM] Chờ SMS cho order #{order_id} (max {timeout}s)...")

        while time.time() < deadline:
            try:
                data = self.check_order(order_id)
                status = data.get("status", "")

                if status in ("CANCELED", "EXPIRED", "TIMEOUT"):
                    log.error(f"[5SIM] Order #{order_id} {status}.")
                    return None

                sms_list = data.get("sms") or []
                if sms_list:
                    code = sms_list[0].get("code")
                    if not code:
                        raw = sms_list[0].get("text", "")
                        m = re.search(r"\b(\d{4,6})\b", raw)
                        if m:
                            code = m.group(1)
                    if code:
                        log.info(f"[5SIM] OTP nhận được cho order #{order_id}")
                        return code
            except Exception as e:
                log.warning(f"[5SIM] check_order lỗi: {e}")

            time.sleep(5)

        log.error(f"[5SIM] Hết thời gian chờ SMS ({timeout}s).")
        return None
