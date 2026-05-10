# scrape_connections.py
# Scrape LinkedIn people search results using an authenticated Selenium session.
# - Reuses login session from login.py when headless=False
# - Supports headless mode (headless=True) by performing login within this script
# - Reads search_url and scrape_pages from config.json (array of key-value objects, flexible for future keys)
# - Scrapes up to N pages and saves results into scraped_connections.json
# - Prints step-by-step logs and writes each profile immediately after scraping

from __future__ import annotations

import json
import os
import sys
import time
import shutil
from typing import Any, Dict, List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

# Import login utilities and constants
import login as login_mod


# ===== Developer toggles =====
# Set to True to run scraping in headless mode.
# Note: If True, this script will build its own headless driver and perform login here.
#       If False, it will reuse the session from login.py via login_and_get_driver().
headless: bool = True

# Default wait timeout
WAIT_SECONDS: int = 20

# File paths (relative to this script directory)
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
OUTPUT_PATH = BASE_DIR / "scraped_connections.json"
TEMP_DIR = BASE_DIR / "temp"

# Colored console helpers (aligned with get_info.py)
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except Exception:
    # Fallback if colorama is not available
    class _Fore:
        MAGENTA = ""
    class _Style:
        BRIGHT = ""
        RESET_ALL = ""
    Fore = _Fore()
    Style = _Style()


def log(msg: str) -> None:
    # Consistent [INFO] prefix and styling like get_info.py
    print(f"{Style.BRIGHT}{Fore.MAGENTA}[INFO]{Style.RESET_ALL} {msg}", flush=True)


def _build_driver(headless_flag: bool = False) -> webdriver.Chrome:
    """Create a Chrome WebDriver configured per requirements.
    - Headless toggle via headless_flag
    - Maximized window
    - Eager page load for speed
    """
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])  # Reduce console noise on Windows
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_experimental_option("detach", True)
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")

    if headless_flag:
        # Use new headless if supported
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.maximize_window()
    except Exception:
        pass

    return driver


def _read_config() -> Dict[str, Any]:
    """Read config.json which is an array of objects and merge into a single dict.
    Later keys override earlier ones if duplicated.
    """
    log(f"Reading config from: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    result: Dict[str, Any] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                result.update(item)
    elif isinstance(data, dict):
        result.update(data)
    else:
        raise ValueError("config.json must be a list or dict of key/value pairs")
    log(f"Config loaded: keys={list(result.keys())}")
    return result


def _ensure_logged_in_driver() -> webdriver.Chrome:
    """Return a logged-in Selenium driver based on the headless toggle.
    - headless=False: reuse login_mod.login_and_get_driver()
    - headless=True: build local headless driver and login using login_mod constants
    """
    if not headless:
        log("Reusing login session via login.py (headless=False)...")
        return login_mod.login_and_get_driver()

    # Headless flow: try cookie-based login first, then fallback to credentials
    log("Building headless driver (headless=True)...")
    driver = _build_driver(headless_flag=True)
    wait = WebDriverWait(driver, WAIT_SECONDS)

    # Attempt to reuse session via cookies.json
    try:
        if hasattr(login_mod, "_try_cookie_login") and login_mod._try_cookie_login(driver, wait):
            log("Reused session via cookies.json (headless).")
            return driver
    except Exception:
        # Non-fatal; continue to credential login
        pass

    # Fallback: credential login
    driver.get(login_mod.LOGIN_URL)

    try:
        from dotenv import load_dotenv
        load_dotenv()
        email = os.getenv("EMAIL")
        password = os.getenv("PASSWORD")
        if not email or not password:
            raise RuntimeError("Missing EMAIL or PASSWORD in .env for headless login and no valid session cookie")

        log("Filling login form...")
        email_el = wait.until(EC.visibility_of_element_located((By.XPATH, login_mod.X_USERNAME)))
        email_el.clear()
        email_el.send_keys(email)

        password_el = wait.until(EC.visibility_of_element_located((By.XPATH, login_mod.X_PASSWORD)))
        password_el.clear()
        password_el.send_keys(password)

        log("Submitting login form...")
        # Try to uncheck Remember Me if selected (best-effort)
        try:
            cb_input = driver.find_element(By.XPATH, '//*[@id="organic-div"]/form/div[3]//input[@type="checkbox"]')
            if cb_input.is_selected():
                label = driver.find_element(By.XPATH, login_mod.X_REMEMBER_ME_LABEL)
                label.click()
        except Exception:
            try:
                label = driver.find_element(By.XPATH, login_mod.X_REMEMBER_ME_LABEL)
                label.click()
            except Exception:
                pass

        sign_in_btn = wait.until(EC.element_to_be_clickable((By.XPATH, login_mod.X_SIGN_IN_BUTTON)))
        sign_in_btn.click()

        try:
            wait.until(EC.presence_of_element_located((By.ID, "global-nav")))
        except Exception:
            time.sleep(2)

        # Refresh and save session cookie for future runs
        try:
            if hasattr(login_mod, "_save_current_session_cookie"):
                login_mod._save_current_session_cookie(driver)
        except Exception:
            pass

        log("Login successful (headless).")
        return driver
    except Exception:
        try:
            driver.quit()
        except Exception:
            pass
        raise


def _xpath_candidates_for_row(idx: int) -> Dict[str, List[str]]:
    """Return possible XPath candidates for fields within a result row index.
    Based on provided row 1 and row 2 patterns. We'll try variants A and B.
    """
    # Variant A (like row 1 example)
    base_a = f"/html/body/div[6]/div[3]/div[2]/div/div[1]/main/div/div/div[1]/div/ul/li[{idx}]/div/div/div/div[2]"
    # Variant B (like row 2 example - note extra [1] levels)
    base_b = f"/html/body/div[6]/div[3]/div[2]/div/div[1]/main/div/div/div[1]/div/ul/li[{idx}]/div/div/div/div[2]/div[1]"

    name_candidates = [
        f"{base_a}/div/div[1]/div/span[1]/span/a/span/span[1]",
        f"{base_b}/div[1]/div/span[1]/span/a/span/span[1]",
    ]
    tag_candidates = [
        f"{base_a}/div/div[2]",
        f"{base_b}/div[2]",
    ]
    location_candidates = [
        f"{base_a}/div/div[3]",
        f"{base_b}/div[3]",
    ]
    # Verified button candidate (provided for row 1). If not found, it's False.
    verified_candidates = [
        f"{base_a}/div/div[1]/div/span[1]/span/span/div/span[1]/button",
    ]
    return {
        "name": name_candidates,
        "tag": tag_candidates,
        "location": location_candidates,
        "verified": verified_candidates,
    }


def _text_or_none(driver: webdriver.Chrome, wait: WebDriverWait, candidates: List[str]) -> Optional[str]:
    for xp in candidates:
        try:
            el = wait.until(EC.visibility_of_element_located((By.XPATH, xp)))
            text = (el.text or "").strip()
            if text:
                return text
            # Some elements may have nested spans, try get_attribute as fallback
            txt = (el.get_attribute("innerText") or "").strip()
            if txt:
                return txt
        except Exception:
            continue
    return None


def _exists(driver: webdriver.Chrome, candidates: List[str]) -> bool:
    for xp in candidates:
        try:
            driver.find_element(By.XPATH, xp)
            return True
        except Exception:
            continue
    return False


def _save_page_html(driver: webdriver.Chrome, page: int, prefix: str = "people_search") -> Optional[Path]:
    """Save current page HTML under temp folder for offline inspection.
    Returns the saved Path or None on failure.
    """
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        filepath = TEMP_DIR / f"{prefix}_page_{page}.html"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log(f"Saved page HTML for analysis: {filepath}")
        return filepath
    except Exception as e:
        log(f"Warning: could not save page HTML: {e}")
        return None


def _delete_file_silent(path: Path) -> None:
    """Delete a file if it exists; ignore errors."""
    try:
        if path and path.exists():
            path.unlink()
    except Exception:
        pass


def _find_result_items(driver: webdriver.Chrome) -> List[Any]:
    """Try multiple CSS selectors to find people search result list items.
    Prefer stable attributes over classes (which can be obfuscated).
    Returns a list of container elements per result.
    """
    css_candidates = [
        'div[data-view-name="search-entity-result-universal-template"]',  # most stable in observed DOM
        'ul.reusable-search__entity-result-list > li',
        'ul.reusable-search__entity-result-list li',
        'ul.search-results__list > li',
        'main ul > li.reusable-search__result-container',
    ]
    for css in css_candidates:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, css)
            if els:
                return els
        except Exception:
            continue
    return []


essential_text_tags = 'p,span,strong,h1,h2,h3,div'

def _extract_from_result_item(item: Any) -> Dict[str, Any]:
    """Extract name, tag, location, verified, connect, profile_url from a result item using robust selectors.
    Item can be either the <li> or the inner container with data-view-name.
    """
    def _get_text(css_list: List[str]) -> Optional[str]:
        for css in css_list:
            try:
                el = item.find_element(By.CSS_SELECTOR, css)
                txt = (el.get_attribute("innerText") or el.text or "").strip()
                if txt:
                    return " ".join(txt.split())
            except Exception:
                continue
        return None

    def _exists_css(css_list: List[str]) -> bool:
        for css in css_list:
            try:
                item.find_element(By.CSS_SELECTOR, css)
                return True
            except Exception:
                continue
        return False

    def _get_href(css_list: List[str]) -> Optional[str]:
        for css in css_list:
            try:
                a = item.find_element(By.CSS_SELECTOR, css)
                href = a.get_attribute("href")
                if href:
                    return href
            except Exception:
                continue
        return None

    # Name and profile URL: use stable app-aware link and aria-hidden span
    name = _get_text([
        'a[data-test-app-aware-link][href*="/in/"] span[aria-hidden="true"]',
        'a[data-test-app-aware-link][href*="/in/"] span span',
    ])
    if not name:
        # Fallback: try the link's innerText
        try:
            a = item.find_element(By.CSS_SELECTOR, 'a[data-test-app-aware-link][href*="/in/"]')
            raw = (a.get_attribute("innerText") or a.text or "").strip()
            if raw:
                name = " ".join(raw.split())
        except Exception:
            name = None

    profile_url = _get_href([
        'a[data-test-app-aware-link][href*="/in/"]',
    ])

    # Tag/headline and location: prefer typography utility classes when present
    tag = _get_text([
        'div.t-14.t-black.t-normal',  # headline often uses these utility classes
    ]) or ""

    # Location tends to be another t-14 line without t-black
    location = _get_text([
        'div.t-14.t-normal',
    ]) or ""

    # If heuristics failed, try scanning nearby simple text nodes for first two lines after name link
    if (not tag or not location):
        try:
            # Find the container holding textual lines (closest ancestor of the name link)
            a = item.find_element(By.CSS_SELECTOR, 'a[data-test-app-aware-link][href*="/in/"]')
            container = a.find_element(By.XPATH, './ancestor::*[contains(@class, "t-16")][1]/ancestor::*[1]')
        except Exception:
            container = item
        try:
            # Collect candidate texts in reading order
            nodes = container.find_elements(By.CSS_SELECTOR, essential_text_tags)
            texts: List[str] = []
            for n in nodes:
                try:
                    t = (n.get_attribute("innerText") or n.text or "").strip()
                    if not t:
                        continue
                    t = " ".join(t.split())
                    # Filter obvious badges and labels
                    if t.startswith("•") or "degree connection" in t.lower() or t.lower().startswith("view "):
                        continue
                    texts.append(t)
                except Exception:
                    continue
            # Derive tag and location from distinct lines not equal to name
            for t in texts:
                if not tag and t != name:
                    tag = t
                    continue
                if tag and not location and t not in (name, tag):
                    location = t
                    break
        except Exception:
            pass

    verified = _exists_css([
        'button[aria-label*="Verified" i]',
        'svg[aria-label*="Verified" i]',
    ])

    # Connect: any button within item with text 'Connect'
    connect = False
    try:
        btns = item.find_elements(By.CSS_SELECTOR, 'button')
        for b in btns:
            txt = (b.get_attribute('innerText') or b.text or '').strip().lower()
            if txt == 'connect':
                connect = True
                break
    except Exception:
        connect = False

    return {
        "name": name,
        "tag": tag,
        "location": location,
        "verified": bool(verified),
        "connect": bool(connect),
        "profile_url": profile_url,
    }


def _build_page_url(base_url: str, page_num: int) -> str:
    """Return base_url with the page query param set to page_num.
    If page is already present, it gets overridden; otherwise it's added.
    """
    parsed = urlparse(base_url)
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if page_num > 1:
        q["page"] = str(page_num)
    else:
        # For page 1, remove page parameter if present for cleanliness
        q.pop("page", None)
    new_query = urlencode(q, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))


def _load_existing_results() -> List[Dict[str, Any]]:
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        # Handle truncated or partially written files: attempt to recover by reading lines
        try:
            with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.endswith(","):
                content = content[:-1]
            # Fallback to empty list if still invalid
            json.loads(content)
        except Exception:
            return []
    except Exception:
        pass
    return []


def _write_results(results: List[Dict[str, Any]]) -> None:
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def _append_one_immediately(
    profile: Dict[str, Any],
    results: List[Dict[str, Any]],
    seen_keys: set[Tuple[Any, Any, Any]],
) -> bool:
    """Append a single profile and immediately persist to disk.
    Deduplicate by (page, index, name). Returns True if appended, False if duplicate.
    """
    key = (profile.get("page"), profile.get("index"), profile.get("name"))
    if key in seen_keys:
        log(f"  - Duplicate detected, skipping save: {key}")
        return False
    results.append(profile)
    seen_keys.add(key)
    _write_results(results)
    log(f"  - Saved to {OUTPUT_PATH}. Total records: {len(results)}")
    return True


def scrape() -> None:
    log("Starting scrape...")
    config = _read_config()
    search_url = config.get("search_url")
    scrape_pages = int(config.get("scrape_pages", 1))

    if not search_url:
        raise RuntimeError("config.json missing 'search_url'")

    log("Ensuring logged-in driver...")
    driver = None
    try:
        driver = _ensure_logged_in_driver()
        wait = WebDriverWait(driver, WAIT_SECONDS)

        existing = _load_existing_results()
        seen = {(r.get("page"), r.get("index"), r.get("name")) for r in existing}
        log(f"Loaded existing results: {len(existing)} entries")

        # Open initial search URL (page 1)
        first_page_url = _build_page_url(search_url, 1)
        log(f"Opening search URL (page 1): {first_page_url}")
        driver.get(first_page_url)
        time.sleep(2)

        saved_count = 0

        # Scrape pages 1..scrape_pages
        for page in range(1, scrape_pages + 1):
            log(f"Scraping page {page}/{scrape_pages}...")
            page_url = _build_page_url(search_url, page)
            if page == 1:
                # Already opened first page above, but ensure URL normalization
                if driver.current_url != page_url:
                    driver.get(page_url)
                    time.sleep(2)
            else:
                log(f"Navigating to page {page}: {page_url}")
                driver.get(page_url)
                time.sleep(2)

            # Save HTML for this page for offline analysis/debugging
            html_path = _save_page_html(driver, page)
            processed_in_page = 0

            # First, try robust CSS-based parsing of result items
            items = _find_result_items(driver)
            if items:
                log(f"Found {len(items)} result items via CSS. Extracting...")
                for idx, item in enumerate(items, start=1):
                    data = _extract_from_result_item(item)
                    name = data.get("name")
                    if not name:
                        log("  - Name not found in item. Skipping.")
                        continue

                    profile = {
                        "page": page,
                        "index": idx,
                        "name": name,
                        "tag": data.get("tag", ""),
                        "location": data.get("location", ""),
                        "verified": bool(data.get("verified", False)),
                        "connect": bool(data.get("connect", False)),
                        "profile_url": data.get("profile_url"),
                        "sent_request": False,
                    }

                    log(f"  - Extracted: name='{name}', verified={bool(profile['verified'])}")
                    if _append_one_immediately(profile, existing, seen):
                        saved_count += 1
                        processed_in_page += 1

            # Fallback to legacy XPath-based approach if CSS found nothing
            if processed_in_page == 0:
                log("CSS-based parsing yielded no records. Falling back to XPath candidates...")
                # Determine index range per requirements:
                # - Page 1: indices up to 11 due to an absent entry
                # - Other pages: 1..10
                max_idx = 11 if page == 1 else 10

                for idx in range(1, max_idx + 1):
                    log(f"- Row {idx}: extracting fields...")
                    cands = _xpath_candidates_for_row(idx)

                    # Try to detect if the row exists at all by checking name presence
                    name = _text_or_none(driver, wait, cands["name"])  # None if row missing
                    if not name:
                        log("  - Name not found. Possibly missing slot. Skipping.")
                        continue

                    tag = _text_or_none(driver, wait, cands["tag"]) or ""
                    location = _text_or_none(driver, wait, cands["location"]) or ""
                    verified = _exists(driver, cands["verified"])  # True if button present for this row structure

                    # Check "Connect" button text at the specified XPath for this row index
                    connect_xpath = f"/html/body/div[6]/div[3]/div[2]/div/div[1]/main/div/div/div[1]/div/ul/li[{idx}]/div/div/div/div[3]/div/button/span"
                    connect = False
                    try:
                        connect_el = driver.find_element(By.XPATH, connect_xpath)
                        connect_text = (connect_el.text or connect_el.get_attribute("innerText") or "").strip()
                        # Mark True only when the text equals "Connect" (case-insensitive)
                        connect = (connect_text.lower() == "connect")
                    except Exception:
                        connect = False

                    # Try to capture profile URL if anchor is present
                    profile_url = None
                    for xp in cands["name"]:
                        try:
                            a_el = driver.find_element(By.XPATH, xp + "/ancestor::a[1]")
                            href = a_el.get_attribute("href")
                            if href:
                                profile_url = href
                                break
                        except Exception:
                            try:
                                span_el = driver.find_element(By.XPATH, xp)
                                a_el2 = span_el.find_element(By.XPATH, "ancestor::span[1]/ancestor::a[1]")
                                href2 = a_el2.get_attribute("href")
                                if href2:
                                    profile_url = href2
                                    break
                            except Exception:
                                continue

                    profile = {
                        "page": page,
                        "index": idx,
                        "name": name,
                        "tag": tag,
                        "location": location,
                        "verified": bool(verified),
                        "connect": bool(connect),
                        "profile_url": profile_url,
                        "sent_request": False,
                    }

                    log(f"  - Extracted: name='{name}', verified={bool(verified)}")
                    if _append_one_immediately(profile, existing, seen):
                        saved_count += 1
                        processed_in_page += 1

            # Remove saved HTML for this page on success; keep it if we captured nothing for debugging
            if processed_in_page > 0 and html_path:
                _delete_file_silent(html_path)
            elif processed_in_page == 0:
                log("No profiles extracted on this page. Keeping saved HTML in temp for manual inspection.")

            # Wait 30–60 seconds between pages to be gentle
            if page < scrape_pages:
                import random
                wait_secs = random.randint(30, 60)
                log(f"Waiting {wait_secs} seconds before next page...")
                time.sleep(wait_secs)

        log(f"Scraping complete. New profiles saved: {saved_count}. Total records now: {len(existing)}")
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}Saved JSON to: {OUTPUT_PATH}{Style.RESET_ALL}", flush=True)
    finally:
        try:
            if driver:
                driver.quit()
                log("Closed browser.")
        except Exception:
            pass


def main() -> int:
    # Clear temp folder at startup
    try:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        log(f"Cleared temp folder: {TEMP_DIR}")
    except Exception as e:
        log(f"Warning: could not clear temp folder: {e}")

    # Clear output file before performing scraping
    try:
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            f.write("[]")
        log(f"Cleared output file: {OUTPUT_PATH}")
    except Exception as e:
        log(f"Warning: could not clear output file: {e}")

    try:
        scrape()
        return 0
    except KeyboardInterrupt:
        log("Interrupted.")
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())