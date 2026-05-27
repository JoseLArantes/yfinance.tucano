import os
import sys
import time
import json
import urllib.request
import urllib.error

def run_scheduler():
    # URL of the main service, default to internal k8s service
    api_url = os.environ.get("API_URL", "http://tucano-yfinance:8009")
    api_token = os.environ.get("DEFAULT_API_TOKEN")
    period = os.environ.get("SYNC_PERIOD", "1mo")
    sync_raw_str = os.environ.get("SYNC_RAW", "false")
    
    sync_raw = sync_raw_str.lower() in ("true", "1", "yes")

    print(f"Starting daily sync scheduler. Connecting to: {api_url}")
    
    # 1. Fetch all tickers
    req = urllib.request.Request(
        f"{api_url}/api/v1/tickers",
        headers={"Authorization": f"Bearer {api_token}"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            tickers = json.loads(response.read().decode())
    except Exception as e:
        print(f"Failed to fetch tickers list from API: {e}")
        sys.exit(1)
        
    if not tickers:
        print("No tickers found in the database. Nothing to sync.")
        sys.exit(0)
        
    print(f"Found {len(tickers)} tickers to synchronize: {tickers}")
    
    sleep_interval = int(os.environ.get("SLEEP_INTERVAL", "300"))
    
    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Syncing ticker: {ticker} (period={period}, sync_raw={sync_raw})...")
        sync_endpoint = f"{api_url}/api/v1/tickers/{ticker}/sync?period={period}&sync_raw={str(sync_raw).lower()}"
        
        sync_req = urllib.request.Request(
            sync_endpoint,
            headers={"Authorization": f"Bearer {api_token}"},
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(sync_req, timeout=120) as response:
                res_data = json.loads(response.read().decode())
                print(f"Successfully synced {ticker}: {res_data}")
        except urllib.error.HTTPError as e:
            print(f"Failed to sync {ticker}. Status: {e.code}, Detail: {e.read().decode()}")
        except Exception as e:
            print(f"Error calling sync endpoint for {ticker}: {e}")
            
        # Space out runs if there are more tickers remaining
        if i < len(tickers) - 1:
            print(f"Waiting {sleep_interval} seconds before the next ticker sync...")
            time.sleep(sleep_interval)
            
    print("All tickers successfully processed. Scheduler exiting.")

if __name__ == "__main__":
    run_scheduler()
