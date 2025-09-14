"""
Настройки торгового бота
Конфигурация для всех компонентов (БЕЗ Pydantic)
"""

import os
from dataclasses import dataclass
from typing import Optional


def get_env_bool(key: str, default: bool = False) -> bool:
    """Получить boolean значение из переменной окружения"""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on')


def get_env_int(key: str, default: int = 0) -> int:
    """Получить int значение из переменной окружения"""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """Получить float значение из переменной окружения"""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """Настройки приложения (БЕЗ Pydantic)"""
    
    def __init__(self):
        """Инициализация настроек из переменных окружения"""
        
        # Основные настройки
        self.APP_NAME: str = "Bybit Trading Bot"
        self.APP_VERSION: str = "1.0.0"
        self.DEBUG: bool = get_env_bool("DEBUG", False)
        
        # Настройки торговли
        self.TRADING_PAIR: str = os.getenv("TRADING_PAIR", "BTCUSDT")
        self.STRATEGY_TIMEFRAME: str = os.getenv("STRATEGY_TIMEFRAME", "5m")
        
        # Bybit WebSocket настройки
        self.BYBIT_WS_TESTNET: bool = get_env_bool("BYBIT_WS_TESTNET", True)
        self.BYBIT_WS_LINEAR_URL: str = os.getenv(
            "BYBIT_WS_LINEAR_URL", 
            "wss://stream-testnet.bybit.com/v5/public/linear"
        )
        self.BYBIT_WS_MAINNET_URL: str = "wss://stream.bybit.com/v5/public/linear"
        
        # Настройки стратегии RSI + MA
        self.RSI_PERIOD: int = get_env_int("RSI_PERIOD", 14)
        self.RSI_OVERSOLD: float = get_env_float("RSI_OVERSOLD", 30.0)
        self.RSI_OVERBOUGHT: float = get_env_float("RSI_OVERBOUGHT", 70.0)
        
        self.MA_SHORT_PERIOD: int = get_env_int("MA_SHORT_PERIOD", 9)
        self.MA_LONG_PERIOD: int = get_env_int("MA_LONG_PERIOD", 21)
        
        # Минимальная уверенность для сигнала (0.0 - 1.0)
        self.MIN_SIGNAL_CONFIDENCE: float = get_env_float("MIN_SIGNAL_CONFIDENCE", 0.7)
        
        # Telegram настройки
        self.TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")
        
        # Настройки логирования
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
        
        # Настройки WebSocket
        self.WS_PING_INTERVAL: int = get_env_int("WS_PING_INTERVAL", 20)
        self.WS_RECONNECT_ATTEMPTS: int = get_env_int("WS_RECONNECT_ATTEMPTS", 5)
        self.WS_RECONNECT_DELAY: int = get_env_int("WS_RECONNECT_DELAY", 5)
        
        # Настройки данных
        self.KLINE_LIMIT: int = get_env_int("KLINE_LIMIT", 100)
        self.DATA_RETENTION_HOURS: int = get_env_int("DATA_RETENTION_HOURS", 24)
        
        # Настройки уведомлений
        self.NOTIFY_ALL_SIGNALS: bool = get_env_bool("NOTIFY_ALL_SIGNALS", True)
        self.NOTIFY_HIGH_CONFIDENCE_ONLY: bool = get_env_bool("NOTIFY_HIGH_CONFIDENCE_ONLY", False)
        
        # Настройки безопасности
        self.MAX_DAILY_SIGNALS: int = get_env_int("MAX_DAILY_SIGNALS", 100)
        self.SIGNAL_COOLDOWN_MINUTES: int = get_env_int("SIGNAL_COOLDOWN_MINUTES", 5)
    
    @property
    def websocket_url(self) -> str:
        """Возвращает URL WebSocket в зависимости от режима"""
        if self.BYBIT_WS_TESTNET:
            return "wss://stream-testnet.bybit.com/v5/public/linear"
        return self.BYBIT_WS_MAINNET_URL
    
    @property
    def is_production(self) -> bool:
        """Проверяет, запущен ли бот в продакшене"""
        return not self.BYBIT_WS_TESTNET
    
    def get_kline_subscription(self) -> str:
        """Возвращает строку подписки на kline данные"""
        return f"kline.{self.STRATEGY_TIMEFRAME}.{self.TRADING_PAIR}"
    
    def get_ticker_subscription(self) -> str:
        """Возвращает строку подписки на ticker данные"""
        return f"tickers.{self.TRADING_PAIR}"
    
    def get_orderbook_subscription(self) -> str:
        """Возвращает строку подписки на orderbook данные"""
        return f"orderbook.50.{self.TRADING_PAIR}"


# Глобальный экземпляр настроек
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Получить экземпляр настроек (синглтон)"""
    global _settings
    
    if _settings is None:
        # Загружаем .env файл если есть
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass  # dotenv не обязательный
        
        _settings = Settings()
        
        # Логирование загруженных настроек
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔧 Настройки загружены (БЕЗ Pydantic):")
        logger.info(f"   Торговая пара: {_settings.TRADING_PAIR}")
        logger.info(f"   Таймфрейм: {_settings.STRATEGY_TIMEFRAME}")
        logger.info(f"   Режим: {'TESTNET' if _settings.BYBIT_WS_TESTNET else 'MAINNET'}")
        logger.info(f"   WebSocket URL: {_settings.websocket_url}")
        logger.info(f"   Telegram: {'Включен' if _settings.TELEGRAM_BOT_TOKEN else 'Отключен'}")
        logger.info(f"   RSI период: {_settings.RSI_PERIOD}")
        logger.info(f"   MA периоды: {_settings.MA_SHORT_PERIOD}/{_settings.MA_LONG_PERIOD}")
        
    return _settings


def validate_settings(settings: Settings) -> bool:
    """Валидация настроек"""
    errors = []
    
    # Проверка торговой пары
    if not settings.TRADING_PAIR or len(settings.TRADING_PAIR) < 3:
        errors.append("Неверная торговая пара")
    
    # Проверка таймфрейма
    valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
    if settings.STRATEGY_TIMEFRAME not in valid_timeframes:
        errors.append(f"Неверный таймфрейм. Доступные: {valid_timeframes}")
    
    # Проверка RSI настроек
    if not (5 <= settings.RSI_PERIOD <= 50):
        errors.append("RSI период должен быть между 5 и 50")
    
    if not (10 <= settings.RSI_OVERSOLD <= 40):
        errors.append("RSI oversold должен быть между 10 и 40")
    
    if not (60 <= settings.RSI_OVERBOUGHT <= 90):
        errors.append("RSI overbought должен быть между 60 и 90")
    
    if settings.RSI_OVERSOLD >= settings.RSI_OVERBOUGHT:
        errors.append("RSI oversold должен быть меньше overbought")
    
    # Проверка MA настроек
    if settings.MA_SHORT_PERIOD >= settings.MA_LONG_PERIOD:
        errors.append("Короткая MA должна быть меньше длинной MA")
    
    # Проверка уверенности сигнала
    if not (0.0 <= settings.MIN_SIGNAL_CONFIDENCE <= 1.0):
        errors.append("Минимальная уверенность должна быть между 0.0 и 1.0")
    
    # Проверка Telegram настроек
    if settings.TELEGRAM_BOT_TOKEN and not settings.TELEGRAM_CHAT_ID:
        errors.append("Если указан Telegram token, нужно указать chat_id")
    
    if errors:
        import logging
        logger = logging.getLogger(__name__)
        logger.error("❌ Ошибки в настройках:")
        for error in errors:
            logger.error(f"   - {error}")
        return False
    
    return True


def get_env_example() -> str:
    """Возвращает пример .env файла"""
    return """# Основные настройки
DEBUG=false
TRADING_PAIR=BTCUSDT
STRATEGY_TIMEFRAME=5m

# Bybit настройки
BYBIT_WS_TESTNET=true

# Стратегия настройки
RSI_PERIOD=14
RSI_OVERSOLD=30.0
RSI_OVERBOUGHT=70.0
MA_SHORT_PERIOD=9
MA_LONG_PERIOD=21
MIN_SIGNAL_CONFIDENCE=0.7

# Telegram настройки
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Дополнительные настройки
LOG_LEVEL=INFO
WS_PING_INTERVAL=20
KLINE_LIMIT=100
MAX_DAILY_SIGNALS=100
SIGNAL_COOLDOWN_MINUTES=5
"""
