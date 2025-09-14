"""
Настройки торгового бота
Конфигурация для всех компонентов
"""

import os
from typing import Optional
from pydantic import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Основные настройки
    APP_NAME: str = "Bybit Trading Bot"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, env="DEBUG")
    
    # Настройки торговли
    TRADING_PAIR: str = Field(default="BTCUSDT", env="TRADING_PAIR")
    STRATEGY_TIMEFRAME: str = Field(default="5m", env="STRATEGY_TIMEFRAME")  # 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d
    
    # Bybit WebSocket настройки
    BYBIT_WS_TESTNET: bool = Field(default=True, env="BYBIT_WS_TESTNET")
    BYBIT_WS_LINEAR_URL: str = Field(
        default="wss://stream-testnet.bybit.com/v5/public/linear",
        env="BYBIT_WS_LINEAR_URL"
    )
    BYBIT_WS_MAINNET_URL: str = "wss://stream.bybit.com/v5/public/linear"
    
    # Настройки стратегии RSI + MA
    RSI_PERIOD: int = Field(default=14, env="RSI_PERIOD")
    RSI_OVERSOLD: float = Field(default=30.0, env="RSI_OVERSOLD")
    RSI_OVERBOUGHT: float = Field(default=70.0, env="RSI_OVERBOUGHT")
    
    MA_SHORT_PERIOD: int = Field(default=9, env="MA_SHORT_PERIOD")
    MA_LONG_PERIOD: int = Field(default=21, env="MA_LONG_PERIOD")
    
    # Минимальная уверенность для сигнала (0.0 - 1.0)
    MIN_SIGNAL_CONFIDENCE: float = Field(default=0.7, env="MIN_SIGNAL_CONFIDENCE")
    
    # Telegram настройки
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, env="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None, env="TELEGRAM_CHAT_ID")
    
    # Настройки логирования
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    # LOG_FILE убираем для совместимости с Render
    
    # Настройки WebSocket
    WS_PING_INTERVAL: int = Field(default=20, env="WS_PING_INTERVAL")  # секунды
    WS_RECONNECT_ATTEMPTS: int = Field(default=5, env="WS_RECONNECT_ATTEMPTS")
    WS_RECONNECT_DELAY: int = Field(default=5, env="WS_RECONNECT_DELAY")  # секунды
    
    # Настройки данных
    KLINE_LIMIT: int = Field(default=100, env="KLINE_LIMIT")  # Количество свечей для анализа
    DATA_RETENTION_HOURS: int = Field(default=24, env="DATA_RETENTION_HOURS")
    
    # Настройки уведомлений
    NOTIFY_ALL_SIGNALS: bool = Field(default=True, env="NOTIFY_ALL_SIGNALS")
    NOTIFY_HIGH_CONFIDENCE_ONLY: bool = Field(default=False, env="NOTIFY_HIGH_CONFIDENCE_ONLY")
    
    # Настройки безопасности
    MAX_DAILY_SIGNALS: int = Field(default=100, env="MAX_DAILY_SIGNALS")
    SIGNAL_COOLDOWN_MINUTES: int = Field(default=5, env="SIGNAL_COOLDOWN_MINUTES")
    
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Глобальный экземпляр настроек
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Получить экземпляр настроек (синглтон)"""
    global _settings
    
    if _settings is None:
        _settings = Settings()
        
        # Логирование загруженных настроек
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔧 Настройки загружены:")
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
