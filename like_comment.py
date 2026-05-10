import time
import random
import re
import json
import os
import subprocess
import sys
from playwright.sync_api import expect
from login import login_and_get_context
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv()
# --- HF Client Setup (NO HARDCODE TOKEN) ---
HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise ValueError("HF_TOKEN not found in environment variables")

client = InferenceClient(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    token=HF_TOKEN
)

MAX_RETRIES = 3

def get_posted_links():
    file_path = 'liked_commented.json'
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return [item['post_link'] for item in data if 'post_link' in item]
    except Exception as e:
        print(f"[ERROR] JSON read failed: {e}", flush=True)
        return []

def save_to_json_top(new_link):
    file_path = 'liked_commented.json'
    data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            data = []
    
    data.insert(0, {"post_link": new_link})
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    print(f"[SUCCESS] Saved to JSON: {new_link}", flush=True)

# --- HF COMMENT GENERATION ---
def generate_ai_comment(content):
    try:
        prompt = (
            f"Understand the sentiment, context, and intent of the content first and then write a 30-word viral-style comment that feels human, adds a strong perspective, and is engaging enough to attract replies or reactions."
            f"Comment only, no quotes, no asterisks, no prefix.\nContent: {content}"
        )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=80,
                    temperature=0.7
                )

                result = response.choices[0].message.content
                clean_comment = result.replace('*', '').replace('"', '').strip()
                return clean_comment

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
                    break

        raise Exception("HF comment generation failed")

    except Exception as e:
        print(f"[ERROR] HF Generation failed: {e}", flush=True)
        raise Exception("HF comment generation failed")


def extract_single_new_share_link():
    pw, browser, context, page = login_and_get_context()

    try:
        already_posted = get_posted_links()
        print(f"[INFO] Loaded {len(already_posted)} links from JSON.", flush=True)

        time.sleep(random.uniform(8, 12))

        workspace = page.locator('#workspace')
        menu_pattern = re.compile(r"Open control menu for post by .*", re.IGNORECASE)
        control_menu_locator = page.get_by_role('button', name=menu_pattern)

        # ✅ SINGLE SCROLL
        workspace.focus()
        page.keyboard.press("PageDown")
        page.evaluate("document.querySelector('#workspace').scrollBy(0, 1000)")
        print("[ACTION] Scroll 1/1...", flush=True)
        time.sleep(5)

        menus = control_menu_locator.all()

        for menu in menus:
            try:
                if not menu.is_visible():
                    continue

                menu.scroll_into_view_if_needed()
                menu.click()
                time.sleep(2)

                embed_item = page.get_by_role('menuitem', name='Embed this post')
                if embed_item.count() == 0:
                    page.keyboard.press("Escape")
                    continue

                embed_item.click()
                time.sleep(3)

                embed_textbox = page.locator("#feed-components-shared-embed-modal__snippet")
                if not embed_textbox.is_visible():
                    sys.exit(1)

                raw_embed = None
                for _ in range(20):
                    try:
                        val = embed_textbox.input_value()
                        if val and "iframe" in val.lower():
                            raw_embed = val
                            break
                    except:
                        pass
                    time.sleep(0.5)

                if not raw_embed:
                    sys.exit(1)

                match = re.search(r'src="([^"]+)"', raw_embed)
                if not match:
                    sys.exit(1)

                full_url = match.group(1)
                base_url = full_url.split('?')[0]
                final_link = base_url.replace('/embed/', '/').strip()

                print(f"[DEBUG] Extracted link: {final_link}", flush=True)

                if "urn:li:share:" not in final_link:
                    sys.exit(1)

                if final_link in already_posted:
                    sys.exit(1)

                print(f"[NEW POST FOUND]: {final_link}", flush=True)

                page.get_by_text('Embed full post').click()
                time.sleep(8)

                iframe = page.frame_locator('iframe[title="Embed a post iframe"]')
                content_loc = iframe.locator('[data-test-id="main-feed-activity-embed-card__commentary"]')

                if content_loc.count() == 0:
                    sys.exit(1)

                content = content_loc.inner_text()

                if len(re.findall(r'[A-Za-z]', content)) < 60:
                    sys.exit(1)

                # expand "...more"
                more_btn = iframe.get_by_text('…more')
                if more_btn.count() > 0:
                    try:
                        if more_btn.is_visible():
                            more_btn.click()
                            time.sleep(1)
                    except:
                        pass

                ai_comment = generate_ai_comment(content)
                print(f"[AI COMMENT]: {ai_comment}", flush=True)

                # open post page
                with context.expect_page() as new_page_info:
                    iframe.get_by_role('link', name='Comment', exact=True).click()

                new_tab = new_page_info.value
                new_tab.bring_to_front()

                new_tab.wait_for_load_state("domcontentloaded")
                time.sleep(5)

                # =========================
                # LIKE (ONLY IF NOT LIKED)
                # =========================
                print("[ACTION] Checking Like state...", flush=True)

                not_liked_btn = new_tab.get_by_role('button', name='React Like', exact=True)
                liked_btn = new_tab.get_by_role('button', name='Unreact Like')

                if not_liked_btn.count() > 0 and not_liked_btn.first.is_visible():
                    print("[INFO] Not liked → liking", flush=True)
                    not_liked_btn.first.click()
                    time.sleep(3)

                elif liked_btn.count() > 0 and liked_btn.first.is_visible():
                    print("[INFO] Already liked → skip", flush=True)

                else:
                    print("[FAIL] Like button not found", flush=True)
                    sys.exit(1)

                # =========================
                # COMMENT (FINAL FLOW)
                # =========================
                try:
                    print("[ACTION] Opening comment box...", flush=True)

                    # 1. Open comment UI
                    comment_btn = new_tab.get_by_role('button', name='Comment', exact=True)

                    if comment_btn.count() == 0 or not comment_btn.first.is_visible():
                        print("[FAIL] Comment button not found", flush=True)
                        sys.exit(1)

                    comment_btn.first.click()
                    time.sleep(5)

                    # 2. Focus editor
                    comment_box = new_tab.get_by_role(
                        'textbox',
                        name='Text editor for creating'
                    ).get_by_role('paragraph')

                    if not comment_box.is_visible():
                        print("[FAIL] Comment box not visible", flush=True)
                        sys.exit(1)

                    comment_box.click()
                    time.sleep(5)

                    # 3. Human typing
                    print("[ACTION] Typing comment...", flush=True)
                    for char in ai_comment:
                        new_tab.keyboard.type(char)
                        time.sleep(random.uniform(0.02, 0.08))

                    time.sleep(5)

                    # 4. Click POST button
                    for _ in range(3):
                        new_tab.keyboard.press("Tab")
                        time.sleep(2)

                    time.sleep(2)
                    new_tab.keyboard.press("Enter")

                    print("[SUCCESS] Comment posted.", flush=True)

                    time.sleep(30)

                except Exception as e:
                    print(f"[FAIL] Comment failed: {e}", flush=True)
                    sys.exit(1)

                new_tab.close()

                save_to_json_top(final_link)

                print("\n[SUCCESS] DONE", flush=True)
                print("="*60, flush=True)
                print(f"RESULT: {final_link}", flush=True)
                print("="*60, flush=True)

                return

            except Exception as e:
                print(f"[FAIL] Exception: {e}", flush=True)
                sys.exit(1)

        print("[FAIL] No valid post found", flush=True)
        sys.exit(1)

    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    extract_single_new_share_link()