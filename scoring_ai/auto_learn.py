"""
auto_learn.py — Scoring AI v2: Live Auto-Learning Daemon
==========================================================
Watches the bot's live trade CSVs (V15, V12).
When new trades are detected, it builds their 20-dim context vectors
and appends them to vector_db.json, allowing the AI to learn in real-time.

Runs continuously as a background daemon.
"""

import os
import sys
import json
import time
import pandas as pd
from datetime import datetime, timezone
import logging

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import collector  # Import collector.py to reuse build_vector logic

# ==========================================
# CONFIG
# ==========================================
POLL_INTERVAL = 60  # seconds

CSV_FILES = [
    "/opt/ct4/logs/v15_trades.csv",
    "/opt/ct4/logs/v12_trades.csv"
]
# Local fallback for testing:
LOCAL_CSVS = [
    os.path.join(os.path.dirname(__file__), "..", "v15_trades.csv"),
    os.path.join(os.path.dirname(__file__), "..", "v12_trades.csv"),
]

DB_PATH = os.path.join(os.path.dirname(__file__), "vector_db.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "auto_learn.log")

# ==========================================
# LOGGING
# ==========================================
log = logging.getLogger("AutoLearn")
log.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setFormatter(logging.Formatter('%(asctime)s [AutoLearn] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
log.addHandler(fh)
sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter('%(asctime)s [AutoLearn] %(message)s', datefmt='%H:%M:%S'))
log.addHandler(sh)


# ==========================================
# CORE LOGIC
# ==========================================
def load_db():
    if not os.path.exists(DB_PATH):
        log.error(f"Vector DB not found at {DB_PATH}. Run collector.py first.")
        return None
    with open(DB_PATH, encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    try:
        # Save to temp file first to prevent corruption
        tmp = DB_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        os.replace(tmp, DB_PATH)
        return True
    except Exception as e:
        log.error(f"Failed to save DB: {e}")
        return False

def get_latest_db_time(db):
    records = db.get("records", [])
    if not records:
        return ""
    # Find max close_time
    max_time = ""
    for r in records:
        ct = r.get("close_time", "")
        if ct > max_time:
            max_time = ct
    return max_time

def process_new_trades():
    db = load_db()
    if not db:
        return

    latest_db_time = get_latest_db_time(db)
    new_records = []
    
    # Check all configured CSVs
    csvs_to_check = CSV_FILES if os.path.exists(os.path.dirname(CSV_FILES[0])) else LOCAL_CSVS
    
    for csv_path in csvs_to_check:
        if not os.path.exists(csv_path):
            continue
            
        try:
            df = pd.read_csv(csv_path)
            if df.empty:
                continue
                
            # Filter rows newer than DB
            if latest_db_time:
                # Convert both to string for simple lexical comparison since ISO 8601 sorts lexically
                df = df[df['close_time'].astype(str) > latest_db_time]
                
            if df.empty:
                continue
                
            log.info(f"Found {len(df)} new trades in {os.path.basename(csv_path)}")
            
            # Process each new trade
            for _, row in df.iterrows():
                vec_record = collector.build_vector(row)
                if vec_record:
                    # Enrich with strategy name if missing
                    if 'strategy' not in vec_record or vec_record['strategy'] == 'UNKNOWN':
                        if 'v15' in csv_path.lower():
                            vec_record['strategy'] = 'V15_Scalper'
                        elif 'v12' in csv_path.lower():
                            vec_record['strategy'] = 'V12_Shadow'
                    new_records.append(vec_record)
                    
        except Exception as e:
            log.error(f"Error processing {csv_path}: {e}")

    if not new_records:
        return

    # Append new records and update stats
    records = db.get("records", [])
    records.extend(new_records)
    
    # Recalculate totals
    winners = sum(1 for r in records if r.get("outcome") == 1)
    losers  = sum(1 for r in records if r.get("outcome") == 0)
    
    by_strategy = db.get("by_strategy", {})
    for r in new_records:
        s = r.get("strategy", "UNKNOWN")
        if s not in by_strategy:
            by_strategy[s] = {"total": 0, "wins": 0}
        by_strategy[s]["total"] += 1
        if r.get("outcome") == 1:
            by_strategy[s]["wins"] += 1

    db["total_trades"] = len(records)
    db["winners"] = winners
    db["losers"] = losers
    db["win_rate"] = round(winners / len(records) * 100, 1) if records else 0
    db["by_strategy"] = by_strategy
    
    # We do NOT run full NORM_RANGES/stats recalculation on every trade to stay fast.
    # A weekly full rebuild via collector.py is recommended.

    if save_db(db):
        log.info(f"✅ Added {len(new_records)} new trades to Vector DB.")
        log.info(f"   Total Trades: {db['total_trades']} | Win Rate: {db['win_rate']}%")


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    log.info("🤖 Auto-Learning Daemon Started")
    log.info(f"Watching CSVs: {[os.path.basename(c) for c in CSV_FILES]}")
    
    # Run once immediately
    process_new_trades()
    
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            process_new_trades()
    except KeyboardInterrupt:
        log.info("Daemon stopped by user.")
