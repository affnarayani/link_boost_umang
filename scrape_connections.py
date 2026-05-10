import json
import re
import time
import random
import sys
import os
from login import login_and_get_context

# --- Configuration ---
TARGET_URL = f"https://www.linkedin.com/search/results/people/?geoUrn=%5B%22113536609%22%5D&keywords=advocate&origin=FACETED_SEARCH"
OUTPUT_FILE = "scraped_connections.json"
# ---------------------


def save_to_json(data):
    """
    Save scraped data instantly after every profile.
    """
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )


def scrape_connections():

    pw, browser, context, page = login_and_get_context()

    all_scraped_data = []
    processed_links = set()

    try:

        # -----------------------------------
        # CLEAR JSON AT START
        # -----------------------------------
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4)

        print("Previous JSON cleared.", flush=True)

        print(f"Navigating to: {TARGET_URL}", flush=True)

        page.goto(TARGET_URL, wait_until="load")

        page.wait_for_timeout(5000)

        while True:

            print("Waiting for page to settle.", flush=True)

            time.sleep(random.uniform(5, 10))

            # -----------------------------------
            # SCROLL PAGE
            # -----------------------------------
            print("Scrolling page...", flush=True)

            for _ in range(6):
                page.mouse.wheel(0, 2000)
                time.sleep(1)

            try:
                page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
            except:
                pass

            time.sleep(5)

            # -----------------------------------
            # FIND CONNECT BUTTONS
            # -----------------------------------
            invite_buttons = page.get_by_role(
                "link",
                name=re.compile(r"Invite .* to connect", re.I)
            ).all()

            print(
                f"Status: Found {len(invite_buttons)} connect buttons on this page.",
                flush=True
            )

            # -----------------------------------
            # PROCESS EACH PROFILE
            # -----------------------------------
            for invite_btn in invite_buttons:

                try:

                    aria_label = (
                        invite_btn.get_attribute("aria-label") or ""
                    ).strip()

                    match = re.search(
                        r"Invite\s+(.*?)\s+to connect",
                        aria_label,
                        re.I
                    )

                    if not match:
                        continue

                    name = match.group(1).strip()

                    # -----------------------------------
                    # FIND PROFILE LINK
                    # -----------------------------------
                    profile_link_locator = page.get_by_role(
                        "link",
                        name=re.compile(re.escape(name), re.I)
                    ).first

                    if profile_link_locator.count() == 0:
                        print(
                            f"Profile link not found for: {name}",
                            flush=True
                        )
                        continue

                    profile_url = profile_link_locator.get_attribute("href")

                    if not profile_url:
                        continue

                    # Make full LinkedIn URL
                    if profile_url.startswith("/"):
                        profile_url = f"https://www.linkedin.com{profile_url}"

                    # Remove tracking params
                    profile_url = profile_url.split("?")[0]

                    # Validate LinkedIn profile URL
                    if "/in/" not in profile_url:
                        continue

                    # Skip duplicates
                    if profile_url in processed_links:
                        continue

                    processed_links.add(profile_url)

                    profile_data = {
                        "name": name,
                        "link": profile_url,
                        "invited": False
                    }

                    all_scraped_data.append(profile_data)

                    # -----------------------------------
                    # SAVE INSTANTLY
                    # -----------------------------------
                    save_to_json(all_scraped_data)

                    print(f"Saved instantly: {name}", flush=True)

                except Exception as e:
                    print(
                        f"Profile processing error: {e}",
                        flush=True
                    )
                    continue

            # -----------------------------------
            # NEXT BUTTON
            # -----------------------------------
            try:

                next_button = page.get_by_test_id(
                    "pagination-controls-next-button-visible"
                )

                if next_button.count() == 0:
                    print("Next button not found. Ending.", flush=True)
                    break

                is_disabled = next_button.get_attribute("disabled")

                if is_disabled is not None:
                    print("Reached final page.", flush=True)
                    break

                print("Clicking next page...", flush=True)

                next_button.scroll_into_view_if_needed()

                time.sleep(random.uniform(2, 4))

                next_button.click()

                page.wait_for_load_state("load")

                page.wait_for_timeout(
                    random.randint(4000, 7000)
                )

            except Exception as e:
                print(f"Pagination error: {e}", flush=True)
                break

        print(
            f"Process Finished. Total {len(all_scraped_data)} profiles saved.",
            flush=True
        )

    except Exception as e:
        print(f"Scraping Error: {e}", flush=True)
        sys.exit(1)

    finally:
        try:
            browser.close()
            pw.stop()
        except:
            pass


if __name__ == "__main__":
    scrape_connections()