import time
import json
import os
import re
import random
import sys
from datetime import datetime
from playwright.sync_api import expect
from login import login_and_get_context

def make_connections():
    # 1. Login session mangwao (Importing from login.py)
    pw, browser, context, page = login_and_get_context()
    
    json_file = 'scraped_connections.json'
    
    if not os.path.exists(json_file):
        print(f"[ERROR] {json_file} file nahi mili!", flush=True)
        pw.stop()
        sys.exit(1)

    # 2. JSON Data load karo
    with open(json_file, 'r', encoding='utf-8') as f:
        connections = json.load(f)

    invitation_sent_successfully = False

    try:
        for index, person in enumerate(connections):
            # Agar pehle se invited hai toh skip karo
            if person.get('invited') is True:
                continue
            
            profile_link = person.get('link')
            profile_name = person.get('name', 'User')
            
            print(f"\n[PROCESS] Target: {profile_name}", flush=True)
            print(f"[NAVIGATE] Visiting: {profile_link}", flush=True)
            
            # Profile page par navigate karein aur random wait karein
            page.goto(profile_link)
            print(f"[WAIT] Waiting for profile to load...", flush=True)
            time.sleep(random.uniform(8, 15)) 

            # 3. Regex Locators for 'Invite'
            # Pattern: 'Invite' se shuru hone wala button
            invite_regex = re.compile(r"^Invite.*", re.IGNORECASE)
            
            # Dono locators search karein
            loc1 = page.get_by_test_id('lazy-column').get_by_role('link', name=invite_regex)
            loc2 = page.get_by_role('button', name=invite_regex)

            target_invite_btn = None
            if loc1.count() > 0 and loc1.first.is_visible():
                target_invite_btn = loc1.first
            elif loc2.count() > 0 and loc2.first.is_visible():
                target_invite_btn = loc2.first

            # 4. Action Logic
            if target_invite_btn:
                print(f"[ACTION] Invite button mil gaya. Clicking in a moment...", flush=True)
                time.sleep(random.uniform(5, 10)) # Click se pehle human-like pause
                target_invite_btn.click()
                
                # Verify Pop-up: 'Add a note to your invitation?'
                popup_header = page.get_by_role('heading', name='Add a note to your invitation?')
                
                try:
                    # Check if popup appeared
                    expect(popup_header).to_be_visible(timeout=12000)
                    print("[INFO] Invitation popup verified. Waiting before sending...", flush=True)
                    time.sleep(random.uniform(6, 12)) 
                    
                    # 'Send' button click karein
                    send_btn = page.get_by_role('button', name='Send', exact=False)
                    send_btn.click()
                    
                    print("[SUCCESS] Invitation sent!", flush=True)
                    # Send ke baad update aur 5-10 second ka wait
                    connections[index]['invited'] = True
                    connections[index]['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    time.sleep(random.uniform(5, 8))
                    invitation_sent_successfully = True
                    
                    # Ek invitation bhej di, ab break karke exit karenge
                    break 

                except Exception as e:
                    print(f"Popup didn't load. Maybe the connection was withdrawn within last 3 weeks.", flush=True)
                    connections[index]['invited'] = True
                    connections[index]['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Agar locator nahi mila (Invite button missing)
                print(f"[SKIP] Invite button missing for {profile_name}. Updating JSON...", flush=True)
                connections[index]['invited'] = True
                connections[index]['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # File save karke next profile par move karein
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(connections, f, indent=4)
                
                time.sleep(random.uniform(5, 10))
                continue 

        # 5. Final JSON Update
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(connections, f, indent=4)

        if invitation_sent_successfully:
            print("\n" + "="*50, flush=True)
            print(f"RESULT: 1 Invitation sent to {profile_name}", flush=True)
            print("="*50, flush=True)
        else:
            print("\n[FINISH] No new invitations were sent.", flush=True)

    except Exception as e:
        print(f"[CRITICAL ERROR] Logic failed: {e}", flush=True)
        sys.exit(1)
    finally:
        print("[INFO] Closing browser session...", flush=True)
        browser.close()
        pw.stop()

if __name__ == "__main__":
    make_connections()