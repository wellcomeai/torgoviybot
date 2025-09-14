"""
Главный файл торгового бота для Bybit
Веб-сервис для деплоя на Render
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Добавляем текущую директорию в путь для импортов
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Импорты компонентов бота
from config.settings import Settings, get_settings
from core.websocket_manager import WebSocketManager
from strategies.base_strategy import BaseStrategy
from telegram.bot import TelegramBot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)

logger = logging.getLogger(__name__)

# Глобальные переменные для хранения состояния бота
class BotManager:
    def __init__(self):
        self.settings: Optional[Settings] = None
        self.websocket_manager: Optional[WebSocketManager] = None
        self.telegram_bot: Optional[TelegramBot] = None
        self.strategy: Optional[BaseStrategy] = None
        
        self.status = {
            "is_running": False,
            "start_time": None,
            "websocket_connected": False,
            "last_signal": None,
            "current_pair": "BTCUSDT",
            "strategy_status": "idle",
            "last_price": None,
            "signals_count": 0
        }

# Глобальный менеджер бота
bot_manager = BotManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("🚀 Запуск торгового бота...")
    
    # Инициализация компонентов при запуске
    await initialize_bot()
    
    yield
    
    # Очистка ресурсов при завершении
    logger.info("🛑 Завершение работы бота...")
    await cleanup_bot()


app = FastAPI(
    title="Bybit Trading Bot",
    description="Торговый бот для фьючерсов Bybit с телеграм уведомлениями",
    version="1.0.0",
    lifespan=lifespan
)


async def initialize_bot():
    """Инициализация всех компонентов бота"""
    try:
        logger.info("Инициализация компонентов...")
        
        # Загрузка настроек
        bot_manager.settings = get_settings()
        logger.info(f"✅ Настройки загружены")
        
        # Инициализация стратегии
        bot_manager.strategy = BaseStrategy(
            symbol=bot_manager.settings.TRADING_PAIR,
            timeframe=bot_manager.settings.STRATEGY_TIMEFRAME
        )
        logger.info(f"✅ Стратегия инициализирована для {bot_manager.settings.TRADING_PAIR}")
        
        # Инициализация WebSocket менеджера
        bot_manager.websocket_manager = WebSocketManager(
            symbol=bot_manager.settings.TRADING_PAIR,
            strategy=bot_manager.strategy,
            on_signal_callback=on_trading_signal
        )
        
        # Запуск WebSocket соединения
        await bot_manager.websocket_manager.start()
        logger.info("✅ WebSocket менеджер запущен")
        
        # Инициализация телеграм бота
        if bot_manager.settings.TELEGRAM_BOT_TOKEN:
            bot_manager.telegram_bot = TelegramBot(
                token=bot_manager.settings.TELEGRAM_BOT_TOKEN,
                chat_id=bot_manager.settings.TELEGRAM_CHAT_ID,
                websocket_manager=bot_manager.websocket_manager
            )
            await bot_manager.telegram_bot.start()
            logger.info("✅ Телеграм бот запущен")
        else:
            logger.warning("⚠️ Telegram bot token не найден, телеграм уведомления отключены")
        
        # Обновление статуса
        bot_manager.status.update({
            "is_running": True,
            "start_time": datetime.now(),
            "websocket_connected": True,
            "strategy_status": "active"
        })
        
        logger.info("✅ Все компоненты успешно инициализированы")
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        bot_manager.status["is_running"] = False
        raise


async def cleanup_bot():
    """Очистка ресурсов при завершении"""
    try:
        bot_manager.status["is_running"] = False
        
        # Остановка WebSocket соединения
        if bot_manager.websocket_manager:
            await bot_manager.websocket_manager.stop()
            logger.info("✅ WebSocket соединение закрыто")
        
        # Остановка телеграм бота
        if bot_manager.telegram_bot:
            await bot_manager.telegram_bot.stop()
            logger.info("✅ Телеграм бот остановлен")
        
        logger.info("✅ Все ресурсы очищены")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при очистке: {e}")


async def on_trading_signal(signal_data: dict):
    """Обработчик торговых сигналов"""
    try:
        logger.info(f"📊 Новый сигнал: {signal_data}")
        
        # Обновление статуса
        bot_manager.status["last_signal"] = signal_data
        bot_manager.status["signals_count"] += 1
        
        # Отправка уведомления в телеграм
        if bot_manager.telegram_bot:
            await bot_manager.telegram_bot.send_signal_notification(signal_data)
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки сигнала: {e}")


@app.get("/")
async def root():
    """Главная страница"""
    return {
        "message": "Bybit Trading Bot API",
        "status": "running" if bot_manager.status["is_running"] else "stopped",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
        "pair": bot_manager.status["current_pair"]
    }


@app.get("/health")
async def health_check():
    """Health check для Render"""
    if not bot_manager.status["is_running"]:
        raise HTTPException(status_code=503, detail="Bot is not running")
    
    websocket_status = False
    if bot_manager.websocket_manager:
        websocket_status = bot_manager.websocket_manager.is_connected
    
    return {
        "status": "healthy",
        "uptime": str(datetime.now() - bot_manager.status["start_time"]) if bot_manager.status["start_time"] else None,
        "websocket": "connected" if websocket_status else "disconnected",
        "strategy": bot_manager.status["strategy_status"],
        "current_pair": bot_manager.status["current_pair"],
        "signals_count": bot_manager.status["signals_count"]
    }


@app.get("/status")
async def get_bot_status():
    """Получить подробный статус бота"""
    websocket_status = False
    telegram_status = False
    
    if bot_manager.websocket_manager:
        websocket_status = bot_manager.websocket_manager.is_connected
    
    if bot_manager.telegram_bot:
        telegram_status = bot_manager.telegram_bot.is_running
    
    return {
        "bot_status": bot_manager.status,
        "components": {
            "websocket_manager": websocket_status,
            "telegram_bot": telegram_status,
            "strategy_active": bot_manager.strategy is not None
        },
        "last_price": bot_manager.status.get("last_price"),
        "strategy_data": bot_manager.strategy.get_current_data() if bot_manager.strategy else None
    }


@app.post("/start")
async def start_bot():
    """Запуск бота"""
    try:
        if bot_manager.status["is_running"]:
            return {"message": "Бот уже запущен", "status": "running"}
        
        await initialize_bot()
        return {"message": "Бот успешно запущен", "status": "running"}
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка запуска: {str(e)}")


@app.post("/stop")
async def stop_bot():
    """Остановка бота"""
    try:
        if not bot_manager.status["is_running"]:
            return {"message": "Бот уже остановлен", "status": "stopped"}
        
        await cleanup_bot()
        return {"message": "Бот успешно остановлен", "status": "stopped"}
        
    except Exception as e:
        logger.error(f"Ошибка остановки бота: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка остановки: {str(e)}")


@app.get("/market/{symbol}")
async def get_market_info(symbol: str = "BTCUSDT"):
    """Получить информацию о рынке"""
    try:
        if not bot_manager.websocket_manager:
            raise HTTPException(status_code=503, detail="WebSocket не подключен")
        
        market_data = bot_manager.websocket_manager.get_market_data(symbol)
        
        if not market_data:
            raise HTTPException(status_code=404, detail=f"Данные для {symbol} не найдены")
        
        return market_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения рыночных данных: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/signals/latest")
async def get_latest_signals():
    """Получить последние торговые сигналы"""
    try:
        if not bot_manager.strategy:
            raise HTTPException(status_code=503, detail="Стратегия не активна")
        
        signals = bot_manager.strategy.get_recent_signals(limit=10)
        
        return {
            "signals": signals,
            "total_signals": bot_manager.status["signals_count"],
            "last_signal": bot_manager.status["last_signal"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения сигналов: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/strategy/status")
async def get_strategy_status():
    """Получить статус стратегии"""
    try:
        if not bot_manager.strategy:
            raise HTTPException(status_code=503, detail="Стратегия не активна")
        
        return bot_manager.strategy.get_status()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения статуса стратегии: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Глобальный обработчик исключений"""
    logger.error(f"Неожиданная ошибка: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера", "error": str(exc)}
    )


if __name__ == "__main__":
    # Настройки для локального запуска и Render
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0"
    
    logger.info(f"🚀 Запуск сервера на {host}:{port}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,  # Отключено для продакшена
        log_level="info"
    )
