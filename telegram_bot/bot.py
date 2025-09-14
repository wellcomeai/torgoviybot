"""
Телеграм бот для торговых уведомлений и управления
Обработка команд, кнопок и отправка сигналов (исправленная детекция)
"""

import asyncio
import logging
from datetime import datetime
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
        from telegram.error import TelegramError
    except ImportError as e:
        TELEGRAM_AVAILABLE = False
        telegram_import_error = str(e)

from config.settings import get_settings


class TelegramBot:
    """Телеграм бот для торгового бота (исправленная детекция)"""
    
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
            self.logger.warning(f"⚠️ Telegram библиотека недоступна: {telegram_import_error}")
            return
        
        self.logger.info("✅ Telegram библиотека обнаружена успешно")
        
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
            
        if not self.token or not self.chat_id:
            self.logger.warning("⚠️ TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не указаны")
            return
            
        try:
            self.logger.info("🤖 Запуск Telegram бота...")
            self.logger.info(f"   Token: {self.token[:10]}...")
            self.logger.info(f"   Chat ID: {self.chat_id}")
            
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
            
            self.logger.info("✅ Telegram бот успешно запущен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска Telegram бота: {e}")
            # Не поднимаем исключение, чтобы не сломать весь бот
    
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
    
    # Обработчики команд
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
/market - Рыночные данные
/signals - Последние сигналы

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

<b>WebSocket:</b> {'🟢 Подключен' if self.websocket_manager and self.websocket_manager.is_connected else '🔴 Отключен'}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
        """
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)
    
    async def _cmd_market(self, update, context):
        """Команда /market"""
        try:
            if self.websocket_manager:
                market_data = self.websocket_manager.get_market_data()
                if market_data:
                    trend_emoji = {"bullish": "📈", "bearish": "📉", "sideways": "➡️"}.get(market_data.get("trend", "sideways"), "➡️")
                    
                    text = f"""
📈 <b>Рыночные данные - {market_data.get('symbol', 'N/A')}</b>

💰 <b>Цена:</b> <code>${market_data.get('price', 'N/A')}</code>
📊 <b>Изменение 24ч:</b> <code>{market_data.get('change_24h', 'N/A')}</code>
📈 <b>Макс 24ч:</b> <code>${market_data.get('high_24h', 'N/A')}</code>
📉 <b>Мин 24ч:</b> <code>${market_data.get('low_24h', 'N/A')}</code>
💹 <b>Объем 24ч:</b> <code>{market_data.get('volume_24h', 'N/A')}</code>

{trend_emoji} <b>Тренд:</b> {market_data.get('trend', 'N/A').title()}

<i>🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
                    """
                    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                    return
            
            await update.message.reply_text("❌ Рыночные данные временно недоступны")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка получения данных: {e}")
    
    async def _cmd_signals(self, update, context):
        """Команда /signals"""
        try:
            if self.websocket_manager and self.websocket_manager.strategy:
                signals = self.websocket_manager.strategy.get_recent_signals(limit=5)
                
                if signals:
                    text = "🎯 <b>Последние торговые сигналы:</b>\n\n"
                    
                    for i, signal in enumerate(reversed(signals), 1):
                        signal_emoji = "🟢" if signal['signal_type'] == "BUY" else "🔴"
                        confidence_percent = signal['confidence'] * 100
                        
                        signal_time = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00')) if isinstance(signal['timestamp'], str) else signal['timestamp']
                        time_str = signal_time.strftime('%H:%M:%S')
                        
                        text += f"{i}. {signal_emoji} <b>{signal['signal_type']}</b> @ <code>${signal['price']:.4f}</code>\n"
                        text += f"   🎯 Уверенность: <b>{confidence_percent:.1f}%</b>\n"
                        text += f"   ⏰ Время: {time_str}\n\n"
                    
                    text += f"<i>Всего сигналов: {len(signals)}</i>"
                    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                    return
            
            await update.message.reply_text("📭 <b>Нет недавних сигналов</b>\n\nСигналы появятся после анализа рыночных данных.", parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка получения сигналов: {e}")
    
    async def _cmd_settings(self, update, context):
        """Команда /settings"""
        settings_text = f"""
⚙️ <b>Настройки бота</b>

<b>Уведомления:</b> {'🔔 Включены' if self.user_settings['notifications'] else '🔕 Отключены'}
<b>Типы сигналов:</b> {', '.join(self.user_settings['signal_types'])}
<b>Мин. уверенность:</b> {self.user_settings['min_confidence']:.0%}

Используйте кнопки ниже для изменения настроек:
        """
        
        await update.message.reply_text(
            settings_text,
            parse_mode=ParseMode.HTML,
            reply_markup=self._get_settings_keyboard()
        )
    
    async def _cmd_strategy(self, update, context):
        """Команда /strategy"""
        try:
            if self.websocket_manager and self.websocket_manager.strategy:
                status = self.websocket_manager.strategy.get_status()
                current_data = self.websocket_manager.strategy.get_current_data()
                indicators = current_data.get('current_indicators', {})
                
                text = f"""
📊 <b>Статус стратегии</b>

<b>Основное:</b>
Стратегия: {status['strategy_name']}
Пара: <code>{status['symbol']}</code>
Таймфрейм: <code>{status['timeframe']}</code>
Статус: {'🟢 Активна' if status['is_active'] else '🔴 Неактивна'}

<b>Данные:</b>
Точек данных: {status['data_points']}
Всего сигналов: {status['total_signals']}
Сигналов сегодня: {status['signals_today']}

<b>Текущие индикаторы:</b>
RSI: <code>{indicators.get('rsi', 0):.1f}</code>
MA короткая: <code>{indicators.get('sma_short', 0):.2f}</code>
MA длинная: <code>{indicators.get('sma_long', 0):.2f}</code>

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
                """
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                return
            
            await update.message.reply_text("❌ Стратегия не инициализирована")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка получения статуса стратегии: {e}")
    
    async def _handle_callback(self, update, context):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "toggle_notifications":
            self.user_settings["notifications"] = not self.user_settings["notifications"]
            status = "включены" if self.user_settings["notifications"] else "отключены"
            
            await query.edit_message_text(
                f"⚙️ <b>Настройки бота</b>\n\n"
                f"✅ Уведомления {status}!\n\n"
                f"<b>Уведомления:</b> {'🔔 Включены' if self.user_settings['notifications'] else '🔕 Отключены'}",
                parse_mode=ParseMode.HTML,
                reply_markup=self._get_settings_keyboard()
            )
        else:
            await query.edit_message_text("🔄 Функция в разработке")
    
    async def _handle_message(self, update, context):
        """Обработка текстовых сообщений"""
        text = update.message.text.lower()
        
        if "статус" in text or "status" in text:
            await self._cmd_status(update, context)
        elif "рынок" in text or "market" in text:
            await self._cmd_market(update, context)
        elif "сигнал" in text or "signal" in text:
            await self._cmd_signals(update, context)
        else:
            await update.message.reply_text(
                "🤔 Используйте /help для справки или команды:\n"
                "/status - статус бота\n"
                "/market - рыночные данные\n"
                "/signals - последние сигналы",
                reply_markup=self._get_main_keyboard()
            )
    
    # Отправка уведомлений
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
            
            # Форматируем сообщение
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
