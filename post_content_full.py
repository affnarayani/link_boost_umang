import json
import re
import os
import requests
import time
import random
import shutil
import sys
from login import login_and_get_context

# --- Configuration ---
GITHUB_RAW_URL = "https://raw.githubusercontent.com/affnarayani/ninetynine_credits_legal_advice_app_content/refs/heads/main/content.json"
CONTENT_FILE = "content.json"
POSTED_FILE = "posted_content.json"
TEMP_FOLDER = "temp"
MAX_CHAR_LIMIT = 2800 # LinkedIn safely allows up to 3000, 2800 is a safe buffer

def random_delay(step_name, min_s=5, max_s=15):
    delay = random.uniform(min_s, max_s)
    print(f"[STEP] {step_name} | Waiting for {delay:.2f} seconds...", flush=True)
    time.sleep(delay)

def clean_temp():
    if os.path.exists(TEMP_FOLDER):
        shutil.rmtree(TEMP_FOLDER)
    os.makedirs(TEMP_FOLDER)
    print("[INFO] Temp folder cleared.", flush=True)

def clean_html(raw_html):
    # 1. Pehle <p> aur </p> tags ko completely remove karein (bina extra \n add kiye)
    clean_text = re.sub(r'</?p>', '', raw_html)
    # 2. Ab jo \n\n pehle se JSON mein hain, unhe normalize karein 
    # Taaki sirf EK khali line bache paragraphs ke beech mein
    clean_text = re.sub(r'\n\s*\n+', '\n\n', clean_text)
    # 3. * aur ** remove karein
    clean_text = clean_text.replace("*", "")
    return clean_text.strip()

def download_image(url):
    print(f"[INFO] Downloading image: {url}", flush=True)
    local_filename = os.path.join(TEMP_FOLDER, "post_image.jpg")
    try:
        with requests.get(url, stream=True, timeout=20) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return os.path.abspath(local_filename)
    except Exception as e:
        print(f"[ERROR] Image download failed: {e}", flush=True)
        return None

def run_post_automation():
    clean_temp()
    
    # 1. Fetch GitHub Content
    print("[INFO] Fetching content from GitHub...", flush=True)
    try:
        response = requests.get(GITHUB_RAW_URL, timeout=20)
        new_content = response.json()
        with open(CONTENT_FILE, "w", encoding="utf-8") as f:
            json.dump(new_content, f, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to fetch content: {e}", flush=True)
        sys.exit(1)

    # 2. Check posted history
    posted_data = []
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, "r", encoding="utf-8") as f:
            try:
                posted_data = json.load(f)
            except: posted_data = []
    
    posted_titles = [item['title'] for item in posted_data]

    # 3. Find uncommon content (Bottom to Top) with Character Limit check
    target_item = None
    clean_description = ""
    
    for item in reversed(new_content):
        if item['title'] not in posted_titles:
            processed_text = clean_html(item['description'])
            # Check length: LinkedIn char limit focus
            if len(processed_text) <= MAX_CHAR_LIMIT:
                target_item = item
                clean_description = processed_text
                break
            else:
                print(f"[SKIP] '{item['title']}' is too long ({len(processed_text)} chars).", flush=True)

    if not target_item:
        print("[INFO] No suitable new content found (either posted or too long).", flush=True)
        return

    print(f"[TARGET] Found post: {target_item['title']} ({len(clean_description)} chars)", flush=True)

    # 4. Prepare Media
    image_path = download_image(target_item['image'])
    if not image_path:
        sys.exit(1)

    # 5. LinkedIn Activity
    pw, browser, context, page = login_and_get_context()

    try:
        random_delay("Preparing LinkedIn Homepage", 15, 30)
        
        print("[ACTION] Opening Post Editor...", flush=True)
        page.get_by_role("button", name="Start a post").click()
        random_delay("Wait after Start a Post click")

        print("[ACTION] Filling description...", flush=True)
        editor = page.get_by_role("textbox", name="Text editor for creating")
        editor.wait_for(state="visible")
        editor.fill(clean_description)
        random_delay("Wait after typing")
        
        print("[ACTION] Uploading Media...", flush=True)
        page.get_by_role("button", name="Add media").click()
        random_delay("Wait for Media Dialog")
        
        page.get_by_role("heading", name="Select files to begin").wait_for(state="visible")
        page.set_input_files("input[type='file']", image_path)
        random_delay("Wait after selecting file")
        
        page.get_by_role("button", name="Next").click()
        random_delay("Wait after Next click")
        
        print("[ACTION] Finalizing Post...", flush=True)
        post_btn = page.get_by_role("button", name="Post", exact=True)
        post_btn.wait_for(state="visible")
        post_btn.click()
        
        print("[INFO] Uploading to LinkedIn servers...", flush=True)
        random_delay("Final Processing Buffer", 15, 30)

        # 6. Update Posted File (Top Append)
        posted_data.insert(0, target_item)
        with open(POSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(posted_data, f, indent=4)
        print(f"[SUCCESS] Posted: {target_item['title']}", flush=True)

    except Exception as e:
        print(f"[ERROR] Automation failed: {e}", flush=True)
        sys.exit(1)
    finally:
        print("[INFO] Shutting down and cleaning temp...", flush=True)
        browser.close()
        pw.stop()
        clean_temp()

if __name__ == "__main__":
    run_post_automation()