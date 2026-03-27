import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

df = pd.read_csv('v15_remote_trades_full.csv')
df['close_time'] = pd.to_datetime(df['close_time'])
df = df.sort_values('close_time')

plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(12, 6))

ax.plot(df['close_time'], df['balance'], color='#00ffcc', linewidth=2, label='Account Balance (USDT)')
ax.fill_between(df['close_time'], df['balance'], df['balance'].min() * 0.95, color='#00ffcc', alpha=0.1)

max_bal = df['balance'].max()
min_bal = df['balance'].min()
start_bal = df.iloc[0]['balance'] if len(df) > 0 else 0
end_bal = df.iloc[-1]['balance'] if len(df) > 0 else 0

ax.scatter(df.iloc[0]['close_time'], start_bal, color='white', zorder=5)
ax.scatter(df.iloc[-1]['close_time'], end_bal, color='white', zorder=5)

ax.annotate(f'Start: ${start_bal:.2f}', xy=(df.iloc[0]['close_time'], start_bal), xytext=(10, 10), textcoords='offset points', color='white')
ax.annotate(f'Current: ${end_bal:.2f}', xy=(df.iloc[-1]['close_time'], end_bal), xytext=(-10, -15), textcoords='offset points', ha='right', color='white')

ax.set_title('V15 Scalper - Live Performance Fluctuation', fontsize=16, pad=20, color='white')
ax.set_xlabel('Time', fontsize=12, color='gray')
ax.set_ylabel('Balance (USDT)', fontsize=12, color='gray')
ax.grid(True, linestyle='--', alpha=0.2, color='gray')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.spines['left'].set_color('gray')
ax.spines['bottom'].set_color('gray')
plt.tight_layout()

out_path = r'C:\\Users\\ibrab\\.gemini\\antigravity\\brain\\ed4acef7-bdd9-4922-aeb6-86c55843ad60\\v15_performance_chart.png'
plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), edgecolor='none')
print(f"Chart saved to {out_path}")
