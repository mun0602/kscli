from __future__ import annotations

import logging
import requests
import time

log = logging.getLogger(__name__)

class FiveSimAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://5sim.net/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def get_profile(self) -> dict:
        url = f"{self.base_url}/user/profile"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def buy_number(self, country: str = "england", operator: str = "any", product: str = "kwai") -> dict:
        url = f"{self.base_url}/user/buy/activation/{country}/{operator}/{product}"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code != 200:
            log.error(f"[5SIM] Buy error: {resp.text}")
            resp.raise_for_status()
        return resp.json()

    def check_order(self, order_id: int) -> dict:
        url = f"{self.base_url}/user/check/{order_id}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def finish_order(self, order_id: int) -> dict:
        url = f"{self.base_url}/user/finish/{order_id}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: int) -> dict:
        url = f"{self.base_url}/user/cancel/{order_id}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def wait_for_sms(self, order_id: int, timeout: int = 180) -> str | None:
        """Wait for SMS code."""
        start = time.time()
        log.info(f"[5SIM] Đang chờ SMS cho order {order_id}...")
        while time.time() - start < timeout:
            data = self.check_order(order_id)
            if data.get("status") == "FINISHED" or data.get("sms"):
                sms_list = data.get("sms", [])
                if sms_list:
                    code = sms_list[0].get("code")
                    log.info(f"[5SIM] Đã nhận code: {code}")
                    return code
            time.sleep(5)
        log.error(f"[5SIM] Hết thời gian chờ SMS ({timeout}s).")
        return None
