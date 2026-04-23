"""Tests para Config."""
import logging

from config import Config


class TestConfigDefaults:
    """Tests asserting default values and shapes of Config class attributes."""

    def test_exchange_default(self):
        """Default exchange is binance."""
        assert Config.EXCHANGE == "binance"

    def test_symbol_is_string(self):
        """SYMBOL is stored as a string."""
        assert isinstance(Config.SYMBOL, str)

    def test_indicators_config_has_rsi(self):
        """INDICATORS_CONFIG contains an RSI entry with a period field."""
        assert "RSI" in Config.INDICATORS_CONFIG
        assert "period" in Config.INDICATORS_CONFIG["RSI"]

    def test_indicators_config_has_macd(self):
        """INDICATORS_CONFIG contains a MACD entry."""
        assert "MACD" in Config.INDICATORS_CONFIG

    def test_indicators_config_has_bollinger(self):
        """INDICATORS_CONFIG contains a BOLLINGER entry."""
        assert "BOLLINGER" in Config.INDICATORS_CONFIG

    def test_scalping_config(self):
        """SCALPING_CONFIG exposes a check_interval field."""
        assert "check_interval" in Config.SCALPING_CONFIG

    def test_swing_config(self):
        """SWING_CONFIG exposes check_interval and ai_confidence_threshold fields."""
        assert "check_interval" in Config.SWING_CONFIG
        assert "ai_confidence_threshold" in Config.SWING_CONFIG

    def test_ai_config_keys(self):
        """AI_CONFIG exposes model_type, model_path, and device fields."""
        assert "model_type" in Config.AI_CONFIG
        assert "model_path" in Config.AI_CONFIG
        assert "device" in Config.AI_CONFIG

    def test_data_config(self):
        """DATA_CONFIG exposes a historical_bars field."""
        assert "historical_bars" in Config.DATA_CONFIG

    def test_position_size_is_float(self):
        """POSITION_SIZE is a float in the (0, 1] range."""
        assert isinstance(Config.POSITION_SIZE, float)
        assert 0 < Config.POSITION_SIZE <= 1

    def test_volatility_threshold_positive(self):
        """VOLATILITY_THRESHOLD is strictly positive."""
        assert Config.VOLATILITY_THRESHOLD > 0


class TestGetExchangeConfig:
    """Tests for Config.get_exchange_config() across testnet/production modes."""

    def test_returns_dict(self):
        """Returns a dict with apiKey, secret, and enableRateLimit fields."""
        config = Config.get_exchange_config()
        assert isinstance(config, dict)
        assert "apiKey" in config
        assert "secret" in config
        assert "enableRateLimit" in config

    def test_testnet_config(self, monkeypatch):
        """Testnet mode adds an 'options' section to the exchange config."""
        monkeypatch.setattr(Config, "TESTNET", True)
        config = Config.get_exchange_config()
        assert "options" in config

    def test_non_testnet_config(self, monkeypatch):
        """Production mode omits the 'urls' override."""
        monkeypatch.setattr(Config, "TESTNET", False)
        config = Config.get_exchange_config()
        assert "urls" not in config

    def test_testnet_binance_has_urls(self, monkeypatch):
        """Binance + testnet adds a 'urls' override pointing at the sandbox."""
        monkeypatch.setattr(Config, "TESTNET", True)
        monkeypatch.setattr(Config, "EXCHANGE", "binance")
        config = Config.get_exchange_config()
        assert "urls" in config

    def test_testnet_non_binance_no_urls(self, monkeypatch):
        """Non-binance exchanges in testnet mode do not get a 'urls' override."""
        monkeypatch.setattr(Config, "TESTNET", True)
        monkeypatch.setattr(Config, "EXCHANGE", "kraken")
        config = Config.get_exchange_config()
        assert "urls" not in config


class TestValidateConfig:
    """Tests for Config.validate_config() return value and log output."""

    def test_validate_no_credentials(self, caplog, monkeypatch):
        """Missing credentials → False plus a 'credentials not found' warning."""
        monkeypatch.setattr(Config, "API_KEY", "")
        monkeypatch.setattr(Config, "API_SECRET", "")
        with caplog.at_level(logging.WARNING, logger="config"):
            result = Config.validate_config()
        assert result is False
        assert "credentials not found" in caplog.text

    def test_validate_with_credentials_testnet(self, caplog, monkeypatch):
        """Valid credentials + testnet → True plus a 'TESTNET' info log."""
        monkeypatch.setattr(Config, "API_KEY", "test_key")
        monkeypatch.setattr(Config, "API_SECRET", "test_secret")
        monkeypatch.setattr(Config, "TESTNET", True)
        with caplog.at_level(logging.INFO, logger="config"):
            result = Config.validate_config()
        assert result is True
        assert "TESTNET" in caplog.text

    def test_validate_production_mode(self, caplog, monkeypatch):
        """Valid credentials + production → True plus a 'PRODUCTION' warning."""
        monkeypatch.setattr(Config, "API_KEY", "test_key")
        monkeypatch.setattr(Config, "API_SECRET", "test_secret")
        monkeypatch.setattr(Config, "TESTNET", False)
        with caplog.at_level(logging.WARNING, logger="config"):
            result = Config.validate_config()
        assert result is True
        assert "PRODUCTION" in caplog.text


class TestPrintConfig:
    """Tests for Config.print_config()'s logged output."""

    def test_print_config_output(self, caplog):
        """Printed output includes the banner plus current EXCHANGE and SYMBOL."""
        with caplog.at_level(logging.INFO, logger="config"):
            Config.print_config()
        assert "CRYPTO TRADING BOT" in caplog.text
        assert Config.EXCHANGE in caplog.text
        assert Config.SYMBOL in caplog.text
