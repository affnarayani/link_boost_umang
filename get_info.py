import os
import json
import re
from datetime import datetime
from login import login_and_get_context 
import sys

# --- Configuration ---
GROW_URL = "https://www.linkedin.com/mynetwork/grow/"
INFO_FILE = "linkedin_info.json"

def perform_activity():
    # login.py se session start karein
    pw, browser, context, page = login_and_get_context()

    try:
        # Navigation status (extracted value nahi)
        page.goto(GROW_URL, wait_until="domcontentloaded")

        # Connection link selector
        target_link_selector = 'a[href*="/mynetwork/invite-connect/connections"]'
        connections_locator = page.locator(target_link_selector)
        
        # Numeric value load hone ka wait (Silent wait)
        try:
            page.wait_for_function(
                f"""(sel) => {{
                    const el = document.querySelector(sel);
                    return el && /\d+/.test(el.innerText);
                }}""",
                arg=target_link_selector,
                timeout=15000
            )
        except:
            pass

        if connections_locator.first.is_visible():
            # Data extraction (Value console par print nahi hogi)
            full_text = connections_locator.first.inner_text()
            aria_label = connections_locator.first.get_attribute("aria-label") or ""
            combined_text = f"{full_text} {aria_label}"
            
            match = re.search(r'(\d+)', combined_text)
            
            if match:
                count = match.group(1)
                
                # New Fresh Data Object
                new_data = [
                    {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "connections": count
                    }
                ]

                # Clear and Write: Purana data delete ho jayega aur naya feed hoga
                with open(INFO_FILE, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, indent=4)
                
                # Success message (Binary status, not the value)
                print("Status: Information updated successfully in JSON.", flush=True)
            else:
                print("Status: Failed to find numeric data.", flush=True)
                sys.exit(1)
        else:
            print("Status: Target element not visible.", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"Status: Activity Error occurred.", flush=True)
        sys.exit(1)
    finally:
        # Silent Cleanup
        try:
            browser.close()
            pw.stop()
        except:
            pass
    print("Process Finished.", flush=True)

if __name__ == "__main__":
    perform_activity()