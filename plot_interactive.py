import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import os

df = pd.read_csv('v15_remote_trades_full.csv')
df['close_time'] = pd.to_datetime(df['close_time'])
df = df.sort_values('close_time')

start_bal = df.iloc[0]['balance'] if len(df) > 0 else 0
end_bal = df.iloc[-1]['balance'] if len(df) > 0 else 0

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=df['close_time'],
    y=df['balance'],
    mode='lines+markers',
    name='Balance (USDT)',
    line=dict(color='#00ffcc', width=2),
    fill='tozeroy',
    fillcolor='rgba(0, 255, 204, 0.1)'
))

fig.update_layout(
    title=f'V15 Scalper - Live Performance Fluctuation<br>Start: ${start_bal:.2f} | Current: ${end_bal:.2f}',
    xaxis_title='Time',
    yaxis_title='Balance (USDT)',
    template='plotly_dark',
    hovermode='x unified',
    margin=dict(l=40, r=40, t=60, b=40)
)

out_file = os.path.join(os.getcwd(), 'v15_chart.html')
fig.write_html(out_file)
print(f"Interactive chart saved to {out_file}")
