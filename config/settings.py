"""
Настройки торгового бота
Конфигурация для всех компонентов (БЕЗ Pydantic)
Обновлено: добавлены настройки OpenAI для ИИ-анализа
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
        
        # OpenAI настройки для ИИ-анализа
        self.OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
        self.OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")
        self.OPENAI_MAX_TOKENS: int = get_env_int("OPENAI_MAX_TOKENS", 2000)
        self.OPENAI_TEMPERATURE: float = get_env_float("OPENAI_TEMPERATURE", 0.3)
        self.OPENAI_TIMEOUT: int = get_env_int("OPENAI_TIMEOUT", 60)  # Таймаут в секундах
        
        # Настройки ИИ-анализа
        self.AI_ANALYSIS_ENABLED: bool = get_env_bool("AI_ANALYSIS_ENABLED", True)
        self.AI_KLINES_COUNT: int = get_env_int("AI_KLINES_COUNT", 50)  # Количество свечей для анализа
        self.AI_ORDERBOOK_LEVELS: int = get_env_int("AI_ORDERBOOK_LEVELS", 10)  # Уровней ордербука
        self.AI_TRADES_COUNT: int = get_env_int("AI_TRADES_COUNT", 100)  # Количество сделок для анализа
        
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
        self.NOTIFY_AI_ANALYSIS: bool = get_env_bool("NOTIFY_AI_ANALYSIS", True)
        
        # Настройки безопасности
        self.MAX_DAILY_SIGNALS: int = get_env_int("MAX_DAILY_SIGNALS", 100)
        self.SIGNAL_COOLDOWN_MINUTES: int = get_env_int("SIGNAL_COOLDOWN_MINUTES", 5)
        self.AI_ANALYSIS_COOLDOWN_MINUTES: int = get_env_int("AI_ANALYSIS_COOLDOWN_MINUTES", 0)  # Без ограничений по умолчанию
        
        # Настройки производительности
        self.MAX_CONCURRENT_AI_REQUESTS: int = get_env_int("MAX_CONCURRENT_AI_REQUESTS", 3)
        self.AI_RETRY_ATTEMPTS: int = get_env_int("AI_RETRY_ATTEMPTS", 2)
        self.AI_RETRY_DELAY: int = get_env_int("AI_RETRY_DELAY", 5)  # Секунды между попытками
    
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
    
    @property
    def is_openai_configured(self) -> bool:
        """Проверяет, настроен ли OpenAI"""
        return bool(self.OPENAI_API_KEY and len(self.OPENAI_API_KEY.strip()) > 10)
    
    @property
    def is_telegram_configured(self) -> bool:
        """Проверяет, настроен ли Telegram"""
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)
    
    @property
    def openai_config(self) -> dict:
        """Возвращает конфигурацию OpenAI"""
        return {
            "api_key": self.OPENAI_API_KEY,
            "model": self.OPENAI_MODEL,
            "max_tokens": self.OPENAI_MAX_TOKENS,
            "temperature": self.OPENAI_TEMPERATURE,
            "timeout": self.OPENAI_TIMEOUT
        }
    
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
        logger.info(f"   Telegram: {'Включен' if _settings.is_telegram_configured else 'Отключен'}")
        logger.info(f"   OpenAI: {'Включен' if _settings.is_openai_configured else 'Отключен'}")
        logger.info(f"   OpenAI модель: {_settings.OPENAI_MODEL}")
        logger.info(f"   ИИ-анализ: {'Включен' if _settings.AI_ANALYSIS_ENABLED else 'Отключен'}")
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
    
    # Проверка OpenAI настроек
    if settings.AI_ANALYSIS_ENABLED and not settings.is_openai_configured:
        errors.append("ИИ-анализ включен, но OPENAI_API_KEY не настроен")
    
    if settings.OPENAI_API_KEY and len(settings.OPENAI_API_KEY.strip()) < 10:
        errors.append("OPENAI_API_KEY слишком короткий (должен быть > 10 символов)")
    
    # Проверка модели OpenAI
    valid_models = ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini"]
    if settings.OPENAI_MODEL not in valid_models:
        errors.append(f"Неверная модель OpenAI. Доступные: {valid_models}")
    
    # Проверка параметров OpenAI
    if not (100 <= settings.OPENAI_MAX_TOKENS <= 4000):
        errors.append("OPENAI_MAX_TOKENS должен быть между 100 и 4000")
    
    if not (0.0 <= settings.OPENAI_TEMPERATURE <= 2.0):
        errors.append("OPENAI_TEMPERATURE должен быть между 0.0 и 2.0")
    
    if not (10 <= settings.OPENAI_TIMEOUT <= 300):
        errors.append("OPENAI_TIMEOUT должен быть между 10 и 300 секунд")
    
    # Проверка параметров ИИ-анализа
    if not (10 <= settings.AI_KLINES_COUNT <= 200):
        errors.append("AI_KLINES_COUNT должен быть между 10 и 200")
    
    if not (5 <= settings.AI_ORDERBOOK_LEVELS <= 50):
        errors.append("AI_ORDERBOOK_LEVELS должен быть между 5 и 50")
    
    if not (50 <= settings.AI_TRADES_COUNT <= 1000):
        errors.append("AI_TRADES_COUNT должен быть между 50 и 1000")
    
    # Проверка производительности
    if not (1 <= settings.MAX_CONCURRENT_AI_REQUESTS <= 10):
        errors.append("MAX_CONCURRENT_AI_REQUESTS должен быть между 1 и 10")
    
    if not (0 <= settings.AI_RETRY_ATTEMPTS <= 5):
        errors.append("AI_RETRY_ATTEMPTS должен быть между 0 и 5")
    
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

# OpenAI настройки для ИИ-анализа
OPENAI_API_KEY=sk-your_openai_api_key_here
OPENAI_MODEL=gpt-4
OPENAI_MAX_TOKENS=2000
OPENAI_TEMPERATURE=0.3
OPENAI_TIMEOUT=60

# ИИ-анализ настройки
AI_ANALYSIS_ENABLED=true
AI_KLINES_COUNT=50
AI_ORDERBOOK_LEVELS=10
AI_TRADES_COUNT=100
AI_ANALYSIS_COOLDOWN_MINUTES=0

# Настройки производительности OpenAI
MAX_CONCURRENT_AI_REQUESTS=3
AI_RETRY_ATTEMPTS=2
AI_RETRY_DELAY=5

# Telegram настройки
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Дополнительные настройки
LOG_LEVEL=INFO
WS_PING_INTERVAL=20
KLINE_LIMIT=100
MAX_DAILY_SIGNALS=100
SIGNAL_COOLDOWN_MINUTES=5
NOTIFY_AI_ANALYSIS=true
"""


def get_settings_summary() -> dict:
    """Получить сводку текущих настроек"""
    settings = get_settings()
    
    return {
        "trading": {
            "pair": settings.TRADING_PAIR,
            "timeframe": settings.STRATEGY_TIMEFRAME,
            "mode": "TESTNET" if settings.BYBIT_WS_TESTNET else "MAINNET"
        },
        "strategy": {
            "rsi_period": settings.RSI_PERIOD,
            "ma_periods": f"{settings.MA_SHORT_PERIOD}/{settings.MA_LONG_PERIOD}",
            "min_confidence": settings.MIN_SIGNAL_CONFIDENCE
        },
        "ai_analysis": {
            "enabled": settings.AI_ANALYSIS_ENABLED,
            "openai_configured": settings.is_openai_configured,
            "model": settings.OPENAI_MODEL,
            "max_tokens": settings.OPENAI_MAX_TOKENS,
            "temperature": settings.OPENAI_TEMPERATURE
        },
        "integrations": {
            "telegram": settings.is_telegram_configured,
            "openai": settings.is_openai_configured
        },
        "performance": {
            "klines_limit": settings.KLINE_LIMIT,
            "ai_klines": settings.AI_KLINES_COUNT,
            "concurrent_ai": settings.MAX_CONCURRENT_AI_REQUESTS
        }
    }
