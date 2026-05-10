import subprocess
import sys
import json
import re
import os
import requests
import time
import random
import shutil
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

from login import login_and_get_context

# --- HF Setup ---
load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("HF_TOKEN not found in environment variables")

client = InferenceClient(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    token=HF_TOKEN
)

# --- Configuration ---
GITHUB_RAW_URL = "https://raw.githubusercontent.com/affnarayani/ninetynine_credits_legal_advice_app_content/refs/heads/main/content.json"
POSTED_FILE = "posted_content.json"
TEMP_FOLDER = "temp"

MAX_RETRIES = 3


def sanitize_ai_content(text):
    clean_text = text.replace("**", "").replace("*", "")
    return clean_text.strip().strip('"').strip("'")


# --- HF Rewrite ---
def rewrite_with_hf(text):
    print("[AI] Rewriting with HuggingFace...", flush=True)

    prompt = (
        f"Rewrite the legal content below into a high-performing LinkedIn post (~120 words).\n"
        f"Rules:\n"
        f"- Exactly 2 paragraphs\n"
        f"- Paragraph 1: Strong hook\n"
        f"- Paragraph 2: Insightful explanation\n"
        f"- End with a thought-provoking question\n"
        f"- Use clear, professional, SEO-friendly language\n"
        f"- Do NOT use symbols like * or **\n"
        f"- IMPORTANT: Add 5–10 relevant hashtags on a new line at the end\n"
        f"- No extra commentary or headings\n"
        f"Content: {text}"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"[Attempt {attempt}] Sending request...", flush=True)

            response = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7
            )

            result = response.choices[0].message.content
            return sanitize_ai_content(result)

        except Exception as e:
            err = str(e)
            print("[ERROR]", err, flush=True)

            if "429" in err.lower():
                print("[WAIT] 10 sec...", flush=True)
                time.sleep(10)
                continue

            if attempt < MAX_RETRIES:
                time.sleep(5)
            else:
                print("[FALLBACK] Using original text", flush=True)
                return sanitize_ai_content(text)


def random_delay(step_name, min_s=10, max_s=20):
    delay = random.uniform(min_s, max_s)
    print(f"[STEP] {step_name} | Waiting {delay:.2f}s", flush=True)
    time.sleep(delay)


def clean_temp():
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER)
    os.makedirs(TEMP_FOLDER)


def clean_html(raw_html):
    clean_text = re.sub(r'</?p>', '', raw_html)
    clean_text = re.sub(r'\n\s*\n+', '\n\n', clean_text)
    return clean_text.strip()


def download_image(url):
    print(f"[INFO] Downloading image: {url}", flush=True)
    local_filename = os.path.join(TEMP_FOLDER, "post_image.jpg")

    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)

        return os.path.abspath(local_filename)

    except Exception as e:
        print(f"[ERROR] Image download failed: {e}", flush=True)
        return None


def run_post_automation():
    clean_temp()

    # --- Fetch content ---
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=20)
        new_content = response.json()
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}", flush=True)
        sys.exit(1)

    # --- History ---
    posted_data = []
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            try:
                posted_data = json.load(f)
            except:
                posted_data = []

    posted_titles = [item['title'] for item in posted_data]

    # --- Find new ---
    target_item = None
    original_desc = ""

    for item in reversed(new_content):
        if item['title'] not in posted_titles:
            original_desc = clean_html(item['description'])
            target_item = item
            break

    if not target_item:
        print("[INFO] No new content found.", flush=True)
        return

    # --- AI Rewrite ---
    final_description = rewrite_with_hf(original_desc)

    # --- Image ---
    image_path = download_image(target_item['image'])
    if not image_path:
        sys.exit(1)

    # --- LinkedIn (LOCATORS UNCHANGED) ---
    pw, browser, context, page = login_and_get_context()

    try:
        random_delay("LinkedIn Load", 15, 25)

        page.get_by_role("button", name="Start a post").click()

        random_delay("Editor Open")

        editor = page.get_by_role("textbox", name="Text editor for creating")
        editor.wait_for(state="visible")
        editor.fill(final_description)

        random_delay("Typing")

        page.get_by_role("button", name="Add media").click()
        page.set_input_files("input[type='file']", image_path)

        random_delay("Upload")

        page.get_by_test_id("interop-shadowdom").get_by_role("button", name="Next").click()

        random_delay("Next")

        page.get_by_role("button", name="Post", exact=True).click()

        random_delay("Final", 15, 20)

        posted_data.insert(0, target_item)

        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(posted_data, f, indent=4)

        print(f"[SUCCESS] Posted: {target_item['title']}", flush=True)

    except Exception as e:
        print(f"[ERROR] Failed: {e}", flush=True)
        sys.exit(1)

    finally:
        browser.close()
        pw.stop()
        clean_temp()


if __name__ == "__main__":
    run_post_automation()