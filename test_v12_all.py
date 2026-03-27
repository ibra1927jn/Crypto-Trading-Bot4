"""
V12.1 Comprehensive Test — Upload test to server and run it remotely.
"""
import paramiko
import os

HOST = "95.217.158.7"
USER = "root"
PASS = "tji3MtHJa9J4"

# The test script that will be uploaded to /opt/ct4/test_v12_suite.py
TEST_CODE = '''#!/usr/bin/env python3
"""V12.1 Test Suite — runs directly on server importing actual bot functions."""
import sys, os, json, time

# Suppress aiohttp import and telegram
os.environ['TG_BOT_TOKEN'] = ''
os.environ['TG_CHAT_ID'] = ''

sys.path.insert(0, '/opt/ct4')

# Read and exec everything before main_loop to get all functions/constants
with open('/opt/ct4/v12_shadow_bot.py', 'r') as f:
    source = f.read()
code_before_main = source.split('async def main_loop')[0]
exec(compile(code_before_main, 'v12_shadow_bot.py', 'exec'), globals())

results = []
passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        results.append(("PASS", name, ""))
    else:
        failed += 1
        results.append(("FAIL", name, str(detail)))

# ============================================================
# PHASE 0: OPERATIONAL HARDENING
# ============================================================

# Kill Switch: daily loss > 5%
from datetime import datetime, timezone, timedelta
today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
st = dict(DEFAULT_STATE)
st['balance'] = 940.0
st['daily_start_balance'] = 1000.0
st['daily_start_date'] = today   # use today so no reset
st['kill_switch'] = False
st['peak_balance'] = 1000.0
killed, reason = check_kill_switch(st)
test("P0: Kill switch daily -6% triggers", killed)

st2 = dict(DEFAULT_STATE)
st2['balance'] = 970.0
st2['daily_start_balance'] = 1000.0
st2['daily_start_date'] = today
st2['kill_switch'] = False
st2['peak_balance'] = 1000.0
k2, _ = check_kill_switch(st2)
test("P0: Kill switch daily -3% safe", not k2)

st3 = dict(DEFAULT_STATE)
st3['balance'] = 840.0
st3['peak_balance'] = 1000.0
st3['daily_start_balance'] = 840.0
st3['daily_start_date'] = today
st3['kill_switch'] = False
k3, r3 = check_kill_switch(st3)
test("P0: Kill switch DD -16% triggers", k3)

# SL Ban
st_ban = dict(DEFAULT_STATE)
st_ban['sl_bans'] = {}
add_sl_ban(st_ban, 'SOL/USDT')
test("P0: SL ban applied", is_banned(st_ban, 'SOL/USDT'))
test("P0: Other coin not banned", not is_banned(st_ban, 'BTC/USDT'))

# Position Timeout
old_pos = {
    'entry_price': 100.0,
    'entry_time': (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
    'side': 'LONG', 'qty': 1.0, 'amount': 100.0,
}
should_to, _ = check_timeout(old_pos, 'TEST', 100.2)
test("P0: Timeout 30h triggers", should_to)

fresh_pos = {
    'entry_price': 100.0,
    'entry_time': datetime.now(timezone.utc).isoformat(),
    'side': 'LONG', 'qty': 1.0, 'amount': 100.0,
}
should_no, _ = check_timeout(fresh_pos, 'TEST2', 100.0)
test("P0: Fresh position safe", not should_no)

# Dynamic Position Sizing
# With $1000 equity, 2% risk = $20 risk, SL 3% -> raw size = $667
# BUT 25% cap kicks in: max $250. Test the cap works.
amt, qty = calculate_position_size(1000.0, 100.0, 97.0, 'LONG', risk_pct=0.02)
test("P0: Sizing LONG capped at $250", 249 < amt < 251, f"amt={amt:.2f}")

amt2, _ = calculate_position_size(1000.0, 100.0, 99.5, 'LONG', risk_pct=0.02)
test("P0: Sizing tight SL also capped", amt2 <= 250.01, f"amt={amt2:.2f}")

amt3, _ = calculate_position_size(1000.0, 100.0, 103.0, 'SHORT', risk_pct=0.02)
test("P0: Sizing SHORT capped at $250", 249 < amt3 < 251, f"amt={amt3:.2f}")

# Verify uncapped: $10k equity, 10% SL -> raw=$2000, cap=$2500 -> no cap
amt4, _ = calculate_position_size(10000.0, 100.0, 90.0, 'LONG', risk_pct=0.02)
test("P0: Sizing uncapped raw calc $2000", 1900 < amt4 < 2100, f"amt={amt4:.2f}")

test("P0: Volume threshold $1M", MIN_VOLUME_24H == 1_000_000)

# ============================================================
# PHASE 1: FUNDING RATE DETECTOR
# ============================================================

fr = FundingRateCache()
ok = fr.refresh()
test("P1: FR Cache refresh OK", ok)
test("P1: FR Cache 500+ pairs", len(fr._cache) > 500, f"n={len(fr._cache)}")

rate_btc, st_btc = fr.get_rate('BTC/USDT')
test("P1: BTC FR found", rate_btc is not None)

rate_pepe, st_pepe = fr.get_rate('PEPE/USDT')
test("P1: PEPE mapped correctly", rate_pepe is not None, f"status={st_pepe}")

# Simulate veto conditions
fr._cache['HIGH/USDT:USDT'] = 0.001   # +0.10%
_, s1 = fr.get_rate('HIGH/USDT')
test("P1: FR +0.10% = VETO-L", 'VETO-L' in s1, f"got {s1}")

fr._cache['LOW/USDT:USDT'] = -0.001   # -0.10%
_, s2 = fr.get_rate('LOW/USDT')
test("P1: FR -0.10% = VETO-S", 'VETO-S' in s2, f"got {s2}")

fr._cache['HOT/USDT:USDT'] = 0.0004   # +0.04% hot
_, s3 = fr.get_rate('HOT/USDT')
test("P1: FR +0.04% = HOT", 'HOT' in s3, f"got {s3}")

fr._cache['OK/USDT:USDT'] = 0.0001    # +0.01% normal
_, s4 = fr.get_rate('OK/USDT')
test("P1: FR +0.01% = normal", 'VETO' not in s4 and 'HOT' not in s4, f"got {s4}")

top = fr.get_top_radioactive(3)
test("P1: Top 3 radioactive", len(top) == 3)
test("P1: Sorted by abs(FR)", abs(top[0][1]) >= abs(top[1][1]))

# ============================================================
# PHASE 2: MULTI-TF (function existence check)
# ============================================================
test("P2: sniper_15m_check exists", 'sniper_15m_check' in dir() or 'sniper_15m_check' in globals())

# ============================================================
# PHASE 3: KELLY + SECTOR
# ============================================================

# Kelly: baseline (< 10 trades)
st_k = dict(DEFAULT_STATE)
st_k['trade_history'] = [{'pnl_pct': 2.0, 'side': 'LONG', 'symbol': 'X'}] * 5
risk, desc = compute_kelly_risk(st_k)
test("P3: Kelly baseline <10 trades", risk == 0.02, f"risk={risk}")

# Kelly: winning history (70% WR, R=2.0)
st_k2 = dict(DEFAULT_STATE)
st_k2['trade_history'] = (
    [{'pnl_pct': 3.0, 'side': 'LONG', 'symbol': 'X'}] * 7 +
    [{'pnl_pct': -1.5, 'side': 'LONG', 'symbol': 'Y'}] * 3
)
risk2, desc2 = compute_kelly_risk(st_k2)
test("P3: Kelly winning -> rises", risk2 > 0.02, f"risk={risk2:.4f}")
test("P3: Kelly max 4%", risk2 <= 0.04, f"risk={risk2:.4f}")

# Kelly: losing history (30% WR)
st_k3 = dict(DEFAULT_STATE)
st_k3['trade_history'] = (
    [{'pnl_pct': 1.0, 'side': 'LONG', 'symbol': 'X'}] * 3 +
    [{'pnl_pct': -2.0, 'side': 'LONG', 'symbol': 'Y'}] * 7
)
risk3, desc3 = compute_kelly_risk(st_k3)
test("P3: Kelly losing -> drops to 1%", risk3 == 0.01, f"risk={risk3:.4f}")

# Sector guard
st_sec = dict(DEFAULT_STATE)
st_sec['positions'] = {'ETH/USDT': {'side': 'LONG'}, 'SOL/USDT': {'side': 'LONG'}}
test("P3: L1 full (ETH+SOL) blocks AVAX", not sector_slots_available(st_sec, 'AVAX/USDT'))
test("P3: Meme sector open", sector_slots_available(st_sec, 'DOGE/USDT'))
test("P3: BTC sector open", sector_slots_available(st_sec, 'BTC/USDT'))
test("P3: DeFi sector open", sector_slots_available(st_sec, 'LINK/USDT'))

st_sec2 = dict(DEFAULT_STATE)
st_sec2['positions'] = {'ETH/USDT': {'side': 'LONG'}}
test("P3: 1 L1 allows another", sector_slots_available(st_sec2, 'SOL/USDT'))

# Sector map complete
for sym in ['BTC/USDT','ETH/USDT','SOL/USDT','LINK/USDT','INJ/USDT',
            'AVAX/USDT','NEAR/USDT','PEPE/USDT','WIF/USDT','DOGE/USDT']:
    test(f"P3: {sym} in SECTOR_MAP", sym in SECTOR_MAP)

# Trade history cap
st_h = dict(DEFAULT_STATE)
st_h['trade_history'] = [{'pnl_pct': 1.0, 'side': 'L', 'symbol': 'X'}] * 55
if len(st_h['trade_history']) > TRADE_HISTORY_CAP:
    st_h['trade_history'] = st_h['trade_history'][-TRADE_HISTORY_CAP:]
test("P3: History capped at 50", len(st_h['trade_history']) == 50)

# ============================================================
# SIMULATION: Full trade lifecycle
# ============================================================

sim = dict(DEFAULT_STATE)
sim['balance'] = 1000.0
sim['trade_history'] = []

risk_pct, _ = compute_kelly_risk(sim)
amt, qty = calculate_position_size(sim['balance'], 100.0, 97.0, 'LONG', risk_pct=risk_pct)
sim['positions'] = {'SIM/USDT': {
    'side': 'LONG', 'entry_price': 100.0, 'qty': qty, 'amount': amt,
    'sl': 97.0, 'initial_sl': 97.0, 'tp': 106.0, 'trail_stage': 0,
    'entry_time': datetime.now(timezone.utc).isoformat(),
}}
sim['balance'] -= amt

test("SIM: Position opened", 'SIM/USDT' in sim['positions'])
test("SIM: Balance decreased", sim['balance'] < 1000.0, f"bal={sim['balance']:.2f}")

pos = sim['positions']['SIM/USDT']
new_sl, msg = manage_trailing_stop_v12(pos, 103.0)
test("SIM: Trail at 1R moves SL up", new_sl > 97.0, f"sl={new_sl:.4f}")

new_sl2, msg2 = manage_trailing_stop_v12(pos, 106.0)
test("SIM: Trail at 2R locks +1R", new_sl2 > 100.0, f"sl={new_sl2:.4f}")

# ============================================================
# REPORT
# ============================================================
print()
print("=" * 60)
print(f"V12.1 TEST RESULTS: {passed} PASSED / {failed} FAILED / {passed+failed} TOTAL")
print("=" * 60)
for status, name, detail in results:
    marker = "OK" if status == "PASS" else "XX"
    line = f"  [{marker}] {name}"
    if detail:
        line += f" ({detail})"
    print(line)
print("=" * 60)
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print(f"WARNING: {failed} TESTS FAILED")
'''

# Upload and execute
print("Uploading test suite to Hetzner...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

# Upload via SFTP
sftp = ssh.open_sftp()
with sftp.file('/opt/ct4/test_v12_suite.py', 'w') as f:
    f.write(TEST_CODE)
sftp.close()

print("Running test suite...\n")
_, out, err = ssh.exec_command(
    'cd /opt/ct4 && /opt/ct4/venv/bin/python3 test_v12_suite.py',
    timeout=120
)
result = out.read().decode("utf-8", errors="replace")
errors = err.read().decode("utf-8", errors="replace")
ssh.close()

# Save results
with open("v12_test_results.txt", "w", encoding="utf-8") as f:
    f.write(result)
    if errors:
        f.write("\n=== STDERR ===\n" + errors)

print(result)
if "FAIL" in result or (errors and "Error" in errors):
    if errors:
        print("\n=== ERRORS ===")
        # Print last 1000 chars of errors
        print(errors[-1000:])
