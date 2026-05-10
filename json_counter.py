import json
from datetime import datetime, timedelta

def process_scraped_data(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
    except FileNotFoundError:
        print("Error: scraped_connections.json file nahi mili.", flush=True)
        return

    # 1. Total number of items
    total_items = len(data)
    
    # 2. Total items with invited = False
    invited_false_count = sum(1 for item in data if item.get("invited") is False)
    
    # 3. Total elements without 'withdraw' key
    no_withdraw_count = sum(1 for item in data if "withdraw" not in item)
    
    # 4. Timestamp logic
    timestamps = [datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S") for item in data if "timestamp" in item]
    
    latest_timestamp = None
    date_status = "N/A"
    
    if timestamps:
        latest_timestamp = max(timestamps)
        # Add 7 days to the latest timestamp
        target_date = latest_timestamp + timedelta(days=7)
        current_date = datetime.now()
        
        if target_date > current_date:
            date_status = "WAIT"
        else:
            date_status = "PROCEED"

    # Printing Results
    print(f"Total number of items: {total_items}", flush=True)
    print(f"Total number of items with invited = false: {invited_false_count}", flush=True)
    print(f"Total elements without 'withdraw' key: {no_withdraw_count}", flush=True)
    
    if latest_timestamp:
        print(f"Latest timestamp: {latest_timestamp}", flush=True)
        print(f"Status: {date_status}", flush=True)

# Script run karein
process_scraped_data('scraped_connections.json')