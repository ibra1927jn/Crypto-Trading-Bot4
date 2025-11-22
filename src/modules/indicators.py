import pandas_ta as ta
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    def __init__(self, config):
        self.config = config if config else {}
        self.rsi_period = self.config.get('RSI', {}).get('period', 14)
        self.macd_fast = self.config.get('MACD', {}).get('fast_period', 12)
        self.macd_slow = self.config.get('MACD', {}).get('slow_period', 26)
        self.macd_signal = self.config.get('MACD', {}).get('signal_period', 9)
        self.bollinger_period = self.config.get('BOLLINGER', {}).get('period', 20)
        self.bollinger_std = self.config.get('BOLLINGER', {}).get('std_dev', 2.0)

    def calculate_all(self, df):
        if df is None or df.empty: return df
        try:
            df['rsi'] = ta.rsi(df['close'], length=self.rsi_period)
            macd = ta.macd(df['close'], fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
            if macd is not None: df = df.join(macd)
            bb = ta.bbands(df['close'], length=self.bollinger_period, std=self.bollinger_std)
            if bb is not None: df = df.join(bb)
        except Exception as e:
            logger.error(f"❌ Error calculando indicadores: {e}")
        return df

    # --- SEÑAL MACD (Ya la tenías) ---
    def get_macd_signal(self, df):
        if df is None or df.empty: return 'NEUTRAL', 0.0
        try:
            macd_col = [c for c in df.columns if c.startswith('MACD_')][0]
            signal_col = [c for c in df.columns if c.startswith('MACDs_')][0]
            curr_macd = df[macd_col].iloc[-1]
            curr_signal = df[signal_col].iloc[-1]
            prev_macd = df[macd_col].iloc[-2]
            prev_signal = df[signal_col].iloc[-2]

            if prev_macd < prev_signal and curr_macd > curr_signal: return 'BUY', 0.8
            elif prev_macd > prev_signal and curr_macd < curr_signal: return 'SELL', 0.8
            return 'NEUTRAL', 0.0
        except: return 'NEUTRAL', 0.0

    # --- SEÑAL BOLLINGER (LA QUE FALTABA) ---
    def get_bollinger_signal(self, df):
        """Estrategia de ruptura de bandas"""
        if df is None or df.empty: return 'NEUTRAL', 0.0
        try:
            latest = df.iloc[-1]
            close = latest['close']
            
            # Buscar columnas BBL (Lower) y BBU (Upper)
            bbl_cols = [c for c in df.columns if c.startswith('BBL')]
            bbu_cols = [c for c in df.columns if c.startswith('BBU')]
            
            # Si el precio rompe abajo -> Rebote (COMPRA)
            if bbl_cols and close < latest[bbl_cols[0]]:
                return 'BUY', 0.9
            
            # Si el precio rompe arriba -> Retroceso (VENTA)
            if bbu_cols and close > latest[bbu_cols[0]]:
                return 'SELL', 0.9
                
            return 'NEUTRAL', 0.0
        except Exception as e:
            logger.error(f"Error Bollinger: {e}")
            return 'NEUTRAL', 0.0

    # --- SEÑAL COMBINADA ---
    def get_combined_signal(self, df):
        if df is None or df.empty: return 'NEUTRAL', 0.0
        try:
            signals = []
            # RSI
            rsi = df['rsi'].iloc[-1]
            if rsi < 30: signals.append('BUY')
            elif rsi > 70: signals.append('SELL')
            
            # Bollinger (Reutilizamos lógica)
            bol_sig, _ = self.get_bollinger_signal(df)
            if bol_sig != 'NEUTRAL': signals.append(bol_sig)

            if not signals: return 'NEUTRAL', 0.0
            
            buy = signals.count('BUY')
            sell = signals.count('SELL')
            
            if buy > sell: return 'BUY', 0.7
            elif sell > buy: return 'SELL', 0.7
            return 'NEUTRAL', 0.0
        except: return 'NEUTRAL', 0.0

    def get_indicators_summary(self, df):
        if df is None or df.empty: return {}
        try: return {'rsi': df['rsi'].iloc[-1]}
        except: return {}