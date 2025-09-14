"""
Телеграм бот для торговых уведомлений и ИИ-анализа рынка
Обновлено: исправлена проблема conflict с multiple instances
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import html
import json

# Пошаговая детекция Telegram библиотеки
TELEGRAM_AVAILABLE = False
telegram_import_error = None

try:
    import telegram
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    TELEGRAM_AVAILABLE = True
except ImportError as e:
    telegram_import_error = str(e)

if TELEGRAM_AVAILABLE:
    try:
        from telegram.ext import (
            Application,
            CommandHandler,
            CallbackQueryHandler,
            MessageHandler,
            filters,
            ContextTypes
        )
        from telegram.constants import ParseMode
        from telegram.error import TelegramError, Conflict, NetworkError
    except ImportError as e:
        TELEGRAM_AVAILABLE = False
        telegram_import_error = str(e)

from config.settings import get_settings


class TelegramBot:
    """Телеграм бот для торгового бота с ИИ-анализом рынка (исправлен conflict)"""
    
    def __init__(self, token: str, chat_id: str, websocket_manager=None, market_analyzer=None):
        self.token = token
        self.chat_id = chat_id
        self.websocket_manager = websocket_manager
        self.market_analyzer = market_analyzer
        self.settings = get_settings()
        
        self.application = None
        self.is_running = False
        self.is_starting = False  # Флаг для предотвращения множественного запуска
        
        self.logger = logging.getLogger(__name__)
        
        # Проверяем доступность Telegram
        if not TELEGRAM_AVAILABLE:
            self.logger.warning(f"⚠️ Telegram библиотека недоступна: {telegram_import_error}")
            return
        
        self.logger.info("✅ Telegram библиотека обнаружена успешно")
        
        # Состояние бота
        self.notifications_enabled = True
        self.user_settings = {
            "notifications": True,
            "signal_types": ["BUY", "SELL"],
            "min_confidence": 0.7,
            "ai_analysis": True
        }
        
        # Кулдаун для ИИ-анализа
        self.last_ai_analysis = None
        self.ai_analysis_in_progress = False
        
        # Управление конфликтами
        self.max_startup_retries = 3
        self.startup_retry_delay = 5
        
    async def start(self):
        """Запуск телеграм бота с решением conflict проблемы"""
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("⚠️ Telegram библиотека недоступна. Пропускаем запуск.")
            return
            
        if not self.token or not self.chat_id:
            self.logger.warning("⚠️ TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не указаны")
            return
        
        if self.is_starting or self.is_running:
            self.logger.warning("⚠️ Telegram бот уже запускается или запущен")
            return
            
        self.is_starting = True
        
        try:
            self.logger.info("🤖 Запуск Telegram бота с защитой от конфликтов...")
            self.logger.info(f"   Token: {self.token[:10]}...")
            self.logger.info(f"   Chat ID: {self.chat_id}")
            
            # Очистка возможных конфликтующих соединений
            await self._cleanup_existing_connections()
            
            # Попытки запуска с retry logic
            for attempt in range(self.max_startup_retries):
                try:
                    await self._start_bot_instance()
                    break
                except Conflict as e:
                    self.logger.warning(f"⚠️ Попытка {attempt + 1}: Конфликт соединений - {e}")
                    if attempt < self.max_startup_retries - 1:
                        self.logger.info(f"🔄 Ожидание {self.startup_retry_delay} сек перед повтором...")
                        await asyncio.sleep(self.startup_retry_delay)
                    else:
                        raise
                except Exception as e:
                    self.logger.error(f"❌ Попытка {attempt + 1}: Ошибка запуска - {e}")
                    if attempt < self.max_startup_retries - 1:
                        await asyncio.sleep(self.startup_retry_delay)
                    else:
                        raise
            
            self.is_running = True
            self.logger.info("✅ Telegram бот успешно запущен")
            
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка запуска Telegram бота: {e}")
            # Не поднимаем исключение, чтобы не сломать весь бот
        finally:
            self.is_starting = False
    
    async def _cleanup_existing_connections(self):
        """Очистка существующих соединений"""
        try:
            self.logger.info("🧹 Очистка существующих Telegram соединений...")
            
            # Создаем временного бота для очистки
            temp_app = Application.builder().token(self.token).build()
            await temp_app.initialize()
            
            try:
                # Получаем информацию о боте
                bot_info = await temp_app.bot.get_me()
                self.logger.info(f"🤖 Подключение к боту: @{bot_info.username}")
                
                # Удаляем webhook если есть
                webhook_info = await temp_app.bot.get_webhook_info()
                if webhook_info.url:
                    self.logger.info(f"🔗 Удаляем webhook: {webhook_info.url}")
                    await temp_app.bot.delete_webhook(drop_pending_updates=True)
                
                # Очищаем pending updates
                self.logger.info("🗑️ Очистка pending updates...")
                await temp_app.bot.get_updates(offset=-1, limit=1, timeout=1)
                
            except Exception as e:
                self.logger.warning(f"⚠️ Ошибка при очистке: {e}")
            finally:
                await temp_app.shutdown()
                
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось выполнить очистку: {e}")
    
    async def _start_bot_instance(self):
        """Запуск экземпляра бота"""
        # Создание приложения
        self.application = Application.builder().token(self.token).build()
        
        # Регистрация обработчиков
        await self._register_handlers()
        
        # Установка команд меню
        await self._set_bot_commands()
        
        # Инициализация и запуск
        await self.application.initialize()
        await self.application.start()
        
        # Запуск polling с обработкой ошибок
        await self.application.updater.start_polling(
            drop_pending_updates=True,  # Игнорируем старые обновления
            allowed_updates=Update.ALL_TYPES,
            error_callback=self._handle_polling_error
        )
        
        # Приветственное сообщение
        await self._send_startup_message()
    
    async def _handle_polling_error(self, update: object, context) -> None:
        """Обработчик ошибок polling"""
        try:
            exception = context.error
            
            if isinstance(exception, Conflict):
                self.logger.error("❌ Конфликт Telegram соединений!")
                self.logger.error("   Возможные причины:")
                self.logger.error("   - Запущен другой экземпляр бота")
                self.logger.error("   - Локальный бот конфликтует с Render")
                self.logger.error("   - Не завершился предыдущий процесс")
                
                # Попытка переподключения через некоторое время
                await asyncio.sleep(10)
                
            elif isinstance(exception, NetworkError):
                self.logger.warning(f"⚠️ Сетевая ошибка: {exception}")
                
            else:
                self.logger.error(f"❌ Ошибка polling: {exception}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка в обработчике ошибок: {e}")
    
    async def _send_startup_message(self):
        """Отправка приветственного сообщения"""
        try:
            ai_status = "🤖 Включен" if self.market_analyzer and self.settings.is_openai_configured else "❌ Отключен"
            
            startup_text = (
                "🚀 <b>Торговый бот с ИИ-анализом запущен!</b>\n\n"
                f"📊 Пара: <code>{self.settings.TRADING_PAIR}</code>\n"
                f"⏱ Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>\n"
                f"🎯 Стратегия: <b>RSI + MA</b>\n"
                f"🤖 ИИ-анализ: {ai_status}\n\n"
                "Нажмите кнопку ниже для получения ИИ-анализа рынка 👇"
            )
            
            await self.send_message(
                startup_text,
                reply_markup=self._get_main_keyboard()
            )
            
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось отправить приветственное сообщение: {e}")
    
    async def stop(self):
        """Остановка телеграм бота с правильной очисткой"""
        if not TELEGRAM_AVAILABLE or not self.application:
            return
            
        try:
            self.logger.info("🛑 Остановка Telegram бота...")
            
            self.is_running = False
            
            # Отправляем сообщение об остановке
            try:
                await self.send_message("🛑 <b>Бот остановлен</b>\n\nСервис временно недоступен.")
            except:
                pass  # Игнорируем ошибки при отправке последнего сообщения
            
            # Правильная остановка polling
            if self.application.updater.running:
                await self.application.updater.stop()
            
            # Остановка приложения
            if self.application.running:
                await self.application.stop()
            
            # Завершение
            await self.application.shutdown()
            
            self.logger.info("✅ Telegram бот корректно остановлен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка остановки Telegram бота: {e}")
    
    async def _register_handlers(self):
        """Регистрация обработчиков команд"""
        if not self.application:
            return
            
        # Основные команды
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("help", self._cmd_help))
        self.application.add_handler(CommandHandler("status", self._cmd_status))
        self.application.add_handler(CommandHandler("market", self._cmd_market_analysis))
        self.application.add_handler(CommandHandler("ai", self._cmd_market_analysis))
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))
        
        # Обработчик текстовых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        
        # Обработчик ошибок
        self.application.add_error_handler(self._handle_polling_error)
    
    async def _set_bot_commands(self):
        """Установка команд в меню бота"""
        if not self.application:
            return
            
        commands = [
            BotCommand("start", "🚀 Запуск бота"),
            BotCommand("help", "❓ Помощь"),
            BotCommand("status", "📊 Статус бота"),
            BotCommand("market", "🤖 ИИ-анализ рынка"),
            BotCommand("ai", "🤖 ИИ-анализ рынка")
        ]
        
        await self.application.bot.set_my_commands(commands)
    
    def _get_main_keyboard(self):
        """Основная клавиатура - ТОЛЬКО кнопка анализа рынка"""
        if not TELEGRAM_AVAILABLE:
            return None
        
        # Проверяем доступность ИИ-анализа
        ai_available = self.market_analyzer and self.settings.is_openai_configured
        button_text = "🤖 Узнать рынок (ИИ)" if ai_available else "📈 Узнать рынок (базовый)"
        
        keyboard = [
            [
                InlineKeyboardButton(button_text, callback_data="ai_market_analysis")
            ]
        ]
        
        # Если ИИ недоступен, добавляем информацию
        if not ai_available:
            keyboard.append([
                InlineKeyboardButton("ℹ️ Настроить ИИ", callback_data="ai_setup_info")
            ])
        
        return InlineKeyboardMarkup(keyboard)
    
    # Обработчики команд (остаются теми же)
    async def _cmd_start(self, update, context):
        """Команда /start"""
        ai_status = "🤖 Включен" if self.market_analyzer and self.settings.is_openai_configured else "❌ Отключен"
        
        await update.message.reply_text(
            "🚀 <b>Добро пожаловать в торговый бот с ИИ-анализом!</b>\n\n"
            f"📊 Торговая пара: <code>{self.settings.TRADING_PAIR}</code>\n"
            f"⏱ Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>\n"
            f"🎯 Стратегия: <b>RSI + Moving Average</b>\n"
            f"🤖 ИИ-анализ GPT-4: {ai_status}\n\n"
            "Нажмите кнопку ниже для получения профессионального анализа рынка от ИИ 👇",
            parse_mode=ParseMode.HTML,
            reply_markup=self._get_main_keyboard()
        )
    
    async def _cmd_help(self, update, context):
        """Команда /help"""
        help_text = """
🆘 <b>Помощь по боту</b>

<b>Основные команды:</b>
/start - Запуск бота
/help - Эта справка  
/status - Статус бота
/market - ИИ-анализ рынка
/ai - ИИ-анализ рынка

<b>🤖 ИИ-анализ включает:</b>
- 📊 Технический анализ всех индикаторов
- 🎯 Конкретные уровни входа, TP и SL
- 📈 Прогнозы на разные временные горизонты
- ⚠️ Оценка рисков и возможностей
- 💡 Профессиональные рекомендации

<b>🔗 Источники данных:</b>
- Свечи, объемы, индикаторы
- Ордербук и активность трейдеров
- Анализ через GPT-4

⚠️ <b>Важно:</b> ИИ-анализ носит информационный характер!
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    
    async def _cmd_status(self, update, context):
        """Команда /status"""
        ai_status = "🟢 Работает" if self.market_analyzer and self.settings.is_openai_configured else "🔴 Отключен"
        ai_model = self.settings.OPENAI_MODEL if self.settings.is_openai_configured else "Не настроен"
        
        status_text = f"""
📊 <b>Статус бота</b>

<b>Торговля:</b>
Пара: <code>{self.settings.TRADING_PAIR}</code>
Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>
Режим: <code>{'TESTNET' if self.settings.BYBIT_WS_TESTNET else 'MAINNET'}</code>

<b>WebSocket:</b> {'🟢 Подключен' if self.websocket_manager and self.websocket_manager.is_connected else '🔴 Отключен'}

<b>🤖 ИИ-анализ:</b>
Статус: {ai_status}
Модель: <code>{ai_model}</code>
Анализ в процессе: {'🔄 Да' if self.ai_analysis_in_progress else '✅ Нет'}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
        """
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
    
    async def _cmd_market_analysis(self, update, context):
        """Команда /market или /ai - запуск ИИ-анализа"""
        await self._perform_ai_market_analysis(update.message.chat_id)
    
    async def _handle_callback(self, update, context):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "ai_market_analysis":
            # Основная кнопка - ИИ-анализ рынка
            await self._perform_ai_market_analysis(query.message.chat_id, query.message.message_id)
            
        elif data == "ai_setup_info":
            # Информация о настройке ИИ
            setup_text = """
🤖 <b>Настройка ИИ-анализа</b>

Для включения ИИ-анализа необходимо:

1️⃣ Получить API ключ OpenAI:
   • Перейти на platform.openai.com
   • Создать аккаунт и получить API key
   • Пополнить баланс

2️⃣ Добавить в переменные окружения:
   <code>OPENAI_API_KEY=sk-your_key_here</code>

3️⃣ Перезапустить бота

<b>💰 Стоимость:</b>
- GPT-4: ~$0.03-0.06 за анализ
- GPT-3.5: ~$0.002-0.004 за анализ

<b>🎯 Что получите:</b>
- Профессиональный технический анализ
- Конкретные уровни входа и выхода
- Take Profit и Stop Loss рекомендации
- Прогнозы на разные временные горизонты
            """
            
            await query.edit_message_text(
                setup_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")
                ]])
            )
            
        elif data == "back_to_main":
            # Возврат к главному меню
            await query.edit_message_text(
                "🤖 <b>Торговый бот готов к работе!</b>\n\n"
                "Нажмите кнопку ниже для получения ИИ-анализа рынка 👇",
                parse_mode=ParseMode.HTML,
                reply_markup=self._get_main_keyboard()
            )
    
    async def _handle_message(self, update, context):
        """Обработка текстовых сообщений"""
        text = update.message.text.lower()
        
        if any(keyword in text for keyword in ["анализ", "рынок", "market", "analysis", "ии", "ai", "гпт", "gpt"]):
            await self._perform_ai_market_analysis(update.message.chat_id)
        elif "статус" in text or "status" in text:
            await self._cmd_status(update, context)
        else:
            await update.message.reply_text(
                "🤖 <b>Для получения ИИ-анализа рынка:</b>\n\n"
                "• Нажмите кнопку ниже\n"
                "• Или отправьте /market\n"
                "• Или напишите 'анализ рынка'\n\n"
                "Используйте /help для полной справки",
                parse_mode=ParseMode.HTML,
                reply_markup=self._get_main_keyboard()
            )
    
    async def _perform_ai_market_analysis(self, chat_id: int, message_id: Optional[int] = None):
        """Выполнение ИИ-анализа рынка"""
        try:
            # Проверка кулдауна
            if self._is_analysis_cooldown():
                await self.send_message(
                    f"⏳ <b>Анализ выполняется слишком часто</b>\n\n"
                    f"Подождите {self.settings.AI_ANALYSIS_COOLDOWN_MINUTES} минут между запросами",
                    chat_id=chat_id
                )
                return
            
            # Проверка, что анализ не выполняется
            if self.ai_analysis_in_progress:
                await self.send_message(
                    "🔄 <b>Анализ уже выполняется</b>\n\nПодождите завершения текущего анализа...",
                    chat_id=chat_id
                )
                return
            
            # Проверка доступности компонентов
            if not self.market_analyzer:
                await self.send_message(
                    "❌ <b>ИИ-анализатор не инициализирован</b>\n\n"
                    "Проверьте настройки OPENAI_API_KEY и перезапустите бота",
                    chat_id=chat_id
                )
                return
            
            if not self.settings.is_openai_configured:
                await self.send_message(
                    "❌ <b>OpenAI не настроен</b>\n\n"
                    "Добавьте OPENAI_API_KEY в переменные окружения:\n"
                    "<code>OPENAI_API_KEY=sk-your_key_here</code>\n\n"
                    "Получить ключ: https://platform.openai.com",
                    parse_mode=ParseMode.HTML,
                    chat_id=chat_id
                )
                return
            
            # Начинаем анализ
            self.ai_analysis_in_progress = True
            self.last_ai_analysis = datetime.now()
            
            # Отправляем сообщение о начале анализа
            await self.send_message(
                "🤖 <b>Запуск ИИ-анализа рынка...</b>\n\n"
                "🔍 Собираю рыночные данные...\n"
                "📊 Анализирую индикаторы...\n"
                "🧠 Отправляю в GPT-4...\n\n"
                "⏳ Это может занять 10-30 секунд",
                chat_id=chat_id
            )
            
            # Выполняем анализ
            market_data, ai_analysis = await self.market_analyzer.analyze_market(self.settings.TRADING_PAIR)
            
            # Проверяем результаты
            if not market_data and not ai_analysis:
                await self.send_message(
                    "❌ <b>Не удалось выполнить анализ</b>\n\n"
                    "Возможные причины:\n"
                    "• Нет подключения к рынку\n"
                    "• Проблемы с OpenAI API\n"
                    "• Неверный API ключ\n\n"
                    "Попробуйте позже или проверьте настройки",
                    chat_id=chat_id
                )
                return
            
            # Отправляем рыночные данные (первое сообщение)
            if market_data:
                market_message = self.market_analyzer.format_market_data_message(market_data)
                await self.send_message(market_message, chat_id=chat_id)
            
            # Отправляем ИИ-анализ (второе сообщение)
            if ai_analysis and not ai_analysis.startswith("❌"):
                analysis_message = f"🤖 <b>ИИ-АНАЛИЗ РЫНКА (GPT-4)</b>\n\n{ai_analysis}"
                await self.send_message(analysis_message, chat_id=chat_id)
                
                # Добавляем кнопку для повторного анализа
                await self.send_message(
                    "✅ <b>Анализ завершен!</b>\n\n"
                    "Для получения нового анализа нажмите кнопку ниже 👇",
                    reply_markup=self._get_main_keyboard(),
                    chat_id=chat_id
                )
            else:
                # Ошибка в анализе
                error_message = ai_analysis if ai_analysis else "❌ Не удалось получить ИИ-анализ"
                await self.send_message(error_message, chat_id=chat_id)
            
            self.logger.info(f"✅ ИИ-анализ рынка завершен для чата {chat_id}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка выполнения ИИ-анализа: {e}")
            await self.send_message(
                f"❌ <b>Ошибка анализа</b>\n\n"
                f"Произошла неожиданная ошибка:\n"
                f"<code>{str(e)}</code>\n\n"
                f"Попробуйте позже или обратитесь к администратору",
                parse_mode=ParseMode.HTML,
                chat_id=chat_id
            )
        finally:
            self.ai_analysis_in_progress = False
    
    def _is_analysis_cooldown(self) -> bool:
        """Проверка кулдауна для ИИ-анализа"""
        if not self.last_ai_analysis or self.settings.AI_ANALYSIS_COOLDOWN_MINUTES == 0:
            return False
        
        cooldown_minutes = self.settings.AI_ANALYSIS_COOLDOWN_MINUTES
        time_diff = datetime.now() - self.last_ai_analysis
        
        return time_diff < timedelta(minutes=cooldown_minutes)
    
    # Отправка уведомлений о торговых сигналах
    async def send_signal_notification(self, signal_data: dict):
        """Отправка уведомления о торговом сигнале"""
        if not TELEGRAM_AVAILABLE or not self.is_running:
            self.logger.info(f"📤 [Telegram недоступен] Сигнал: {signal_data.get('signal_type', 'N/A')} {signal_data.get('symbol', 'N/A')}")
            return
            
        try:
            if not self.user_settings["notifications"]:
                return
            
            signal_type = signal_data.get("signal_type", "")
            confidence = signal_data.get("confidence", 0)
            
            if signal_type not in self.user_settings["signal_types"]:
                return
                
            if confidence < self.user_settings["min_confidence"]:
                return
            
            # Форматируем сообщение о сигнале
            signal_emoji = "🟢" if signal_type == "BUY" else "🔴" if signal_type == "SELL" else "🔵"
            confidence_stars = "⭐" * min(5, int(confidence * 5))
            
            text = f"""
🚨 <b>ТОРГОВЫЙ СИГНАЛ!</b>

{signal_emoji} <b>{signal_type} {signal_data.get('symbol', '')}</b>

💰 <b>Цена:</b> <code>${signal_data.get('price', 0):.4f}</code>
🎯 <b>Уверенность:</b> <code>{confidence:.1%}</code> {confidence_stars}
⏰ <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}

💭 <b>Причина:</b> {signal_data.get('reason', 'Нет описания')}

⚠️ <i>Торгуйте ответственно!</i>
            """
            
            await self.send_message(text)
            self.logger.info(f"📤 Отправлено уведомление о сигнале: {signal_type} {signal_data.get('symbol', '')}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки уведомления: {e}")
    
    async def send_message(self, text: str, reply_markup=None, chat_id: Optional[int] = None):
        """Отправка сообщения в чат с обработкой ошибок"""
        if not TELEGRAM_AVAILABLE or not self.application or not self.is_running:
            self.logger.info(f"📤 [Telegram недоступен] {text[:100]}...")
            return
            
        try:
            target_chat_id = chat_id or self.chat_id
            
            await self.application.bot.send_message(
                chat_id=target_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Conflict as e:
            self.logger.error(f"❌ Конфликт при отправке сообщения: {e}")
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки сообщения Telegram: {e}")
    
    def get_bot_status(self) -> dict:
        """Получить статус телеграм бота"""
        return {
            "is_running": self.is_running,
            "is_starting": self.is_starting,
            "telegram_available": TELEGRAM_AVAILABLE,
            "ai_analyzer_available": self.market_analyzer is not None,
            "openai_configured": self.settings.is_openai_configured,
            "ai_analysis_in_progress": self.ai_analysis_in_progress,
            "last_ai_analysis": self.last_ai_analysis.isoformat() if self.last_ai_analysis else None,
            "notifications_enabled": self.notifications_enabled,
            "user_settings": self.user_settings,
            "max_startup_retries": self.max_startup_retries
        }
