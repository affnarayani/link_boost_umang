import json
import re
import time
import random
import sys
from login import login_and_get_context

# --- Configuration ---
TARGET_URL = f"https://www.linkedin.com/search/results/people/?geoUrn=%5B%22113536609%22%5D&keywords=advocate&origin=FACETED_SEARCH"
OUTPUT_FILE = "scraped_connections.json"
# ---------------------

def scrape_connections():
    pw, browser, context, page = login_and_get_context()
    all_scraped_data = []

    try:
        print(f"Navigating to: {TARGET_URL}", flush=True)
        page.goto(TARGET_URL, wait_until="load")
        
        while True:
            print("Waiting for page to settle.", flush=True)
            time.sleep(random.uniform(15, 30)) 

            # --- 1. SET CONTEXT ---
            iframe_locator = page.locator('[data-testid="interop-iframe"]')
            if iframe_locator.count() > 0:
                target_frame = iframe_locator.content_frame
                main_context = target_frame.get_by_role('main')
            else:
                target_frame = page
                main_context = page.get_by_role('main')

            # --- 2. MULTI-METHOD SCROLL (Fix for Lazy Loading) ---
            print("Scrolling to the bottom using multiple methods...", flush=True)
            time.sleep(random.uniform(15, 30)) 
            
            # Method A: Mouse Scroll (Mimics human behavior)
            for _ in range(5):
                page.mouse.wheel(0, 1000)
                time.sleep(0.5)

            # Method B: JavaScript Scroll inside Iframe
            try:
                target_frame.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except: pass
            
            # Method C: Scroll to the last profile found
            try:
                last_profile = main_context.locator(".search-results-container a[aria-label^='View ']").last
                if last_profile.count() > 0:
                    last_profile.scroll_into_view_if_needed()
            except: pass
            
            time.sleep(3) # Wait for buttons to render

            # --- 3. SCRAPING LOGIC ---
            container_selector = '.search-results-container'
            profile_links = main_context.locator(f"{container_selector} a[aria-label^='View ']").all()
            
            if not profile_links:
                profile_links = main_context.locator(f"a:has-text('View ')").all()

            print(f"Status: Found {len(profile_links)} profiles on this page.", flush=True)

            for link_locator in profile_links:
                try:
                    raw_label = link_locator.get_attribute("aria-label") or ""
                    raw_text = link_locator.inner_text() or ""
                    combined = f"{raw_label} {raw_text}".strip()
                    
                    match = re.search(r"View\s+(.+?)(?:'s|’s| profile)", combined, re.IGNORECASE)
                    name = match.group(1).strip() if match else combined.replace("View ", "").split("'s")[0].split("’s")[0].strip()

                    invite_btn = main_context.get_by_role('button', name=f"Invite {name}")
                    
                    if invite_btn.count() > 0:
                        profile_url = link_locator.get_attribute("href")
                        if profile_url and not profile_url.startswith("http"):
                            profile_url = f"https://www.linkedin.com{profile_url}"

                        all_scraped_data.append({
                            "name": name,
                            "link": profile_url,
                            "invited": False
                        })
                except: continue

            # --- 4. PAGINATION LOGIC ---
            pagination_text_locator = main_context.get_by_text(re.compile(r"Page \d+ of \d+", re.IGNORECASE))
            
            if pagination_text_locator.count() > 0:
                full_text = pagination_text_locator.first.inner_text()
                page_match = re.search(r"Page (\d+) of (\d+)", full_text, re.IGNORECASE)
                
                if page_match:
                    current_page = int(page_match.group(1))
                    total_pages = int(page_match.group(2))
                    print(f"Status: Page {current_page} of {total_pages} processed.", flush=True)

                    if current_page < total_pages:
                        next_button = main_context.get_by_role('button', name='Next')
                        
                        if next_button.count() > 0:
                            print("Next button found. Clicking...", flush=True)
                            next_button.scroll_into_view_if_needed() # Final check
                            next_button.click()
                            page.wait_for_load_state("load")
                        else:
                            print("Next button not found physically. Ending.", flush=True)
                            break
                    else:
                        print("Reached final page.", flush=True)
                        break
                else: break
            else:
                print("Pagination text not found. Ending.", flush=True)
                break

        # 5. Final Save
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_scraped_data, f, indent=4)
        
        print(f"Process Finished. Total {len(all_scraped_data)} profiles saved to {OUTPUT_FILE}", flush=True)

    except Exception as e:
        print(f"Scraping Error: {e}", flush=True)
        sys.exit(1)
    finally:
        try:
            browser.close()
            pw.stop()
        except: pass

if __name__ == "__main__":
    scrape_connections()