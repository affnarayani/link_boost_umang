# login.py
# Automates LinkedIn login with Selenium (non-headless, maximized window)
# Adds session cookie management and CAPTCHA challenge handling.

import os
import sys
import time
import json
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL = "https://www.linkedin.com/login?fromSignIn=true&trk=guest_homepage-basic_nav-header-signin"
HOME_URL = "https://www.linkedin.com/feed/"
BASE_URL = "https://www.linkedin.com/"
CHALLENGE_PREFIX = "https://www.linkedin.com/checkpoint/challenge"
CHALLENGE_V2_PREFIX = "https://www.linkedin.com/checkpoint/challengesV2/"

# XPaths provided in the requirements
X_USERNAME = '//*[@id="username"]'
X_PASSWORD = '//*[@id="password"]'
X_REMEMBER_ME_LABEL = '//*[@id="organic-div"]/form/div[3]/label'
X_SIGN_IN_BUTTON = '//*[@id="organic-div"]/form/div[4]/button'

# Store only the LinkedIn session cookie (li_at) to disk
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies.json")
ENCRYPTED_COOKIE_FILE = os.path.join(os.path.dirname(__file__), "cookies.json.encrypted")
ENCRYPTED_COOKIE_FILES = [
    os.path.join(os.path.dirname(__file__), "cookies.json.encrypted"),
    os.path.join(os.path.dirname(__file__), "cookies.json.encrypt"),  # alt name
]
SESSION_COOKIE_NAME = "li_at"

# IST timezone (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def _build_driver() -> webdriver.Chrome:
    """Create a Chrome WebDriver with desired options and return it."""
    chrome_options = Options()

    # Read headless preference from environment
    headless_env = os.getenv("HEADLESS", "").strip().lower()
    is_headless = headless_env in {"1", "true", "yes", "y"}

    if is_headless:
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")
    else:
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_experimental_option("detach", True)

    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])  # Reduce console noise on Windows
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    if not is_headless:
        try:
            driver.maximize_window()
        except Exception:
            pass

    return driver


# -------------------------
# Cookie helpers
# -------------------------

def _format_expiry_ist(epoch_seconds: Optional[int]) -> str:
    if not isinstance(epoch_seconds, (int, float)):
        return "session-only (no expiry)"
    dt_ist = datetime.fromtimestamp(int(epoch_seconds), tz=IST)
    return dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")


def _format_remaining_ist(epoch_seconds: Optional[int]) -> str:
    if not isinstance(epoch_seconds, (int, float)):
        return "session-only"
    now_ist = datetime.now(IST)
    expiry_ist = datetime.fromtimestamp(int(epoch_seconds), tz=IST)
    delta = expiry_ist - now_ist
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "expired"
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _read_session_cookie_from_disk() -> Tuple[Optional[dict], bool]:
    """Return (cookie_dict, expired_flag).
    - cookie_dict: stored li_at cookie dict (may be returned even if expired)
    - expired_flag: True if stored cookie exists but is expired
    """
    data = None
    # Try encrypted first (silent on purpose)
    try:
        target_path = next((p for p in ENCRYPTED_COOKIE_FILES if os.path.exists(p)), None)
        if target_path:
            load_dotenv()
            key = os.getenv("DECRYPT_KEY")
            if key:
                with open(target_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                s = base64.b64decode(payload.get("s", ""))
                n = base64.b64decode(payload.get("n", ""))
                ct = base64.b64decode(payload.get("ct", ""))
                if s and n and ct:
                    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=s, iterations=200_000)
                    k = kdf.derive(key.encode("utf-8"))
                    data = json.loads(AESGCM(k).decrypt(n, ct, None).decode("utf-8"))
    except Exception:
        data = None

    if data is None:
        if not os.path.exists(COOKIE_FILE):
            print("[Cookie] No session cookie file found.")
            return None, False
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            print("[Cookie] Failed to read cookie file.")
            return None, False

    cookie = data.get(SESSION_COOKIE_NAME)
    if not isinstance(cookie, dict) or "value" not in cookie:
        print("[Cookie] Cookie file does not contain a valid session cookie.")
        return None, False

    expiry = cookie.get("expiry")
    if isinstance(expiry, (int, float)):
        now = int(time.time())
        if int(expiry) <= now:
            print(f"[Cookie] Found session cookie but it is expired (expired at {_format_expiry_ist(expiry)}).")
            return cookie, True

    print(f"[Cookie] Found active session cookie. Expires at {_format_expiry_ist(expiry)}. Remaining: {_format_remaining_ist(expiry)}.")
    return cookie, False


def _write_session_cookie_to_disk(cookie: dict) -> None:
    payload = {SESSION_COOKIE_NAME: cookie, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        # If an encrypted cookie exists, avoid creating plaintext
        if any(os.path.exists(p) for p in ENCRYPTED_COOKIE_FILES):
            print("[Cookie] Encrypted cookie present; not writing plaintext cookies.json.")
            return

        # Ask the user whether to create plaintext cookie when no encrypted cookie is present
        try:
            answer = input("No encrypted cookie found. Create plaintext cookies.json for session reuse? [y/N]: ")
        except Exception:
            answer = ""
        if str(answer).strip().lower() not in {"y", "yes"}:
            print("[Cookie] Skipped writing cookie to disk.")
            return

        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"[Cookie] Saved session cookie. Expires at {_format_expiry_ist(cookie.get('expiry'))}. Remaining: {_format_remaining_ist(cookie.get('expiry'))}.")
    except Exception:
        print("[Cookie] Failed to write cookie file (non-fatal).")


def _delete_cookie_file_if_exists() -> None:
    try:
        if os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
            print("[Cookie] Deleted expired session cookie file.")
    except Exception:
        pass
    # Also silently clean up any stray plaintext cookie if encrypted exists
    try:
        if any(os.path.exists(p) for p in ENCRYPTED_COOKIE_FILES) and os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
    except Exception:
        pass


def _handle_challenge_if_present(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """If redirected to LinkedIn challenge (CAPTCHA or approval), wait until user completes it."""
    try:
        current = driver.current_url
        if current.startswith(CHALLENGE_PREFIX) or current.startswith(CHALLENGE_V2_PREFIX):
            if current.startswith(CHALLENGE_V2_PREFIX):
                print("[Captcha] human approval required.")
            else:
                print("[Captcha] human verification required.")
            # Poll until the URL changes away from the challenge page
            last_notice = 0
            while True:
                time.sleep(2)
                try:
                    current = driver.current_url
                except Exception:
                    continue
                now = time.time()
                if now - last_notice > 15:
                    print("[Captcha] Waiting for completion...")
                    last_notice = now
                if not (current.startswith(CHALLENGE_PREFIX) or current.startswith(CHALLENGE_V2_PREFIX)):
                    break
            # After challenge, wait for main UI to load (best effort)
            try:
                wait.until(EC.presence_of_element_located((By.ID, "global-nav")))
            except Exception:
                pass
            print("[Captcha] Challenge completed. Continuing...")
    except Exception:
        # Non-fatal
        pass


def _try_cookie_login(driver: webdriver.Chrome, wait: WebDriverWait) -> bool:
    """Try to log in by reusing the stored session cookie. Return True if successful.
    No refresh or re-save is performed on success.
    """
    cookie, expired = _read_session_cookie_from_disk()

    if expired:
        _delete_cookie_file_if_exists()
        print("[Cookie] Will proceed with credential login to refresh session.")
        return False

    if not cookie:
        print("[Cookie] Cookie-based login not possible.")
        return False

    try:
        # Must be on the correct domain before adding cookies
        driver.get(BASE_URL)

        minimal_cookie = {
            "name": SESSION_COOKIE_NAME,
            "value": cookie["value"],
            "path": cookie.get("path", "/"),
        }
        domain = cookie.get("domain") or ".linkedin.com"
        minimal_cookie["domain"] = domain
        if isinstance(cookie.get("expiry"), (int, float)):
            minimal_cookie["expiry"] = int(cookie["expiry"])  # seconds since epoch

        try:
            driver.add_cookie(minimal_cookie)
        except Exception:
            minimal_cookie.pop("domain", None)
            driver.add_cookie(minimal_cookie)

        # Navigate to feed and check state
        driver.get(HOME_URL)
        _handle_challenge_if_present(driver, wait)

        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "global-nav")))
            print("[Cookie] Session cookie login succeeded.")
            return True
        except Exception:
            print("[Cookie] Session cookie login failed.")
            return False

    except Exception:
        print("[Cookie] Error applying session cookie.")
        return False


def _save_current_session_cookie(driver: webdriver.Chrome) -> None:
    try:
        cookies = driver.get_cookies()
        session = next((c for c in cookies if c.get("name") == SESSION_COOKIE_NAME), None)
        if session:
            to_store = {
                "name": session.get("name"),
                "value": session.get("value"),
                "domain": session.get("domain", ".linkedin.com"),
                "path": session.get("path", "/"),
            }
            if isinstance(session.get("expiry"), (int, float)):
                to_store["expiry"] = int(session["expiry"])  # seconds since epoch
            _write_session_cookie_to_disk(to_store)
        else:
            print("[Cookie] Session cookie not found after login (nothing to save).")
    except Exception:
        print("[Cookie] Failed to capture session cookie (non-fatal).")


def login_and_get_driver() -> webdriver.Chrome:
    """Log in to LinkedIn and return a live WebDriver session without closing it.

    Behavior:
    1) If a valid session cookie exists, reuse it to login without credentials.
    2) If absent or expired/invalid, log in with credentials and store a fresh session cookie.
    3) If a CAPTCHA challenge appears, wait for manual completion.
    """
    driver = _build_driver()
    wait = WebDriverWait(driver, 25)

    # 1) Try cookie-based login first
    if _try_cookie_login(driver, wait):
        return driver

    # 2) Fallback to credential-based login
    load_dotenv()
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")

    if not email or not password:
        try:
            driver.quit()
        except Exception:
            pass
        raise RuntimeError("Missing EMAIL or PASSWORD in .env and no valid session cookie available")

    try:
        driver.get(LOGIN_URL)

        email_el = wait.until(EC.visibility_of_element_located((By.XPATH, X_USERNAME)))
        email_el.clear()
        email_el.send_keys(email)

        password_el = wait.until(EC.visibility_of_element_located((By.XPATH, X_PASSWORD)))
        password_el.clear()
        password_el.send_keys(password)

        # Uncheck "Remember me" only if the checkbox is present
        try:
            cb_elems = driver.find_elements(By.XPATH, '//*[@id="organic-div"]/form/div[3]//input[@type="checkbox"]')
            if cb_elems:
                cb_input = cb_elems[0]
                if cb_input.is_selected():
                    label_elems = driver.find_elements(By.XPATH, X_REMEMBER_ME_LABEL)
                    target = label_elems[0] if label_elems else cb_input
                    target.click()
                    if cb_input.is_selected():
                        target.click()
        except Exception:
            pass

        # Click the Sign in button
        sign_in_btn = wait.until(EC.element_to_be_clickable((By.XPATH, X_SIGN_IN_BUTTON)))
        sign_in_btn.click()

        # If LinkedIn triggers a challenge, wait for user to solve it
        time.sleep(1)  # small grace period for redirect
        _handle_challenge_if_present(driver, wait)

        # Wait until global nav appears or we're redirected post-login
        try:
            wait.until(EC.presence_of_element_located((By.ID, "global-nav")))
        except Exception:
            time.sleep(3)

        # Save / refresh session cookie for next runs
        _save_current_session_cookie(driver)

        return driver

    except Exception as exc:
        try:
            driver.quit()
        except Exception:
            pass
        raise RuntimeError(f"Login failed: {exc}") from exc


def main() -> int:
    try:
        driver = login_and_get_driver()
        print("Logged in successfully. The browser will remain open. Press Ctrl+C to exit this script.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting script without closing the browser (detach=True).")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())