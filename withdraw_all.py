import time
import json
import os
import re
import random
import sys
from datetime import datetime, timedelta
from playwright.sync_api import expect
from login import login_and_get_context

def withdraw_all():
    json_file = 'scraped_connections.json'
    
    if not os.path.exists(json_file):
        print(f"[ERROR] {json_file} nahi mili!", flush=True)
        sys.exit(1)

    # 1. JSON Load aur Validation
    with open(json_file, 'r', encoding='utf-8') as f:
        connections = json.load(f)

    if not connections:
        print("[INFO] JSON khali hai.", flush=True)
        return

    # --- CONDITION 1: Latest Timestamp + 7 Days Check ---
    timestamps = [datetime.strptime(c['timestamp'], "%Y-%m-%d %H:%M:%S") for c in connections if 'timestamp' in c]
    if not timestamps:
        print("[WAIT] Kisi bhi record mein timestamp nahi mila.", flush=True)
        return

    latest_ts = max(timestamps)
    current_date = datetime.now()
    threshold_date = latest_ts + timedelta(days=7)

    if threshold_date > current_date:
        print(f"[WAIT] 7-day rule not met. Next run after: {threshold_date}", flush=True)
        return
    
    # --- CONDITION 2: Check if 'withdraw' key exists in ALL ---
    if not all('withdraw' in c for c in connections):
        print("[WAIT] Process not complete for all connections in JSON.", flush=True)
        return

    print("\n[START] All conditions met. Launching Stealth Browser...", flush=True)

    # 2. Start Stealth Browser (Login)
    pw, browser, context, page = login_and_get_context()

    try:
        page.goto("https://www.linkedin.com/mynetwork/invitation-manager/sent/")
        print("[NAVIGATE] Sent invitations page loaded.", flush=True)
        time.sleep(random.uniform(8, 12))

        # --- PHASE 1: EXPAND ALL (Load More) ---
        print("[PHASE 1] Expanding the list...", flush=True)
        while True:
            load_more_btn = page.get_by_role('button', name='Load more')
            if load_more_btn.is_visible():
                print("[ACTION] Clicking 'Load more'...", flush=True)
                load_more_btn.click()
                # Wait for new content to inject
                time.sleep(random.uniform(5, 10))
            else:
                print("[INFO] No more 'Load more' buttons. List is fully expanded.", flush=True)
                break

        # --- PHASE 2: WITHDRAWAL ---
        print("[PHASE 2] Starting withdrawal process...", flush=True)
        
        while True:
            # Hamesha first available "Withdraw" button uthao expanded list se
            target_link = page.get_by_role('listitem').get_by_role('link', name="Withdraw").first

            if target_link.count() == 0 or not target_link.is_visible():
                print("[FINISH] All visible invitations processed successfully.", flush=True)
                break

            print(f"[ACTION] Clicking Withdraw button...", flush=True)
            target_link.click()
            
            # Pop-up validation
            time.sleep(random.uniform(5, 15))
            popup_heading = page.get_by_role('heading', name='Withdraw invitation')
            
            if popup_heading.is_visible():
                print("[VERIFIED] Popup visible.", flush=True)
                time.sleep(random.uniform(5, 15))
                
                confirm_btn = page.get_by_role('button', name=re.compile(r"Withdraw", re.IGNORECASE))
                
                if confirm_btn.is_visible():
                    confirm_btn.click()
                    print("[SUCCESS] Invitation withdrawn.", flush=True)
                    # Har withdrawal ke baad thoda buffer time
                    time.sleep(random.uniform(5, 15))
                else:
                    print("[ERROR] Confirm button not found!", flush=True)
                    sys.exit(1)
            else:
                print("[ERROR] Popup did not appear!", flush=True)
                sys.exit(1)

    except Exception as e:
        print(f"[CRITICAL ERROR] {e}", flush=True)
        sys.exit(1)
    finally:
        print("[INFO] Closing session.", flush=True)
        browser.close()
        pw.stop()

if __name__ == "__main__":
    withdraw_all()