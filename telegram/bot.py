"""
Телеграм бот для торговых уведомлений и управления
Обработка команд, кнопок и отправка сигналов (ОПЦИОНАЛЬНЫЙ)
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import html
import json

# Опциональный импорт Telegram библиотеки
try:
    from telegram import (
        Update, 
        InlineKeyboardButton, 
        InlineKeyboardMarkup,
        BotCommand
    )
    from telegram.ext import (
        Application,
        CommandHandler,
        CallbackQueryHandler,
        MessageHandler,
        filters,
        ContextTypes
    )
    from telegram.constants import ParseMode
    from telegram.error import TelegramError
    
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    # Создаем заглушки для типов
    Update = None
    ContextTypes = None

from config.settings import get_settings


class TelegramBot:
    """Телеграм бот для торгового бота (опциональный)"""
    
    def __init__(self, token: str, chat_id: str, websocket_manager=None):
        self.token = token
        self.chat_id = chat_id
        self.websocket_manager = websocket_manager
        self.settings = get_settings()
        
        self.application = None
        self.is_running = False
        
        self.logger = logging.getLogger(__name__)
        
        # Проверяем доступность Telegram
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("⚠️ python-telegram-bot не установлен. Telegram бот недоступен.")
            return
        
        # Состояние бота
        self.notifications_enabled = True
        self.user_settings = {
            "notifications": True,
            "signal_types": ["BUY", "SELL"],
            "min_confidence": 0.7
        }
        
    async def start(self):
        """Запуск телеграм бота"""
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("⚠️ Telegram библиотека недоступна. Пропускаем запуск.")
            return
            
        try:
            self.logger.info("🤖 Запуск Telegram бота...")
            
            # Создание приложения
            self.application = Application.builder().token(self.token).build()
            
            # Регистрация обработчиков
            await self._register_handlers()
            
            # Установка команд меню
            await self._set_bot_commands()
            
            # Запуск бота
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.is_running = True
            
            # Приветственное сообщение
            await self.send_message(
                "🚀 <b>Торговый бот запущен!</b>\n\n"
                f"📊 Пара: {self.settings.TRADING_PAIR}\n"
                f"⏱ Таймфрейм: {self.settings.STRATEGY_TIMEFRAME}\n"
                f"🎯 Стратегия: RSI + MA\n\n"
                "Используйте /help для списка команд",
                reply_markup=self._get_main_keyboard()
            )
            
            self.logger.info("✅ Telegram бот запущен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска Telegram бота: {e}")
            raise
    
    async def stop(self):
        """Остановка телеграм бота"""
        if not TELEGRAM_AVAILABLE or not self.application:
            return
            
        try:
            self.logger.info("🛑 Остановка Telegram бота...")
            
            self.is_running = False
            
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            
            self.logger.info("✅ Telegram бот остановлен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка остановки Telegram бота: {e}")
    
    async def _register_handlers(self):
        """Регистрация обработчиков команд"""
        if not self.application:
            return
            
        # Команды
        self.application.add_handler(CommandHandler("start", self._cmd_start))
        self.application.add_handler(CommandHandler("help", self._cmd_help))
        self.application.add_handler(CommandHandler("status", self._cmd_status))
        self.application.add_handler(CommandHandler("market", self._cmd_market))
        self.application.add_handler(CommandHandler("signals", self._cmd_signals))
        self.application.add_handler(CommandHandler("settings", self._cmd_settings))
        self.application.add_handler(CommandHandler("strategy", self._cmd_strategy))
        
        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))
        
        # Обработчик текстовых сообщений
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
    
    async def _set_bot_commands(self):
        """Установка команд в меню бота"""
        if not self.application:
            return
            
        commands = [
            BotCommand("start", "🚀 Запуск бота"),
            BotCommand("help", "❓ Помощь"),
            BotCommand("status", "📊 Статус бота"),
            BotCommand("market", "📈 Рыночные данные"),
            BotCommand("signals", "🎯 Последние сигналы"),
            BotCommand("settings", "⚙️ Настройки"),
            BotCommand("strategy", "📊 Статус стратегии")
        ]
        
        await self.application.bot.set_my_commands(commands)
    
    def _get_main_keyboard(self):
        """Основная клавиатура"""
        if not TELEGRAM_AVAILABLE:
            return None
            
        keyboard = [
            [
                InlineKeyboardButton("📈 Узнать рынок", callback_data="market_info"),
                InlineKeyboardButton("📊 Статус", callback_data="bot_status")
            ],
            [
                InlineKeyboardButton("🎯 Сигналы", callback_data="recent_signals"),
                InlineKeyboardButton("📊 Стратегия", callback_data="strategy_status")
            ],
            [
                InlineKeyboardButton("⚙️ Настройки", callback_data="settings"),
                InlineKeyboardButton("❓ Помощь", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def _get_settings_keyboard(self):
        """Клавиатура настроек"""
        if not TELEGRAM_AVAILABLE:
            return None
            
        notifications_text = "🔔 Вкл" if self.user_settings["notifications"] else "🔕 Выкл"
        
        keyboard = [
            [
                InlineKeyboardButton(f"Уведомления: {notifications_text}", callback_data="toggle_notifications")
            ],
            [
                InlineKeyboardButton("📊 Типы сигналов", callback_data="signal_types"),
                InlineKeyboardButton("🎯 Мин. уверенность", callback_data="min_confidence")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # Обработчики команд (урезанная версия)
    async def _cmd_start(self, update, context):
        """Команда /start"""
        await update.message.reply_text(
            "🚀 <b>Добро пожаловать в торговый бот Bybit!</b>\n\n"
            f"📊 Торговая пара: <code>{self.settings.TRADING_PAIR}</code>\n"
            f"⏱ Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>\n"
            f"🎯 Стратегия: <b>RSI + Moving Average</b>\n\n"
            "Бот отправляет торговые сигналы на основе технического анализа.",
            parse_mode=ParseMode.HTML,
            reply_markup=self._get_main_keyboard()
        )
    
    async def _cmd_help(self, update, context):
        """Команда /help"""
        help_text = """
🆘 <b>Помощь по боту</b>

<b>Команды:</b>
/start - Запуск бота
/help - Эта справка
/status - Статус бота

<b>Торговые сигналы:</b>
• 🟢 <b>BUY</b> - Сигнал на покупку
• 🔴 <b>SELL</b> - Сигнал на продажу

⚠️ <b>Важно:</b> Сигналы носят информационный характер!
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)
    
    async def _cmd_status(self, update, context):
        """Команда /status"""
        status_text = f"""
📊 <b>Статус бота</b>

<b>Торговля:</b>
Пара: <code>{self.settings.TRADING_PAIR}</code>
Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>
Режим: <code>{'TESTNET' if self.settings.BYBIT_WS_TESTNET else 'MAINNET'}</code>

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
        """
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
    
    async def _cmd_market(self, update, context):
        """Команда /market"""
        await update.message.reply_text("📈 Рыночные данные временно недоступны")
    
    async def _cmd_signals(self, update, context):
        """Команда /signals"""
        await update.message.reply_text("🎯 Сигналы временно недоступны")
    
    async def _cmd_settings(self, update, context):
        """Команда /settings"""
        await update.message.reply_text("⚙️ Настройки временно недоступны")
    
    async def _cmd_strategy(self, update, context):
        """Команда /strategy"""
        await update.message.reply_text("📊 Статус стратегии временно недоступен")
    
    async def _handle_callback(self, update, context):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("🔄 Функция в разработке")
    
    async def _handle_message(self, update, context):
        """Обработка текстовых сообщений"""
        await update.message.reply_text(
            "🤔 Используйте /help для справки",
            reply_markup=self._get_main_keyboard()
        )
    
    # Отправка уведомлений
    async def send_signal_notification(self, signal_data: dict):
        """Отправка уведомления о торговом сигнале"""
        if not TELEGRAM_AVAILABLE:
            self.logger.info("📤 Telegram недоступен, сигнал пропущен")
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
            
            # Форматируем сообщение
            signal_emoji = "🟢" if signal_type == "BUY" else "🔴" if signal_type == "SELL" else "🔵"
            
            text = f"""
🚨 <b>ТОРГОВЫЙ СИГНАЛ!</b>

{signal_emoji} <b>{signal_type} {signal_data.get('symbol', '')}</b>

💰 <b>Цена:</b> <code>${signal_data.get('price', 0):.4f}</code>
🎯 <b>Уверенность:</b> <code>{confidence:.1%}</code>
⏰ <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}

💭 <b>Причина:</b> {signal_data.get('reason', 'Нет описания')}

⚠️ <i>Торгуйте ответственно!</i>
            """
            
            await self.send_message(text)
            self.logger.info(f"📤 Отправлено уведомление о сигнале: {signal_type}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки уведомления: {e}")
    
    async def send_message(self, text: str, reply_markup=None):
        """Отправка сообщения в чат"""
        if not TELEGRAM_AVAILABLE or not self.application:
            self.logger.info(f"📤 [Telegram недоступен] {text[:100]}...")
            return
            
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки сообщения Telegram: {e}")
