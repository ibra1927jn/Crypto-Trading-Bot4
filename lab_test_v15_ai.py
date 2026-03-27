"""
lab_test_v15_ai.py
==================
Tests the V15 analyze_scalp function and the auto_learn daemon locally.
"""

import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime, timezone
import os
import json

import v15_scalper
import scoring_ai.auto_learn as auto_learn
import scoring_ai.collector as collector

async def test_v15_analysis():
    print("--- 🧪 LAB TEST 1: V15 Scalper Indicators ---")
    exchange = ccxt.binance()
    sym = 'BTC/USDT'
    try:
        ohlcv = await exchange.fetch_ohlcv(sym, '15m', limit=200)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        cur_px = df['close'].iloc[-1]
        
        # Test analyze_scalp
        ok, sl, tp, atr_pct, adx, rsi, ema50_d, ema200_d, bb_pos, macd_norm, streak, regime, reason = v15_scalper.analyze_scalp(df.copy(), 'LONG', cur_px)
        
        print(f"BTC/USDT @ {cur_px}")
        print(f"  ADX: {adx:.1f} | RSI: {rsi:.1f} | ATR%: {atr_pct*100:.2f}%")
        print(f"  EMA50 Dist: {ema50_d:.2f}% | EMA200 Dist: {ema200_d:.2f}%")
        print(f"  BB Position: {bb_pos:.2f} | MACD Hist: {macd_norm:.4f}")
        print(f"  Streak: {streak} | Regime: {regime}")
        print(f"  Signal: {'YES' if ok else 'NO'} ({reason})")
        print("✅ V15 Indicator Calculation: PASSED\n")
        return True
    except Exception as e:
        print(f"❌ V15 Indicator Calculation FAILED: {e}")
        return False
    finally:
        await exchange.close()

def test_csv_log_and_auto_learn():
    print("--- 🧪 LAB TEST 2: V15 CSV Logging & Auto-Learn ---")
    
    # 1. Create a dummy trade in V15 CSV
    sym = "TEST/USDT"
    v15_scalper.TRADES_CSV = "test_v15_trades.csv"
    if os.path.exists(v15_scalper.TRADES_CSV):
        os.remove(v15_scalper.TRADES_CSV)
        
    print("Writing dummy trade to CSV with 31 columns...")
    v15_scalper.log_trade_csv(
        symbol=sym, side="LONG", reason="TP ✅", 
        entry_px=1000, exit_px=1100, amount=100, pnl=10, pnl_pct=10.0, 
        balance=1010, entry_time=datetime.now(timezone.utc).isoformat(),
        adx=25.0, rsi=30.0, atr_pct=0.015,
        ema50_dist=-2.5, ema200_dist=-5.0, btc_corr=0.8,
        volume_ratio=2.5, bb_position=0.1, macd_hist_norm=-0.5,
        consec_candles=-3, market_regime=-1.0
    )
    
    df = pd.read_csv(v15_scalper.TRADES_CSV)
    print(f"CSV Columns written: {len(df.columns)}")
    if len(df.columns) == 31:
        print("✅ CSV Log format: PASSED")
    else:
        print("❌ CSV Log format: FAILED")
        return False
        
    # 2. Test auto-learner integration
    print("\nTesting auto_learn daemon logic on dummy trade...")
    
    auto_learn.LOCAL_CSVS = [v15_scalper.TRADES_CSV]
    auto_learn.CSV_FILES = [v15_scalper.TRADES_CSV]
    
    # Backup original DB
    db_path = "scoring_ai/vector_db.json"
    backup_path = "scoring_ai/vector_db_backup.json"
    if os.path.exists(db_path):
        import shutil
        shutil.copy(db_path, backup_path)
    
    try:
        # Load DB to get current trade count
        db = auto_learn.load_db()
        initial_trades = db['total_trades']
        
        # Run auto-learn
        auto_learn.process_new_trades()
        
        # Check if trade was added
        db2 = auto_learn.load_db()
        new_trades = db2['total_trades']
        print(f"DB Trades before: {initial_trades} | After: {new_trades}")
        
        if new_trades == initial_trades + 1:
            print("✅ Auto-Learn DB Merge: PASSED")
            
            # Check the last record
            last_record = db2['records'][-1]
            if last_record['symbol'] == "TEST/USDT":
                print("✅ Auto-Learn Record verification: PASSED")
                print(f"   Vector length: {len(last_record['vector'])}")
                print(f"   Normalized length: {len(last_record['norm_vector'])}")
                return True
            else:
                print("❌ Auto-Learn Record verification: FAILED (wrong symbol)")
                return False
        else:
            print("❌ Auto-Learn DB Merge: FAILED (trade not added)")
            return False
            
    finally:
        # Restore DB
        if os.path.exists(backup_path):
            shutil.copy(backup_path, db_path)
            os.remove(backup_path)
        if os.path.exists(v15_scalper.TRADES_CSV):
            os.remove(v15_scalper.TRADES_CSV)

if __name__ == "__main__":    
    print("====================================")
    print("V15 & SCORING AI v2 LAB TEST")
    print("====================================\n")
    
    try:
        r1 = asyncio.run(test_v15_analysis())
        r2 = test_csv_log_and_auto_learn()

        print("\n====================================")
        if r1 and r2:
            print("🚀 ALL LAB TESTS PASSED! Ready for deployment.")
        else:
            print("💥 LAB TESTS FAILED. Please review code.")
        print("====================================")
    except Exception as e:
        import traceback
        with open("lab_error.txt", "w") as f:
            f.write(traceback.format_exc())
        print(f"FATAL ERROR: {e}. Check lab_error.txt")
