import pandas as pd
import numpy as np

def find_swing_levels(df: pd.DataFrame, order: int = 5):
    """
    Finds structural Swing Highs and Swing Lows in a DataFrame.
    """
    # Find local maxima (Swing Highs)
    df['is_high'] = df['high'] == df['high'].rolling(window=2*order+1, center=True).max()
    swing_highs = df[df['is_high']]['high'].dropna().tolist()
    
    # Find local minima (Swing Lows)
    df['is_low'] = df['low'] == df['low'].rolling(window=2*order+1, center=True).min()
    swing_lows = df[df['is_low']]['low'].dropna().tolist()
    
    # Return them reversed so the most recent ones are first
    return swing_highs[::-1], swing_lows[::-1]

def calculate_structural_rr(entry_price: float, side: str, swing_highs: list, swing_lows: list, atr: float = 0):
    """
    Calculates the Take Profit (TP), Stop Loss (SL) and Risk/Reward based on market structure.
    :param atr: Average True Range to serve as the padding shield against Stop Hunts.
    """
    if not swing_highs or not swing_lows:
        return {'approved': False, 'rr': 0, 'reason': 'No swing levels found'}

    tp_price = 0
    sl_price = 0

    if side == 'long':
        # SL should be below the most recent swing low that is BELOW our entry minus ATR padding
        valid_lows = [l for l in swing_lows if l < entry_price]
        if not valid_lows: return {'approved': False, 'rr': 0, 'reason': 'No clear Swing Low below entry'}
        
        sl_price = valid_lows[0] - (atr if atr > 0 else (entry_price * 0.005))
        risk = entry_price - sl_price

        # TP should be at the next major swing high ABOVE our entry
        valid_highs = [h for h in swing_highs if h > entry_price]
        if not valid_highs: 
            # Price Discovery (Cielo Abierto): Default to 1:2 R/R based on risk
            tp_price = entry_price + (risk * 2)
        else:
            # We want to pull TP slightly back from the absolute peak to ensure fill (buffer)
            tp_price = valid_highs[0] - (atr * 0.2 if atr > 0 else 0)
            
        reward = tp_price - entry_price

    else: # short
        # SL should be above the most recent swing high that is ABOVE our entry plus ATR padding
        valid_highs = [h for h in swing_highs if h > entry_price]
        if not valid_highs: return {'approved': False, 'rr': 0, 'reason': 'No clear Swing High above entry'}
        
        sl_price = valid_highs[0] + (atr if atr > 0 else (entry_price * 0.005))
        risk = sl_price - entry_price

        # TP should be at the next major swing low BELOW our entry
        valid_lows = [l for l in swing_lows if l < entry_price]
        if not valid_lows:
            # Price Discovery (Abismo): Default to 1:2 R/R based on risk
            tp_price = entry_price - (risk * 2)
        else:
            tp_price = valid_lows[0] + (atr * 0.2 if atr > 0 else 0)
            
        reward = entry_price - tp_price

    # Protect against divisions by zero
    if risk <= 0: return {'approved': False, 'rr': 0, 'reason': 'Risk is 0 or negative'}
    
    rr = reward / risk
    approved = rr >= 1.5

    return {
        'approved': approved,
        'rr': round(rr, 2),
        'tp_price': tp_price,
        'sl_price': sl_price,
        'risk_pct': round((risk / entry_price) * 100, 2),
        'reward_pct': round((reward / entry_price) * 100, 2),
        'reason': 'Optimal structural setup' if approved else 'R/R below 1.5 threshold'
    }
