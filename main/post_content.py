"""
post_content.py

Workflow:
1) Sanitize content.json: remove all asterisk (*) characters from each description
2) Clear the temp folder
3) Login to LinkedIn (reuses cookies.json via login.py)
4) Navigate to https://www.linkedin.com/feed/
5) Save page HTML to temp folder
6) Click "Start a post" (try provided XPaths and fallbacks)
7) Focus the composer input area (try provided XPath and robust fallbacks)
8) Type the first item's description as plain text paragraphs (no HTML, paragraphs separated by Enter)
9) Download the first item's image to temp and upload it to the post
10) Click Post and wait 15 seconds, then close the browser

Notes:
- Uses Selenium with Chrome; the HEADLESS behavior can be controlled via HEADLESS env var (same as login.py)
- Relies on login.login_and_get_driver()
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

# Provided XPaths (primary attempts)
XPATH_START_POST_A = "/html/body/div[5]/div[3]/div/div/div[2]/div/div/main/div[1]/div[2]/div[2]/button/span/span"
XPATH_START_POST_B = "/html/body/div[6]/div[3]/div/div/div[2]/div/div/main/div[1]/div[2]/div[2]/button/span/span"
# Provided composer input XPath
XPATH_COMPOSER_INPUT = "/html/body/div[4]/div/div/div/div[2]/div/div[2]/div[1]/div/div/div/div/div/div/div[1]/p"
# Provided Post button XPath (updated per request)
XPATH_POST_BUTTON = "/html/body/div[4]/div/div/div/div[2]/div/div/div[2]/div[3]/div/div[2]/button/span"

# GitHub source for content.json and the target textarea XPath
GITHUB_BLOB_URL = (
    "https://github.com/affnarayani/ninetynine_credits_legal_advice_app_content/blob/main/content.json"
)
GITHUB_TARGET_XPATH = '//*[@id="read-only-cursor-text-area"]'

# Maximum characters allowed for a LinkedIn post (including spaces)
MAX_POST_CHARS = 2950


def build_driver(is_headless: bool) -> webdriver.Chrome:
    """Create and return a configured Chrome WebDriver instance (for GitHub fetch)."""
    chrome_options = Options()
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


def fetch_json_text(driver: webdriver.Chrome, url: str, xpath: str, timeout: int = 25) -> str:
    """Navigate to the URL and fetch text from the provided XPath (textarea value preferred)."""
    driver.get(url)
    wait = WebDriverWait(driver, timeout)
    element = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    text = element.get_attribute("value") or element.text or ""
    if not text.strip():
        raise RuntimeError("Fetched content is empty from the specified XPath.")
    return text


def write_content_json(raw_text: str, output_path: Path | str) -> None:
    """Write the JSON content to disk, validating and pretty-printing if possible (overwrite)."""
    path = Path(output_path)
    try:
        parsed = json.loads(raw_text)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_text)


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
    """Load content.json, remove all asterisks from description fields.
    Returns (items, first_item).
    """
    with open(content_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list) or not items:
        raise RuntimeError("content.json must be a non-empty JSON array")

    for item in items:
        desc = item.get("description")
        if isinstance(desc, str):
            item["description"] = desc.replace("*", "")

    # Persist sanitized content back to disk
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    return items, items[0]


def html_to_plain_paragraphs(desc_html: str) -> List[str]:
    """Convert a small HTML snippet (with <p> tags) into plain-text paragraphs.
    - Remove any HTML tags
    - Unescape entities
    - Split paragraphs by blank lines/newlines
    - Trim and drop empties
    """
    # Ensure closing p tags create newlines for splitting
    text = desc_html
    text = text.replace("</p>", "</p>\n")
    # Strip all tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape entities (&nbsp;, &amp;, etc.)
    text = html_unescape.unescape(text)
    # Normalize line breaks
    lines = [ln.strip() for ln in text.splitlines()]
    paras = [ln for ln in lines if ln]
    return paras


def save_feed_html(driver, out_path: Path) -> None:
    html = driver.page_source
    out_path.write_text(html, encoding="utf-8")


def save_snapshot(driver, out_path: Path) -> None:
    """Save current page_source to a given path for debugging."""
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass


def js_click_first_matching_button(driver, texts: List[str]) -> bool:
    """Use JS to find and click the first visible button in any modal/footer whose text matches any of texts.
    Returns True if clicked.
    """
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
    """Try multiple strategies to click the 'Start a post' entry point."""
    candidates = [
        (By.XPATH, XPATH_START_POST_A),
        (By.XPATH, XPATH_START_POST_B),
        # Fallback: text-based button/span
        (By.XPATH, "//button[.//span[normalize-space(text())='Start a post']]"),
        (By.XPATH, "//span[normalize-space(.)='Start a post']/ancestor::button"),
        (By.XPATH, "//button[contains(@aria-label,'Start a post')]"),
    ]
    last_err = None
    for by, sel in candidates:
        try:
            el = wait.until(EC.element_to_be_clickable((by, sel)))
            # If target is the inner span, click the nearest button ancestor if present
            try:
                btn = el.find_element(By.XPATH, "ancestor::button[1]")
                btn.click()
            except Exception:
                el.click()
            return
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not find 'Start a post' entry. Last error: {last_err}")


def focus_composer_input(driver, wait: WebDriverWait):
    """Focus the contenteditable composer input area using several strategies."""
    candidates = [
        (By.XPATH, XPATH_COMPOSER_INPUT),
        # Robust fallbacks commonly found in LinkedIn composer
        (By.XPATH, "//div[@role='textbox' and @contenteditable='true']"),
        (By.XPATH, "//div[contains(@class,'ql-editor') and @contenteditable='true']"),
        (By.XPATH, "//div[@data-placeholder and @contenteditable='true']"),
        (By.XPATH, "//div[contains(@class,'share-box')]//div[@contenteditable='true']"),
    ]

    last_err = None
    for by, sel in candidates:
        try:
            el = wait.until(EC.visibility_of_element_located((by, sel)))
            el.click()
            return el
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not focus composer input. Last error: {last_err}")


def type_paragraphs_with_retries(driver, wait: WebDriverWait, paragraphs: List[str]):
    """Enter the entire content in one send_keys call, waiting 6 seconds before and after.
    Retries if the composer element becomes stale by re-focusing it.
    """
    # Join paragraphs with double newlines to separate them clearly
    content = "\n\n".join([p for p in paragraphs if p])

    attempts = 0
    while True:
        try:
            # Re-focus before sending to get a fresh reference
            input_el = focus_composer_input(driver, wait)
            # Wait 6 seconds before entering text
            time.sleep(6)
            if content:
                input_el.send_keys(content)
            # Wait 6 seconds after entering text
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


def upload_image_in_composer(driver, wait: WebDriverWait, image_path: Path) -> None:
    """Attach an image and handle LinkedIn's media modal (Next/Done flows)."""
    # A few strategies to reveal/locate the file input
    # 1) Click a visible 'Add a photo' / 'Media' button first
    media_buttons = [
        (By.XPATH, "//button[.//span[contains(normalize-space(.), 'Add a photo')]]"),
        (By.XPATH, "//button[contains(@aria-label,'Add a photo')]"),
        (By.XPATH, "//button[contains(@aria-label,'Add media')]"),
        (By.XPATH, "//button[.//span[contains(normalize-space(.), 'Media')]]"),
        (By.XPATH, "//button[.//span[contains(normalize-space(.), 'Photo')]]"),
    ]
    for by, sel in media_buttons:
        try:
            btn = driver.find_element(by, sel)
            if btn.is_displayed():
                btn.click()
                time.sleep(1.0)
                break
        except Exception:
            pass

    # 2) Try common selectors for file inputs
    file_inputs = [
        (By.XPATH, "//input[@type='file' and contains(@accept,'image')]")
    ]

    uploaded = False
    for by, sel in file_inputs:
        try:
            inp = wait.until(EC.presence_of_element_located((by, sel)))
            inp.send_keys(str(image_path.resolve()))
            uploaded = True
            break
        except Exception:
            pass

    if not uploaded:
        # 3) Last resort: any file input in the composer modal
        try:
            any_file_input = driver.find_element(By.XPATH, "//div[contains(@class,'artdeco-modal')]//input[@type='file']")
            any_file_input.send_keys(str(image_path.resolve()))
            uploaded = True
        except Exception:
            pass

    if not uploaded:
        raise RuntimeError("Could not locate a file input to upload image.")

    # Give time for LinkedIn to show image preview + modal controls
    time.sleep(2.5)

    # Save a snapshot for debugging after upload
    save_snapshot(driver, TEMP_DIR / "after_image_upload.html")

    # Handle possible intermediate modal: click Next/Done/Continue if present via JS
    js_click_first_matching_button(driver, ["Next", "Done", "Continue", "Apply"]) 
    time.sleep(1.0)

    # Additional wait requested after media upload
    time.sleep(6)


def click_post_button(driver, wait: WebDriverWait) -> None:
    """Click the Post button directly using XPath or robust fallbacks."""
    candidates = [
        (By.XPATH, XPATH_POST_BUTTON),
        (By.XPATH, "//button[.//span[normalize-space(text())='Post']]"),
        (By.XPATH, "//span[normalize-space(.)='Post']/ancestor::button"),
    ]
    last_err = None
    for by, sel in candidates:
        try:
            el = wait.until(EC.element_to_be_clickable((by, sel)))
            # If the element is a span, click the nearest button ancestor
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
    # Initialize colorful, structured console output
    try:
        from colorama import init as colorama_init, Fore, Style
        colorama_init(autoreset=True)
    except Exception:
        class Fore:
            GREEN = ""; YELLOW = ""; RED = ""; CYAN = ""; MAGENTA = ""; BLUE = ""
        class Style:
            BRIGHT = ""; RESET_ALL = ""

    def banner(msg: str) -> None:
        print(f"{Style.BRIGHT}{Fore.CYAN}=== {msg} ==={Style.RESET_ALL}")

    def step(n: int, msg: str) -> None:
        print(f"{Fore.BLUE}{Style.BRIGHT}[STEP {n}] {msg}{Style.RESET_ALL}")

    def info(msg: str) -> None:
        print(f"{Fore.CYAN}ℹ {msg}{Style.RESET_ALL}")

    def success(msg: str) -> None:
        print(f"{Fore.GREEN}✔ {msg}{Style.RESET_ALL}")

    def warn(msg: str) -> None:
        print(f"{Fore.YELLOW}⚠ {msg}{Style.RESET_ALL}")

    def error(msg: str) -> None:
        print(f"{Fore.RED}✖ {msg}{Style.RESET_ALL}")

    # posted_content.json helpers
    POSTED_JSON = REPO_ROOT / "posted_content.json"

    def load_posted() -> list[dict]:
        try:
            with open(POSTED_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def normalize_title(t: str | None) -> str:
        return (t or "").strip().lower()

    def is_already_posted(item: dict, posted_list: list[dict]) -> bool:
        t = normalize_title(item.get("title"))
        for p in posted_list:
            if normalize_title(p.get("title")) == t:
                return True
        return False

    def prepend_posted(item: dict) -> None:
        posted = load_posted()
        # Remove any existing entries with same title
        new_posted = [item] + [p for p in posted if normalize_title(p.get("title")) != normalize_title(item.get("title"))]
        with open(POSTED_JSON, "w", encoding="utf-8") as f:
            json.dump(new_posted, f, ensure_ascii=False, indent=2)

    def select_first_unposted(items: list[dict], posted_list: list[dict]) -> tuple[int, dict] | None:
        for idx, it in enumerate(items):
            if not is_already_posted(it, posted_list):
                return idx, it
        return None

    banner("LinkedIn Auto Poster")

    # 0) Fetch latest content.json from GitHub and overwrite local
    step(0, "Fetching latest content.json from GitHub")
    gh_driver = build_driver(headless)
    try:
        raw = fetch_json_text(gh_driver, GITHUB_BLOB_URL, GITHUB_TARGET_XPATH)
        write_content_json(raw, CONTENT_JSON)
        success("Fetched and wrote content.json")
    finally:
        try:
            gh_driver.quit()
        except Exception:
            pass

    # 1) Sanitize content.json
    step(1, "Sanitizing content.json (removing asterisks)")
    items, _first_unused = load_and_sanitize_content(CONTENT_JSON)
    success(f"Loaded {len(items)} items")

    # Choose first item that is not already posted and is within character limit
    posted_list = load_posted()
    first_index = -1
    first = None
    for idx, item_candidate in enumerate(items):
        if not is_already_posted(item_candidate, posted_list):
            desc_html = item_candidate.get("description") or ""
            plain_text_paragraphs = html_to_plain_paragraphs(desc_html)
            char_count = len("\n\n".join(plain_text_paragraphs)) # Count characters including spaces and newlines

            if char_count > MAX_POST_CHARS:
                warn(f"Item '{item_candidate.get('title','').strip()[:80]}' (index {idx}) skipped due to exceeding {MAX_POST_CHARS} characters ({char_count} chars).")
                continue # Try next item
            else:
                first_index = idx
                first = item_candidate
                info(f"Selected item index {first_index} → '{first.get('title','').strip()[:80]}' ({char_count} chars)")
                break # Found a suitable item

    if not first:
        warn("No unposted items found within the character limit. Exiting.")
        return 0

    # 2) Clear temp folder
    step(2, "Clearing temp folder")
    clear_temp_folder(TEMP_DIR)
    success("Temp cleared")

    # 3) Login (reuses session cookie if available)
    step(3, "Logging in and preparing driver")
    driver = login_and_get_driver()
    wait = WebDriverWait(driver, 25)
    success("Driver ready")

    try:
        # 4) Navigate to feed
        step(4, "Navigating to LinkedIn feed")
        driver.get(FEED_URL)
        success("Feed loaded (page source captured next)")

        # 5) Save feed HTML
        save_feed_html(driver, SAVED_FEED_HTML)

        # 6) Click "Start a post"
        step(6, "Opening composer (Start a post)")
        try_click_start_post(driver, wait)
        save_snapshot(driver, TEMP_DIR / "after_start_post.html")
        success("Composer opened")

        # 7) Focus the composer input (initial focus; subsequent sends will re-focus as needed)
        step(7, "Focusing composer input")
        focus_composer_input(driver, wait)
        success("Composer focused")

        # 8) Prepare text: convert first item's description to plain paragraphs
        step(8, "Typing post content")
        desc_html = first.get("description") or ""
        paragraphs = html_to_plain_paragraphs(desc_html)
        type_paragraphs_with_retries(driver, wait, paragraphs)
        success("Content typed")

        # 9) Download and upload the image (if present)
        image_url = first.get("image")
        if isinstance(image_url, str) and image_url.strip():
            step(9, "Uploading image")
            local_image = TEMP_DIR / "post_image.jpg"
            download_image(image_url, local_image)
            upload_image_in_composer(driver, wait, local_image)
            success("Image attached")
        else:
            info("No image for this item")

        # 10) Click Post
        step(10, "Clicking Post")
        click_post_button(driver, wait)
        success("Post button clicked successfully")

        # Record as posted immediately after successful click
        step(11, "Recording posted content")
        try:
            prepend_posted({
                "title": first.get("title"),
                "description": first.get("description"),
                "image": first.get("image"),
            })
            success("posted_content.json updated (prepended)")
        except Exception as e:
            warn(f"Could not update posted_content.json: {e}")

        # 12) Wait 15 seconds, then close
        step(12, "Finalizing and waiting for publication")
        time.sleep(15)
        success("Done")
        return 0
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        # Clear temp once more on finish
        try:
            clear_temp_folder(TEMP_DIR)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
