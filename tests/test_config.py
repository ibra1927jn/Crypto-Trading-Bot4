"""Tests para Config."""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from config import Config


class TestConfigDefaults:
    def test_exchange_default(self):
        assert Config.EXCHANGE == "binance"

    def test_symbol_is_string(self):
        assert isinstance(Config.SYMBOL, str)

    def test_indicators_config_has_rsi(self):
        assert 'RSI' in Config.INDICATORS_CONFIG
        assert 'period' in Config.INDICATORS_CONFIG['RSI']

    def test_indicators_config_has_macd(self):
        assert 'MACD' in Config.INDICATORS_CONFIG

    def test_indicators_config_has_bollinger(self):
        assert 'BOLLINGER' in Config.INDICATORS_CONFIG

    def test_scalping_config(self):
        assert 'check_interval' in Config.SCALPING_CONFIG

    def test_swing_config(self):
        assert 'check_interval' in Config.SWING_CONFIG
        assert 'ai_confidence_threshold' in Config.SWING_CONFIG

    def test_ai_config_keys(self):
        assert 'model_type' in Config.AI_CONFIG
        assert 'model_path' in Config.AI_CONFIG
        assert 'device' in Config.AI_CONFIG

    def test_data_config(self):
        assert 'historical_bars' in Config.DATA_CONFIG

    def test_position_size_is_float(self):
        assert isinstance(Config.POSITION_SIZE, float)
        assert 0 < Config.POSITION_SIZE <= 1

    def test_volatility_threshold_positive(self):
        assert Config.VOLATILITY_THRESHOLD > 0


class TestGetExchangeConfig:
    def test_returns_dict(self):
        config = Config.get_exchange_config()
        assert isinstance(config, dict)
        assert 'apiKey' in config
        assert 'secret' in config
        assert 'enableRateLimit' in config

    def test_testnet_config(self):
        original = Config.TESTNET
        Config.TESTNET = True
        config = Config.get_exchange_config()
        assert 'options' in config
        Config.TESTNET = original
