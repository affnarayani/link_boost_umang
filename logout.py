# logout.py
# Logs out of LinkedIn using an existing session from login.py and cleans up state

import os
import time
import shutil
from pathlib import Path

# Toggle headless mode here: True = headless, False = headful
headless = True

# Apply headless preference for login.py (it reads HEADLESS env var)
os.environ["HEADLESS"] = "1" if headless else "0"

from login import login_and_get_driver, COOKIE_FILE, BASE_URL  # noqa: E402

LOGOUT_URL = "https://www.linkedin.com/m/logout/"
TEMP_DIR = Path(__file__).with_name("temp")


def clear_temp_folder(path: Path) -> None:
    """Delete all files/subfolders inside the temp directory. Re-create if missing."""
    try:
        if path.exists():
            # Remove all contents inside the folder without deleting the folder itself
            for entry in path.iterdir():
                try:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
                except Exception:
                    # Best-effort cleanup
                    pass
        else:
            path.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Non-fatal
        pass


def wait_for_logout(driver, timeout: int = 30) -> bool:
    """Wait until LinkedIn session is terminated (li_at cookie disappears or redirected to login).
    Returns True if logged out detected before timeout, else False.
    """
    start = time.time()

    def has_session_cookie() -> bool:
        try:
            cookies = driver.get_cookies()
            return any(c.get("name") == "li_at" for c in cookies)
        except Exception:
            return True  # treat errors as still logged in; we'll retry

    while time.time() - start < timeout:
        try:
            current = driver.current_url
            if "login" in current or "/checkpoint/" in current:
                return True
            # Refresh base URL to ensure cookie state reflects logout
            driver.get(BASE_URL)
            if not has_session_cookie():
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def delete_cookie_file() -> None:
    try:
        if os.path.exists(COOKIE_FILE):
            os.remove(COOKIE_FILE)
    except Exception:
        # Non-fatal
        pass


def main() -> int:
    # 1) Clear temp folder immediately
    clear_temp_folder(TEMP_DIR)

    # 2) Login using existing helper (reuses cookies.json when available)
    driver = None
    try:
        driver = login_and_get_driver()

        # 3) Navigate to logout URL
        driver.get(LOGOUT_URL)

        # 4) Wait until logout completes
        wait_for_logout(driver, timeout=45)

        # 5) Delete stored cookie file (if any)
        delete_cookie_file()

        return 0
    except Exception as exc:
        print(f"ERROR during logout: {exc}")
        return 1
    finally:
        # 6) Close the browser
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())