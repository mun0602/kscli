"""Account manager — handle 5sim phone acquisition & Kuaishou login."""
from __future__ import annotations

import logging
import os
import time

import uiautomator2 as u2

from kscli.core.sms_5sim import FiveSimAPI

log = logging.getLogger(__name__)

DEFAULT_COUNTRY = "vietnam"
DEFAULT_OPERATOR = "any"
DEFAULT_PRODUCT = "kwai"

APP_PACKAGE = "com.smile.gifmaker"


class KuaishouAccountManager:
    """Handle Kuaishou login flow."""

    # UI selectors verified on English build
    RID_PHONE_INPUT = "com.smile.gifmaker:id/et_phone"
    RID_GET_CODE_BTN = "com.smile.gifmaker:id/btn_get_code"
    RID_CODE_INPUT = "com.smile.gifmaker:id/et_code"
    RID_LOGIN_BTN = "com.smile.gifmaker:id/btn_login"
    RID_REGISTER_BTN = "com.smile.gifmaker:id/btn_register"
    RID_ME_TAB = "com.smile.gifmaker:id/bottom_nav_account"

    # Backup selectors (text-based)
    TXT_GET_CODE = "获取验证码"
    TXT_LOGIN = "登录"
    TXT_REGISTER = "注册"
    TXT_ME = "Me"
    TXT_MY_PROFILE = "My Profile"

    def __init__(self, api_key: str | None = None):
        """Initialize with optional API key (can load from env/config later)."""
        self.api_key = api_key or os.getenv("KUAISHOU_5SIM_API_KEY", "")
        self.fivesim: FiveSimAPI | None = FiveSimAPI(self.api_key) if self.api_key else None

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
        """Navigate to login screen: Open app -> Me tab -> Login button."""
        log.info("[Login] Opening Kuaishou app...")
        d.app_start(APP_PACKAGE)
        time.sleep(3)

        log.info("[Login] Navigating to Me tab...")
        me_tab = self._find_element(d, rid=self.RID_ME_TAB, txt=self.TXT_ME)
        if me_tab:
            me_tab.click()
            log.info("[Login] Clicked Me tab")
            time.sleep(2)
        else:
            log.warning("[Login] Me tab not found, assume already on Me")

        if self._detect_login_screen(d):
            log.info("[Login] Login screen detected")
            return True

        log.info("[Login] Looking for Login button...")
        login_btn = self._find_element(
            d,
            rid=self.RID_LOGIN_BTN,
            txt=self.TXT_LOGIN,
            desc="Login"
        )
        if login_btn:
            login_btn.click()
            log.info("[Login] Clicked Login button")
            time.sleep(2)
            return True

        if self._find_element(d, rid=self.RID_PHONE_INPUT):
            log.info("[Login] Phone input found, ready to type")
            return True

        log.error("[Login] Cannot navigate to login screen")
        return False

    def _detect_login_screen(self, d: u2.Device) -> bool:
        """Check if login screen is visible."""
        if d(text="请输入手机号").exists:
            return True
        if d(textContains="phone").exists:
            return True
        if d(resourceId=self.RID_PHONE_INPUT).exists:
            return True
        return False

    def _enter_phone_and_request_otp(self, d: u2.Device, phone: str) -> bool:
        """Enter phone number and tap 'Get Code' button.

        Returns True if the OTP request was sent successfully.
        """
        phone_input = self._find_element(d, rid=self.RID_PHONE_INPUT)
        if not phone_input:
            log.error("[Login] Không tìm ô nhập số điện thoại")
            return False

        phone_input.click()
        phone_input.clear_text()
        phone_clean = phone.replace("+", "").replace(" ", "")
        phone_input.set_text(phone_clean)
        log.info(f"[Login] Đã nhập SĐT: {phone_clean}")
        time.sleep(1.5)

        get_code_btn = self._find_element(
            d,
            rid=self.RID_GET_CODE_BTN,
            txt=self.TXT_GET_CODE,
        )
        if not get_code_btn:
            log.error("[Login] Không tìm nút 'Lấy mã'")
            return False

        get_code_btn.click()
        log.info("[Login] Clicked 'Lấy mã'")
        time.sleep(2.0)
        return True

    def _enter_otp_and_login(self, d: u2.Device, otp: str) -> bool:
        """Enter OTP code and tap Login button."""
        code_input = self._find_element(d, rid=self.RID_CODE_INPUT)
        if not code_input:
            log.error("[Login] Không tìm ô nhập OTP")
            return False
        code_input.click()
        code_input.clear_text()
        code_input.set_text(otp)
        log.info("[Login] Đã nhập OTP")
        time.sleep(1.5)
        return self._tap_login(d)

    def _enter_password_and_login(self, d: u2.Device, password: str) -> bool:
        """Enter password and tap Login button."""
        pwd_input = self._find_element(d, rid="com.smile.gifmaker:id/et_password")
        if not pwd_input:
            log.error("[Login] Không tìm ô nhập password")
            return False
        pwd_input.click()
        pwd_input.clear_text()
        pwd_input.set_text(password)
        log.info("[Login] Đã nhập password")
        time.sleep(1.5)
        return self._tap_login(d)

    def _tap_login(self, d: u2.Device) -> bool:
        """Tap login button and verify success."""
        login_btn = self._find_element(
            d,
            rid=self.RID_LOGIN_BTN,
            txt=self.TXT_LOGIN,
        )
        if not login_btn:
            log.error("[Login] Không tìm nút 'Login'")
            return False

        login_btn.click()
        log.info("[Login] Clicked 'Login'")
        time.sleep(3.0)

        if self._detect_login_screen(d):
            log.error("[Login] Login thất bại, vẫn ở login screen")
            return False

        log.info("[Login] Login thành công!")
        return True

    def login_otp(
        self,
        d: u2.Device,
        phone: str,
        otp: str = "",
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
        log.info(f"[Login] Bắt đầu login: {phone}")

        if not self._navigate_to_login_screen(d):
            log.error("[Login] Cannot navigate to login screen")
            return False

        if not self._enter_phone_and_request_otp(d, phone):
            return False

        if use_password:
            if not password:
                log.error("[Login] Không có password")
                return False
            return self._enter_password_and_login(d, password)
        else:
            if not otp:
                log.error("[Login] Không có OTP")
                return False
            return self._enter_otp_and_login(d, otp)

    def auto_login_with_5sim(
        self,
        d: u2.Device,
        use_password: str | None = None,
        country: str = DEFAULT_COUNTRY,
        operator: str = DEFAULT_OPERATOR,
        product: str = DEFAULT_PRODUCT,
    ) -> bool:
        """Auto-login using 5SIM phone number.

        Fixed flow:
          1. Buy phone number from 5SIM
          2. Navigate to login screen
          3. Enter phone number and tap 'Get Code'
          4. Poll 5SIM for the OTP SMS
          5. Enter OTP and login

        Args:
            d: uiautomator2 device
            use_password: If set, use this password instead of OTP
            country: 5SIM country code
            operator: 5SIM operator
            product: 5SIM product

        Returns:
            True if successful
        """
        if not self.fivesim:
            log.error("[Login] 5SIM API key không được cấu hình")
            return False

        # Step 1: Buy phone number
        log.info(f"[Login] Mua SĐT từ 5SIM ({country}/{operator}/{product})...")
        try:
            order = self.fivesim.buy_number(country=country, operator=operator, product=product)
            log.info(f"[Login] Có SĐT: {order.phone} (order #{order.order_id})")
        except Exception as e:
            log.error(f"[Login] Lỗi mua SĐT: {e}")
            return False

        phone = order.phone
        if phone.startswith("+"):
            phone = phone[1:]

        # Step 2: Navigate to login screen
        if not self._navigate_to_login_screen(d):
            log.error("[Login] Cannot navigate to login screen")
            self.fivesim.cancel_order(order.order_id)
            return False

        # Step 3: Enter phone and request OTP
        if not self._enter_phone_and_request_otp(d, phone):
            self.fivesim.cancel_order(order.order_id)
            return False

        if use_password:
            # Password mode — skip SMS polling
            success = self._enter_password_and_login(d, use_password)
        else:
            # Step 4: Poll 5SIM for SMS (now AFTER requesting OTP from app)
            log.info("[Login] Chờ OTP từ 5SIM...")
            otp = self.fivesim.wait_for_sms(order.order_id)
            if not otp:
                log.error("[Login] Không nhận OTP")
                self.fivesim.cancel_order(order.order_id)
                return False

            # Step 5: Enter OTP and login
            success = self._enter_otp_and_login(d, otp)

        if success:
            try:
                self.fivesim.finish_order(order.order_id)
                log.info(f"[Login] Đánh dấu order #{order.order_id} hoàn thành")
            except Exception as e:
                log.warning(f"[Login] Lỗi finish order: {e}")
        else:
            try:
                self.fivesim.cancel_order(order.order_id)
            except Exception:
                pass

        return success
