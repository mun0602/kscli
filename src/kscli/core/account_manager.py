"""Account manager — handle 5sim phone acquisition & Kuaishou login."""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

import requests
import uiautomator2 as u2

log = logging.getLogger(__name__)

# 5SIM API base
BASE_URL = "https://5sim.net/v1/user"
DEFAULT_COUNTRY = "vietnam"
DEFAULT_OPERATOR = "any"
DEFAULT_PRODUCT = "kuaishou"  # fallback: use "other" if not available


@dataclass
class PhoneOrder:
    """Represents a 5sim phone order."""
    order_id: int
    phone: str
    status: str  # PENDING, RECEIVED, FINISHED, CANCELED, BANNED
    country: str
    operator: str
    product: str
    created_at: str
    expires: str


class FiveSim:
    """Simple 5SIM API wrapper."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("5SIM API key tidak boleh kosong")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    def buy_activation(
        self,
        country: str = DEFAULT_COUNTRY,
        operator: str = DEFAULT_OPERATOR,
        product: str = DEFAULT_PRODUCT,
    ) -> PhoneOrder:
        """Buy a virtual phone number for activation."""
        url = f"{BASE_URL}/buy/activation/{country}/{operator}/{product}"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return PhoneOrder(
            order_id=data.get("id"),
            phone=data.get("phone"),
            status=data.get("status"),
            country=data.get("country"),
            operator=data.get("operator"),
            product=data.get("product"),
            created_at=data.get("created_at"),
            expires=data.get("expires"),
        )

    def check_order(self, order_id: int) -> dict:
        """Check order status & get SMS."""
        url = f"{BASE_URL}/check/{order_id}"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def finish_order(self, order_id: int) -> dict:
        """Mark order as finished."""
        url = f"{BASE_URL}/finish/{order_id}"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_sms(self, order_id: int, retry_count: int = 30, retry_delay: float = 2.0) -> str | None:
        """Poll for SMS OTP code. Return code or None if timeout."""
        for attempt in range(retry_count):
            try:
                order = self.check_order(order_id)
                sms_list = order.get("sms") or []
                if sms_list:
                    # Return first code found
                    code = sms_list[0].get("code")
                    if code:
                        log.info(f"✅ OTP nhận được: {code}")
                        return code
            except Exception as e:
                log.warning(f"Lỗi check order #{order_id}: {e}")

            if attempt < retry_count - 1:
                time.sleep(retry_delay)

        return None


class KuaishouAccountManager:
    """Handle Kuaishou login flow."""

    # UI selectors verified on English build
    RID_PHONE_INPUT = "com.smile.gifmaker:id/et_phone"
    RID_GET_CODE_BTN = "com.smile.gifmaker:id/btn_get_code"
    RID_CODE_INPUT = "com.smile.gifmaker:id/et_code"
    RID_LOGIN_BTN = "com.smile.gifmaker:id/btn_login"
    RID_REGISTER_BTN = "com.smile.gifmaker:id/btn_register"
    RID_ME_TAB = "com.smile.gifmaker:id/bottom_nav_account"  # Me tab in bottom navigation
    
    # Backup selectors (text-based)
    TXT_GET_CODE = "获取验证码"
    TXT_LOGIN = "登录"
    TXT_REGISTER = "注册"
    TXT_ME = "Me"
    TXT_MY_PROFILE = "My Profile"

    def __init__(self, api_key: str | None = None):
        """Initialize with optional API key (can load from env/config later)."""
        self.api_key = api_key or os.getenv("KUAISHOU_5SIM_API_KEY", "")
        self.fivesim = FiveSim(self.api_key) if self.api_key else None

    def _find_element(self, d: u2.Device, rid: str = "", txt: str = "", desc: str = ""):
        """Try to find element by resourceId, text, or description."""
        if rid:
            elem = d(resourceId=rid)
            if elem.exists:
                return elem
        if txt:
            elem = d(text=txt)
            if elem.exists:
                return elem
        if desc:
            elem = d(description=desc)
            if elem.exists:
                return elem
        return None

    def _navigate_to_login_screen(self, d: u2.Device) -> bool:
        """Navigate to login screen: Open app → Me tab → Login button."""
        # Step 1: Open Kuaishou app
        log.info("1️⃣  Opening Kuaishou app...")
        d.app_start("com.smile.gifmaker")
        time.sleep(3)
        
        # Step 2: Click "Me" tab (bottom navigation)
        log.info("2️⃣  Navigating to Me tab...")
        me_tab = self._find_element(d, rid=self.RID_ME_TAB, txt=self.TXT_ME)
        if me_tab:
            me_tab.click()
            log.info("   ✅ Clicked Me tab")
            time.sleep(2)
        else:
            log.warning("   ⚠️  Me tab not found, assume already on Me")
        
        # Step 3: Check if login screen is visible
        if self._detect_login_screen(d):
            log.info("   ✅ Login screen detected")
            return True
        
        # Step 4: Try to find and click "Login" button
        log.info("3️⃣  Looking for Login button...")
        login_btn = self._find_element(
            d,
            rid=self.RID_LOGIN_BTN,
            txt=self.TXT_LOGIN,
            desc="Login"
        )
        if login_btn:
            login_btn.click()
            log.info("   ✅ Clicked Login button")
            time.sleep(2)
            return True
        
        # Step 5: Try to find and click phone input directly
        if self._find_element(d, rid=self.RID_PHONE_INPUT):
            log.info("   ✅ Phone input found, ready to type")
            return True
        
        log.error("   ❌ Cannot navigate to login screen")
        return False

    def _detect_login_screen(self, d: u2.Device) -> bool:
        """Check if login screen is visible."""
        # Vietnamese: 请输入手机号 / English: Enter phone number
        if d(text="请输入手机号").exists:
            return True
        if d(textContains="phone").exists:
            return True
        if d(resourceId=self.RID_PHONE_INPUT).exists:
            return True
        return False

    def login_otp(
        self,
        d: u2.Device,
        phone: str,
        otp: str,
        password: str | None = None,
        use_password: bool = False,
    ) -> bool:
        """Login using OTP or password.
        
        Args:
            d: uiautomator2 device
            phone: Phone number (with country prefix like +84...)
            otp: OTP code if use_password=False
            password: Password if use_password=True
            use_password: If True, use password instead of OTP
        
        Returns:
            True if login successful
        """
        log.info(f"📱 Bắt đầu login: {phone}")

        # Step 0: Navigate to login screen
        if not self._navigate_to_login_screen(d):
            log.error("❌ Cannot navigate to login screen")
            return False

        # Step 1: Enter phone
        phone_input = self._find_element(d, rid=self.RID_PHONE_INPUT)
        if not phone_input:
            log.error("❌ Không tìm ô nhập số điện thoại")
            return False
        
        phone_input.click()
        phone_input.clear_text()
        # Kuaishou VN có thể cần nhập without +, chỉ 10 chữ số
        phone_clean = phone.replace("+", "").replace(" ", "")
        phone_input.set_text(phone_clean)
        log.info(f"  📲 Đã nhập SĐT: {phone_clean}")
        time.sleep(1.5)

        # Step 2: Get code button
        get_code_btn = self._find_element(
            d,
            rid=self.RID_GET_CODE_BTN,
            txt=self.TXT_GET_CODE,
        )
        if not get_code_btn:
            log.error("❌ Không tìm nút 'Lấy mã'")
            return False
        
        get_code_btn.click()
        log.info("  📬 Clicked 'Lấy mã'")
        time.sleep(2.0)

        # Step 3: Enter OTP/Password
        if not use_password:
            if not otp:
                log.error("❌ Không có OTP")
                return False
            code_input = self._find_element(d, rid=self.RID_CODE_INPUT)
            if not code_input:
                log.error("❌ Không tìm ô nhập OTP")
                return False
            code_input.click()
            code_input.clear_text()
            code_input.set_text(otp)
            log.info(f"  🔐 Đã nhập OTP: {otp}")
        else:
            if not password:
                log.error("❌ Không có password")
                return False
            pwd_input = self._find_element(d, rid="com.smile.gifmaker:id/et_password")
            if not pwd_input:
                log.error("❌ Không tìm ô nhập password")
                return False
            pwd_input.click()
            pwd_input.clear_text()
            pwd_input.set_text(password)
            log.info(f"  🔑 Đã nhập password")

        time.sleep(1.5)

        # Step 4: Login button
        login_btn = self._find_element(
            d,
            rid=self.RID_LOGIN_BTN,
            txt=self.TXT_LOGIN,
        )
        if not login_btn:
            log.error("❌ Không tìm nút 'Login'")
            return False
        
        login_btn.click()
        log.info("  🔓 Clicked 'Login'")
        time.sleep(3.0)

        # Step 5: Verify login success — nếu vẫn thấy login screen = fail
        if self._detect_login_screen(d):
            log.error("❌ Login thất bại, vẫn ở login screen")
            return False

        log.info("  ✅ Login thành công!")
        return True

    def auto_login_with_5sim(
        self,
        d: u2.Device,
        use_password: str | None = None,
        country: str = DEFAULT_COUNTRY,
        operator: str = DEFAULT_OPERATOR,
        product: str = DEFAULT_PRODUCT,
    ) -> bool:
        """Auto-login using 5SIM phone number.
        
        Args:
            d: uiautomator2 device
            use_password: If set, use this password instead of OTP
            country: 5SIM country code (default: vietnam)
            operator: 5SIM operator (default: any)
            product: 5SIM product (default: kuaishou)
        
        Returns:
            True if successful
        """
        if not self.fivesim:
            log.error("❌ 5SIM API key không được cấu hình")
            return False

        # Buy activation
        log.info(f"🛒 Mua SĐT từ 5SIM ({country}/{operator}/{product})...")
        try:
            order = self.fivesim.buy_activation(country=country, operator=operator, product=product)
            log.info(f"  ✅ Có SĐT: {order.phone} (order #{order.order_id})")
        except Exception as e:
            log.error(f"  ❌ Lỗi mua SĐT: {e}")
            return False

        # Get OTP
        if not use_password:
            log.info("📨 Chờ OTP...")
            otp = self.fivesim.get_sms(order.order_id)
            if not otp:
                log.error("  ❌ Không nhận OTP")
                return False
        else:
            otp = None

        # Login
        phone = order.phone
        if phone.startswith("+"):
            phone = phone[1:]  # Remove +
        
        success = self.login_otp(
            d,
            phone=phone,
            otp=otp or "",
            password=use_password,
            use_password=bool(use_password),
        )

        if success:
            # Mark order as finished
            try:
                self.fivesim.finish_order(order.order_id)
                log.info(f"  ✅ Đánh dấu order #{order.order_id} hoàn thành")
            except Exception as e:
                log.warning(f"  ⚠ Lỗi finish order: {e}")

        return success
