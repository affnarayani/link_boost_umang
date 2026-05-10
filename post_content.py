"""
post_content.py

Workflow:
1) Fetch content.json directly from GitHub Raw URL
2) Sanitize content.json: remove all asterisk (*) characters from each description
3) Clear the temp folder
4) Login to LinkedIn (reuses cookies.json via login.py)
5) Navigate to https://www.linkedin.com/feed/
6) Save page HTML to temp folder
7) Click "Start a post" (try provided XPaths and fallbacks)
8) Focus the composer input area (try provided XPath and robust fallbacks)
9) Type the first item's description as plain text paragraphs (no HTML, paragraphs separated by Enter)
10) Download the first item's image to temp and upload it to the post
11) Click Post and wait 15 seconds, then close the browser
"""

from __future__ import annotations

import html as html_unescape
import json
import os
import re
import time, random
import urllib.request
from pathlib import Path
from typing import List, Tuple

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import StaleElementReferenceException, ElementNotInteractableException

# Reuse the existing login flow and cookie handling
from login import login_and_get_driver

# -----------------------------
# Toggle: True = headless, False = headful
# -----------------------------
headless: bool = True
os.environ["HEADLESS"] = "true" if headless else "false"

REPO_ROOT = Path(__file__).resolve().parent
CONTENT_JSON = REPO_ROOT / "content.json"
TEMP_DIR = REPO_ROOT / "temp"
FEED_URL = "https://www.linkedin.com/feed/"
SAVED_FEED_HTML = TEMP_DIR / "feed.html"

# GitHub RAW source for content.json
GITHUB_RAW_URL = (
    "https://raw.githubusercontent.com/affnarayani/ninetynine_credits_legal_advice_app_content/refs/heads/main/content.json"
)

# Provided XPaths (primary attempts)
XPATH_START_POST_A = "/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[2]/div/div[2]/div/div/div[1]/div/div/div"
XPATH_START_POST_B = "div[aria-label='Start a post']"
CSS_COMPOSER_INPUT = '.ql-editor.ql-blank'
XPATH_POST_BUTTON = "/html/body/div[1]/div[3]//div/div[1]/div/div/div/div[2]/div/div[2]/div[2]/div[2]/div/div[2]/button/span"
SHADOW_HOST_SELECTOR = "#interop-outlet"
MAX_POST_CHARS = 2950


def fetch_and_write_raw_json(url: str, output_path: Path) -> None:
    """Fetch JSON directly from URL and write to disk."""
    with urllib.request.urlopen(url) as response:
        raw_data = response.read().decode('utf-8')
        parsed = json.loads(raw_data)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)


def clear_temp_folder(temp_dir: Path) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    for entry in temp_dir.iterdir():
        try:
            if entry.is_file() or entry.is_symlink():
                entry.unlink(missing_ok=True)
            elif entry.is_dir():
                for sub in entry.rglob("*"):
                    try:
                        if sub.is_file() or sub.is_symlink():
                            sub.unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    entry.rmdir()
                except Exception:
                    pass
        except Exception:
            pass


def load_and_sanitize_content(content_path: Path) -> Tuple[List[dict], dict]:
    with open(content_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    if not isinstance(items, list) or not items:
        raise RuntimeError("content.json must be a non-empty JSON array")
    for item in items:
        desc = item.get("description")
        if isinstance(desc, str):
            item["description"] = desc.replace("*", "")
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return items, items[0]


def html_to_plain_paragraphs(desc_html: str) -> List[str]:
    text = desc_html
    text = text.replace("</p>", "</p>\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = html_unescape.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    paras = [ln for ln in lines if ln]
    return paras


def save_feed_html(driver, out_path: Path) -> None:
    html = driver.page_source
    out_path.write_text(html, encoding="utf-8")


def save_snapshot(driver, out_path: Path) -> None:
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass


def js_click_first_matching_button(driver, texts: List[str]) -> bool:
    script = r"""
    const texts = arguments[0].map(t => t.toLowerCase());
    function visible(el){
      if(!el) return false;
      const style = window.getComputedStyle(el);
      if(style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }
    function collectCandidates(){
      const scopes = [
        document.querySelector('.artdeco-modal'),
        document.querySelector('.artdeco-modal__actionbar'),
        document
      ];
      const found = new Set();
      const results = [];
      for(const scope of scopes){
        if(!scope) continue;
        const btns = scope.querySelectorAll('button');
        for(const b of btns){
          const label = (b.innerText || b.textContent || '').trim().toLowerCase();
          const aria = (b.getAttribute('aria-label') || '').trim().toLowerCase();
          for(const t of texts){
            if(label === t || aria === t || label.includes(t) || aria.includes(t)){
              if(!found.has(b) && visible(b)){
                found.add(b);
                results.push(b);
              }
            }
          }
        }
      }
      return results;
    }
    const candidates = collectCandidates();
    if(candidates.length){
      candidates[0].click();
      return true;
    }
    return false;
    """
    try:
        return bool(driver.execute_script(script, texts))
    except Exception:
        return False


def try_click_start_post(driver, wait: WebDriverWait) -> None:
    candidates = [
        (By.XPATH, XPATH_START_POST_A),
        (By.CSS_SELECTOR, XPATH_START_POST_B),
        (By.XPATH, "//button[.//span[normalize-space(text())='Start a post']]"),
        (By.XPATH, "//span[normalize-space(.)='Start a post']/ancestor::button"),
        (By.XPATH, "//button[contains(@aria-label,'Start a post')]"),
    ]
    last_err = None
    for by, sel in candidates:
        try:
            el = wait.until(EC.element_to_be_clickable((by, sel)))
            try:
                btn = el.find_element(By.XPATH, "ancestor::button[1]")
                btn.click()
            except Exception:
                el.click()
            return
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not find 'Start a post' entry. Last error: {last_err}")


def focus_composer_input(wait_context: WebDriverWait):
    candidates = [
        (By.CSS_SELECTOR, CSS_COMPOSER_INPUT),
        (By.XPATH, "//div[@role='textbox' and @contenteditable='true']"),
        (By.XPATH, "//div[contains(@class,'ql-editor') and @contenteditable='true']"),
        (By.XPATH, "//div[@data-placeholder and @contenteditable='true']"),
        (By.XPATH, "//div[contains(@class,'share-box')]//div[@contenteditable='true']"),
    ]
    last_err = None
    for by, sel in candidates:
        try:
            el = wait_context.until(EC.visibility_of_element_located((by, sel)))
            el.click()
            return el
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not focus composer input. Last error: {last_err}")


def type_paragraphs_with_retries(shadow_wait: WebDriverWait, paragraphs: List[str]):
    content = "\n\n".join([p for p in paragraphs if p])
    attempts = 0
    while True:
        try:
            input_el = focus_composer_input(shadow_wait)
            time.sleep(6)
            if content:
                input_el.send_keys(content)
            time.sleep(6)
            break
        except (StaleElementReferenceException, ElementNotInteractableException):
            attempts += 1
            if attempts >= 3:
                raise
            time.sleep(0.5)


def download_image(url: str, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest_path.as_posix())
    return dest_path


def upload_image_in_composer(driver, wait: WebDriverWait, shadow_wait: WebDriverWait, image_path: Path) -> None:
    add_media_button_selector = "div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div:nth-child(3) > div:nth-child(2) > div:nth-child(1) > div:nth-child(2) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > section:nth-child(1) > div:nth-child(2) > ul:nth-child(1) > li:nth-child(2) > div:nth-child(1) > div:nth-child(1) > span:nth-child(1) > button:nth-child(1) > span:nth-child(1)"
    file_input_id = "media-editor-file-selector__file-input"
    uploaded = False

    try:
        btn = shadow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, add_media_button_selector)))
        btn.click()
        time.sleep(2.0)
    except Exception as e:
        raise RuntimeError(f"Could not click 'Add media' button in shadow DOM. Error: {e}")

    try:
        inp = shadow_wait.until(EC.presence_of_element_located((By.ID, file_input_id)))
        inp.send_keys(str(image_path.resolve()))
        uploaded = True
    except Exception as e:
        try:
            any_file_input = shadow_wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='file' and contains(@accept,'image')]")))
            any_file_input.send_keys(str(image_path.resolve()))
            uploaded = True
        except Exception:
            pass

    if not uploaded:
        raise RuntimeError("Could not locate a file input to upload image.")

    time.sleep(2.5)
    save_snapshot(driver, TEMP_DIR / "after_image_upload.html")

    next_button_selector = "div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div:nth-child(3) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(2) > div:nth-child(1) > button:nth-child(2)"
    try:
        next_btn = shadow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_button_selector)))
        next_btn.click()
        time.sleep(1.0)
    except Exception:
        js_click_first_matching_button(driver, ["Next", "Done", "Continue", "Apply"])
        time.sleep(1.0)

    time.sleep(6)


def click_post_button(driver, wait: WebDriverWait, shadow_wait: WebDriverWait) -> None:
    post_button_selector = "div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(1) > div:nth-child(3) > div:nth-child(2) > div:nth-child(1) > div:nth-child(1) > div:nth-child(2) > div:nth-child(5) > div:nth-child(1) > div:nth-child(2) > button:nth-child(1)"
    try:
        post_btn = shadow_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, post_button_selector)))
        post_btn.click()
        return
    except Exception as e:
        last_err = e

    candidates = [
        (By.XPATH, "//button[.//span[normalize-space(text())='Post']]"),
        (By.XPATH, "//span[normalize-space(.)='Post']/ancestor::button"),
    ]
    for by, sel in candidates:
        try:
            el = shadow_wait.until(EC.element_to_be_clickable((by, sel)))
            try:
                btn = el.find_element(By.XPATH, "ancestor::button[1]")
                btn.click()
            except Exception:
                el.click()
            return
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not find 'Post' button. Last error: {last_err}")


def main() -> int:
    try:
        from colorama import init as colorama_init, Fore, Style
        colorama_init(autoreset=True)
    except Exception:
        class Fore: GREEN = ""; YELLOW = ""; RED = ""; CYAN = ""; MAGENTA = ""; BLUE = ""
        class Style: BRIGHT = ""; RESET_ALL = ""

    def banner(msg: str) -> None: print(f"{Style.BRIGHT}{Fore.CYAN}=== {msg} ==={Style.RESET_ALL}")
    def step(n: int, msg: str) -> None: print(f"{Fore.BLUE}{Style.BRIGHT}[STEP {n}] {msg}{Style.RESET_ALL}")
    def info(msg: str) -> None: print(f"{Fore.CYAN}ℹ {msg}{Style.RESET_ALL}")
    def success(msg: str) -> None: print(f"{Fore.GREEN}✔ {msg}{Style.RESET_ALL}")
    def warn(msg: str) -> None: print(f"{Fore.YELLOW}⚠ {msg}{Style.RESET_ALL}")
    def error(msg: str) -> None: print(f"{Fore.RED}✖ {msg}{Style.RESET_ALL}")

    POSTED_JSON = REPO_ROOT / "posted_content.json"

    def load_posted() -> list[dict]:
        try:
            with open(POSTED_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception: return []

    def normalize_title(t: str | None) -> str: return (t or "").strip().lower()

    def is_already_posted(item: dict, posted_list: list[dict]) -> bool:
        t = normalize_title(item.get("title"))
        return any(normalize_title(p.get("title")) == t for p in posted_list)

    def prepend_posted(item: dict) -> None:
        posted = load_posted()
        item_to_record = item.copy()
        new_posted = [item_to_record] + [p for p in posted if normalize_title(p.get("title")) != normalize_title(item.get("title"))]
        with open(POSTED_JSON, "w", encoding="utf-8") as f:
            json.dump(new_posted, f, ensure_ascii=False, indent=2)

    banner("LinkedIn Auto Poster")

    # 0) Fetch latest content.json from GitHub Raw URL
    step(0, "Fetching latest content.json from GitHub (Raw)")
    try:
        fetch_and_write_raw_json(GITHUB_RAW_URL, CONTENT_JSON)
        success("Fetched and wrote content.json")
    except Exception as e:
        error(f"Failed to fetch content.json: {e}")
        return 1

    # 1) Sanitize content.json
    step(1, "Sanitizing content.json (removing asterisks)")
    items, _ = load_and_sanitize_content(CONTENT_JSON)
    success(f"Loaded {len(items)} items")

    posted_list = load_posted()
    first = None
    for idx, item_candidate in enumerate(items):
        if not is_already_posted(item_candidate, posted_list):
            desc_html = item_candidate.get("description") or ""
            paragraphs = html_to_plain_paragraphs(desc_html)
            char_count = len("\n\n".join(paragraphs))
            if char_count > MAX_POST_CHARS:
                warn(f"Item index {idx} exceeds char limit.")
                continue
            first = item_candidate
            info(f"Selected item: '{first.get('title','').strip()[:80]}'")
            break

    if not first:
        warn("No unposted items found. Exiting.")
        return 0

    # 2) Clear temp
    step(2, "Clearing temp folder")
    clear_temp_folder(TEMP_DIR)
    success("Temp cleared")

    # 3) Login
    step(3, "Logging in and preparing driver")
    driver = login_and_get_driver()
    wait = WebDriverWait(driver, 25)
    success("Driver ready")

    try:
        # 4) Feed
        step(4, "Navigating to LinkedIn feed")
        driver.get(FEED_URL)
        save_feed_html(driver, SAVED_FEED_HTML)

        # 6) Start Post
        step(6, "Opening composer")
        try_click_start_post(driver, wait)
        
        # 7) Shadow DOM Focus
        step(7, "Focusing composer input (Shadow DOM)")
        shadow_host = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SHADOW_HOST_SELECTOR)))
        shadow_root = shadow_host.shadow_root
        shadow_wait = WebDriverWait(shadow_root, 25)
        focus_composer_input(shadow_wait)

        # 8) Type Content
        step(8, "Typing post content")
        paragraphs = html_to_plain_paragraphs(first.get("description") or "")
        type_paragraphs_with_retries(shadow_wait, paragraphs)

        # 9) Image
        image_url = first.get("image")
        if isinstance(image_url, str) and image_url.strip():
            step(9, "Uploading image")
            local_image = TEMP_DIR / "post_image.jpg"
            download_image(image_url, local_image)
            upload_image_in_composer(driver, wait, shadow_wait, local_image)
            success("Image attached")

        # 10) Click Post
        step(10, "Clicking Post")
        click_post_button(driver, wait, shadow_wait)
        success("Post clicked")

        # 11) Record
        step(11, "Recording posted content")
        prepend_posted(first)

        # 12) Wait
        step(12, "Finalizing")
        time.sleep(15)
        success("Done")
        return 0
    finally:
        try: driver.quit()
        except: pass
        try: clear_temp_folder(TEMP_DIR)
        except: pass


if __name__ == "__main__":
    raise SystemExit(main())