"""Tests para Config."""
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

    def test_non_testnet_config(self):
        original = Config.TESTNET
        Config.TESTNET = False
        config = Config.get_exchange_config()
        assert 'urls' not in config
        Config.TESTNET = original

    def test_testnet_binance_has_urls(self):
        original_testnet = Config.TESTNET
        original_exchange = Config.EXCHANGE
        Config.TESTNET = True
        Config.EXCHANGE = 'binance'
        config = Config.get_exchange_config()
        assert 'urls' in config
        Config.TESTNET = original_testnet
        Config.EXCHANGE = original_exchange

    def test_testnet_non_binance_no_urls(self):
        original_testnet = Config.TESTNET
        original_exchange = Config.EXCHANGE
        Config.TESTNET = True
        Config.EXCHANGE = 'kraken'
        config = Config.get_exchange_config()
        assert 'urls' not in config
        Config.TESTNET = original_testnet
        Config.EXCHANGE = original_exchange


class TestValidateConfig:
    def test_validate_no_credentials(self, capsys):
        original_key = Config.API_KEY
        original_secret = Config.API_SECRET
        Config.API_KEY = ""
        Config.API_SECRET = ""
        result = Config.validate_config()
        assert result is False
        output = capsys.readouterr().out
        assert "WARNING" in output
        Config.API_KEY = original_key
        Config.API_SECRET = original_secret

    def test_validate_with_credentials_testnet(self, capsys):
        original_key = Config.API_KEY
        original_secret = Config.API_SECRET
        original_testnet = Config.TESTNET
        Config.API_KEY = "test_key"
        Config.API_SECRET = "test_secret"
        Config.TESTNET = True
        result = Config.validate_config()
        assert result is True
        output = capsys.readouterr().out
        assert "TESTNET" in output
        Config.API_KEY = original_key
        Config.API_SECRET = original_secret
        Config.TESTNET = original_testnet

    def test_validate_production_mode(self, capsys):
        original_key = Config.API_KEY
        original_secret = Config.API_SECRET
        original_testnet = Config.TESTNET
        Config.API_KEY = "test_key"
        Config.API_SECRET = "test_secret"
        Config.TESTNET = False
        result = Config.validate_config()
        assert result is True
        output = capsys.readouterr().out
        assert "PRODUCTION" in output
        Config.API_KEY = original_key
        Config.API_SECRET = original_secret
        Config.TESTNET = original_testnet


class TestPrintConfig:
    def test_print_config_output(self, capsys):
        Config.print_config()
        output = capsys.readouterr().out
        assert "CRYPTO TRADING BOT" in output
        assert Config.EXCHANGE in output
        assert Config.SYMBOL in output
