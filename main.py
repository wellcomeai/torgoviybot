"""
Главный файл торгового бота для Bybit с ИИ-анализом
Веб-сервис для деплоя на Render с интеграцией OpenAI GPT-4
Обновлено: добавлен ИИ-анализ рынка через MarketAnalyzer
Обновлено: интеграция с официальной библиотекой pybit v5.11.0
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
from telegram_bot.bot import TelegramBot
from ai_analyzer.market_analyzer import MarketAnalyzer  # НОВЫЙ ИМПОРТ

# Настройка логирования (безопасно для Render)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()  # Только console для Render
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
        self.market_analyzer: Optional[MarketAnalyzer] = None  # НОВЫЙ КОМПОНЕНТ
        
        self.status = {
            "is_running": False,
            "start_time": None,
            "websocket_connected": False,
            "last_signal": None,
            "current_pair": "BTCUSDT",
            "strategy_status": "idle",
            "last_price": None,
            "signals_count": 0,
            "ai_analysis_enabled": False,  # НОВЫЙ СТАТУС
            "ai_analysis_count": 0,  # НОВЫЙ СЧЕТЧИК
            "last_ai_analysis": None  # НОВОЕ ПОЛЕ
        }

# Глобальный менеджер бота
bot_manager = BotManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    logger.info("🚀 Запуск торгового бота с ИИ-анализом...")
    
    # Инициализация компонентов при запуске
    await initialize_bot()
    
    yield
    
    # Очистка ресурсов при завершении
    logger.info("🛑 Завершение работы бота...")
    await cleanup_bot()


app = FastAPI(
    title="Bybit Trading Bot with AI Analysis",
    description="Торговый бот для фьючерсов Bybit с ИИ-анализом через OpenAI GPT-4",
    version="2.1.0",
    lifespan=lifespan
)


async def initialize_bot():
    """Инициализация всех компонентов бота включая ИИ-анализатор"""
    try:
        logger.info("Инициализация компонентов с pybit...")
        
        # Загрузка настроек
        bot_manager.settings = get_settings()
        logger.info(f"✅ Настройки загружены")
        
        # НОВОЕ: Логирование использования pybit
        logger.info("✅ Используется официальная библиотека pybit v5.11.0")
        logger.info(f"   WebSocket: {bot_manager.settings.websocket_url}")
        logger.info(f"   REST API: {bot_manager.settings.bybit_rest_url}")
        
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
        
        # НОВОЕ: Инициализация ИИ-анализатора
        if bot_manager.settings.AI_ANALYSIS_ENABLED:
            try:
                bot_manager.market_analyzer = MarketAnalyzer(
                    websocket_manager=bot_manager.websocket_manager
                )
                
                # Проверяем статус анализатора
                analyzer_status = bot_manager.market_analyzer.get_status()
                
                if analyzer_status.get("openai_available") and analyzer_status.get("api_key_configured"):
                    logger.info("✅ ИИ-анализатор успешно инициализирован")
                    logger.info(f"   Модель: {bot_manager.settings.OPENAI_MODEL}")
                    logger.info(f"   Макс токенов: {bot_manager.settings.OPENAI_MAX_TOKENS}")
                    bot_manager.status["ai_analysis_enabled"] = True
                else:
                    logger.warning("⚠️ ИИ-анализатор инициализирован с ошибками:")
                    if not analyzer_status.get("openai_available"):
                        logger.warning("   - OpenAI библиотека недоступна")
                    if not analyzer_status.get("api_key_configured"):
                        logger.warning("   - OPENAI_API_KEY не настроен")
                    bot_manager.market_analyzer = None
                    
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации ИИ-анализатора: {e}")
                bot_manager.market_analyzer = None
        else:
            logger.info("📴 ИИ-анализ отключен в настройках")
        
        # Инициализация телеграм бота с ИИ-анализатором
        if bot_manager.settings.is_telegram_configured:
            bot_manager.telegram_bot = TelegramBot(
                token=bot_manager.settings.TELEGRAM_BOT_TOKEN,
                chat_id=bot_manager.settings.TELEGRAM_CHAT_ID,
                websocket_manager=bot_manager.websocket_manager,
                market_analyzer=bot_manager.market_analyzer  # ПЕРЕДАЕМ АНАЛИЗАТОР
            )
            await bot_manager.telegram_bot.start()
            logger.info("✅ Телеграм бот запущен с ИИ-анализом")
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
        
        # Логирование итогового статуса
        logger.info("📊 СТАТУС КОМПОНЕНТОВ:")
        logger.info(f"   WebSocket: {'✅ Подключен' if bot_manager.websocket_manager.is_connected else '❌ Отключен'}")
        logger.info(f"   Стратегия: {'✅ Активна' if bot_manager.strategy else '❌ Неактивна'}")
        logger.info(f"   Telegram: {'✅ Активен' if bot_manager.telegram_bot else '❌ Отключен'}")
        logger.info(f"   ИИ-анализ: {'✅ Активен' if bot_manager.market_analyzer else '❌ Отключен'}")
        
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
        
        # ИИ-анализатор не требует специальной очистки
        if bot_manager.market_analyzer:
            logger.info("✅ ИИ-анализатор отключен")
        
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
        "message": "Bybit Trading Bot with AI Analysis",
        "status": "running" if bot_manager.status["is_running"] else "stopped",
        "version": "2.1.0",
        "timestamp": datetime.now().isoformat(),
        "pair": bot_manager.status["current_pair"],
        "ai_enabled": bot_manager.status["ai_analysis_enabled"],
        "pybit_version": "5.11.0"
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
        "signals_count": bot_manager.status["signals_count"],
        "ai_analysis_enabled": bot_manager.status["ai_analysis_enabled"],
        "ai_analysis_count": bot_manager.status["ai_analysis_count"],
        "pybit_version": "5.11.0"
    }


@app.get("/status")
async def get_bot_status():
    """Получить подробный статус бота"""
    websocket_status = False
    telegram_status = False
    ai_status = False
    
    if bot_manager.websocket_manager:
        websocket_status = bot_manager.websocket_manager.is_connected
    
    if bot_manager.telegram_bot:
        telegram_status = bot_manager.telegram_bot.is_running
    
    if bot_manager.market_analyzer:
        ai_analyzer_status = bot_manager.market_analyzer.get_status()
        ai_status = ai_analyzer_status.get("client_initialized", False)
    
    return {
        "bot_status": bot_manager.status,
        "components": {
            "websocket_manager": websocket_status,
            "telegram_bot": telegram_status,
            "strategy_active": bot_manager.strategy is not None,
            "ai_analyzer": ai_status,
            "openai_configured": bot_manager.settings.is_openai_configured if bot_manager.settings else False
        },
        "last_price": bot_manager.status.get("last_price"),
        "strategy_data": bot_manager.strategy.get_current_data() if bot_manager.strategy else None,
        "ai_analyzer_status": bot_manager.market_analyzer.get_status() if bot_manager.market_analyzer else None,
        "library_info": {
            "pybit_version": "5.11.0",
            "websocket_url": bot_manager.settings.websocket_url if bot_manager.settings else None,
            "rest_url": bot_manager.settings.bybit_rest_url if bot_manager.settings else None
        }
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


# НОВЫЕ ENDPOINTS ДЛЯ ИИ-АНАЛИЗА

@app.post("/ai/analyze")
async def ai_market_analysis():
    """Запуск ИИ-анализа рынка через API"""
    try:
        if not bot_manager.market_analyzer:
            raise HTTPException(
                status_code=503, 
                detail="ИИ-анализатор не инициализирован. Проверьте OPENAI_API_KEY."
            )
        
        if not bot_manager.settings.is_openai_configured:
            raise HTTPException(
                status_code=503,
                detail="OpenAI не настроен. Добавьте OPENAI_API_KEY в переменные окружения."
            )
        
        logger.info("🤖 Запуск ИИ-анализа через API...")
        
        # Выполняем анализ
        market_data, ai_analysis = await bot_manager.market_analyzer.analyze_market(
            bot_manager.settings.TRADING_PAIR
        )
        
        # Обновляем статистику
        bot_manager.status["ai_analysis_count"] += 1
        bot_manager.status["last_ai_analysis"] = datetime.now()
        
        return {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "symbol": bot_manager.settings.TRADING_PAIR,
            "market_data": market_data,
            "ai_analysis": ai_analysis,
            "analysis_count": bot_manager.status["ai_analysis_count"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка ИИ-анализа через API: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка ИИ-анализа: {str(e)}")


@app.get("/ai/status")
async def get_ai_status():
    """Получить статус ИИ-анализатора"""
    try:
        if not bot_manager.market_analyzer:
            return {
                "ai_available": False,
                "reason": "ИИ-анализатор не инициализирован",
                "openai_configured": bot_manager.settings.is_openai_configured if bot_manager.settings else False,
                "analysis_enabled": bot_manager.settings.AI_ANALYSIS_ENABLED if bot_manager.settings else False
            }
        
        analyzer_status = bot_manager.market_analyzer.get_status()
        
        return {
            "ai_available": True,
            "analyzer_status": analyzer_status,
            "settings": {
                "model": bot_manager.settings.OPENAI_MODEL,
                "max_tokens": bot_manager.settings.OPENAI_MAX_TOKENS,
                "temperature": bot_manager.settings.OPENAI_TEMPERATURE,
                "analysis_enabled": bot_manager.settings.AI_ANALYSIS_ENABLED
            },
            "statistics": {
                "total_analyses": bot_manager.status["ai_analysis_count"],
                "last_analysis": bot_manager.status["last_ai_analysis"]
            }
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения статуса ИИ: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@app.get("/ai/config")
async def get_ai_config():
    """Получить конфигурацию ИИ-анализатора"""
    try:
        if not bot_manager.settings:
            raise HTTPException(status_code=503, detail="Настройки не загружены")
        
        return {
            "openai_configured": bot_manager.settings.is_openai_configured,
            "analysis_enabled": bot_manager.settings.AI_ANALYSIS_ENABLED,
            "model": bot_manager.settings.OPENAI_MODEL,
            "max_tokens": bot_manager.settings.OPENAI_MAX_TOKENS,
            "temperature": bot_manager.settings.OPENAI_TEMPERATURE,
            "timeout": bot_manager.settings.OPENAI_TIMEOUT,
            "data_settings": {
                "klines_count": bot_manager.settings.AI_KLINES_COUNT,
                "orderbook_levels": bot_manager.settings.AI_ORDERBOOK_LEVELS,
                "trades_count": bot_manager.settings.AI_TRADES_COUNT
            },
            "performance": {
                "max_concurrent_requests": bot_manager.settings.MAX_CONCURRENT_AI_REQUESTS,
                "retry_attempts": bot_manager.settings.AI_RETRY_ATTEMPTS,
                "cooldown_minutes": bot_manager.settings.AI_ANALYSIS_COOLDOWN_MINUTES
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка получения конфигурации ИИ: {e}")
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
    
    logger.info(f"🚀 Запуск сервера с ИИ-анализом на {host}:{port}")
    logger.info(f"📊 OpenAI настроен: {'Да' if os.getenv('OPENAI_API_KEY') else 'Нет'}")
    logger.info(f"📦 Используется pybit v5.11.0 для Bybit API")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,  # Отключено для продакшена
        log_level="info"
    )
