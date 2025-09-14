"""
Телеграм бот для торговых уведомлений и управления
Обработка команд, кнопок и отправка сигналов
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import html
import json

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

from config.settings import get_settings


class TelegramBot:
    """Телеграм бот для торгового бота"""
    
    def __init__(self, token: str, chat_id: str, websocket_manager=None):
        self.token = token
        self.chat_id = chat_id
        self.websocket_manager = websocket_manager
        self.settings = get_settings()
        
        self.application = None
        self.is_running = False
        
        self.logger = logging.getLogger(__name__)
        
        # Состояние бота
        self.notifications_enabled = True
        self.user_settings = {
            "notifications": True,
            "signal_types": ["BUY", "SELL"],
            "min_confidence": 0.7
        }
        
    async def start(self):
        """Запуск телеграм бота"""
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
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        await update.message.reply_text(
            "🚀 <b>Добро пожаловать в торговый бот Bybit!</b>\n\n"
            f"📊 Торговая пара: <code>{self.settings.TRADING_PAIR}</code>\n"
            f"⏱ Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>\n"
            f"🎯 Стратегия: <b>RSI + Moving Average</b>\n\n"
            "Бот отправляет торговые сигналы на основе технического анализа.\n\n"
            "<i>Используйте кнопки ниже для управления:</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=self._get_main_keyboard()
        )
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /help"""
        help_text = """
🆘 <b>Помощь по боту</b>

<b>Команды:</b>
/start - Запуск бота
/help - Эта справка
/status - Статус бота
/market - Рыночные данные
/signals - Последние сигналы
/settings - Настройки уведомлений
/strategy - Статус стратегии

<b>Кнопки:</b>
📈 <b>Узнать рынок</b> - Текущие рыночные данные
📊 <b>Статус</b> - Статус работы бота
🎯 <b>Сигналы</b> - Последние торговые сигналы
📊 <b>Стратегия</b> - Информация о стратегии
⚙️ <b>Настройки</b> - Настройки уведомлений

<b>Торговые сигналы:</b>
• 🟢 <b>BUY</b> - Сигнал на покупку
• 🔴 <b>SELL</b> - Сигнал на продажу
• Уверенность показывает надежность сигнала (0-100%)

<b>Стратегия:</b>
RSI + Moving Average - классическая стратегия технического анализа
• RSI определяет перекупленность/перепроданность
• MA показывает направление тренда

⚠️ <b>Важно:</b> Сигналы носят информационный характер. Торгуйте ответственно!
        """
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.HTML,
            reply_markup=self._get_main_keyboard()
        )
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /status"""
        try:
            # Получаем статус от WebSocket менеджера
            if self.websocket_manager:
                connection_status = self.websocket_manager.get_connection_status()
                ws_status = "🟢 Подключен" if connection_status["is_connected"] else "🔴 Отключен"
                data_delay = connection_status.get("data_delay", 0)
                
                if data_delay > 60:
                    data_status = f"⚠️ Задержка {data_delay:.0f}с"
                elif data_delay > 10:
                    data_status = f"🟡 Задержка {data_delay:.0f}с"
                else:
                    data_status = "🟢 Актуально"
            else:
                ws_status = "🔴 Не инициализирован"
                data_status = "❌ Нет данных"
            
            status_text = f"""
📊 <b>Статус бота</b>

<b>Соединения:</b>
WebSocket: {ws_status}
Данные: {data_status}
Telegram: 🟢 Активен

<b>Торговля:</b>
Пара: <code>{self.settings.TRADING_PAIR}</code>
Таймфрейм: <code>{self.settings.STRATEGY_TIMEFRAME}</code>
Режим: <code>{'TESTNET' if self.settings.BYBIT_WS_TESTNET else 'MAINNET'}</code>

<b>Уведомления:</b>
Статус: {'🔔 Включены' if self.user_settings['notifications'] else '🔕 Отключены'}
Типы: {', '.join(self.user_settings['signal_types'])}
Мин. уверенность: {self.user_settings['min_confidence']:.0%}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="bot_status"),
                    InlineKeyboardButton("📈 Рынок", callback_data="market_info")
                ],
                [
                    InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
                ]
            ]
            
            await update.message.reply_text(
                status_text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка получения статуса: {e}")
    
    async def _cmd_market(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /market"""
        await self._send_market_info(update.message.chat_id)
    
    async def _cmd_signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /signals"""
        await self._send_recent_signals(update.message.chat_id)
    
    async def _cmd_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    async def _cmd_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /strategy"""
        await self._send_strategy_status(update.message.chat_id)
    
    # Обработчик кнопок
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий на кнопки"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        try:
            if data == "main_menu":
                await query.edit_message_text(
                    "🏠 <b>Главное меню</b>\n\nВыберите действие:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._get_main_keyboard()
                )
            
            elif data == "market_info":
                await self._send_market_info(query.message.chat_id, edit_message=True, message_id=query.message.message_id)
            
            elif data == "bot_status":
                await self._send_bot_status(query.message.chat_id, edit_message=True, message_id=query.message.message_id)
            
            elif data == "recent_signals":
                await self._send_recent_signals(query.message.chat_id, edit_message=True, message_id=query.message.message_id)
            
            elif data == "strategy_status":
                await self._send_strategy_status(query.message.chat_id, edit_message=True, message_id=query.message.message_id)
            
            elif data == "settings":
                await query.edit_message_text(
                    f"⚙️ <b>Настройки бота</b>\n\n"
                    f"<b>Уведомления:</b> {'🔔 Включены' if self.user_settings['notifications'] else '🔕 Отключены'}\n"
                    f"<b>Типы сигналов:</b> {', '.join(self.user_settings['signal_types'])}\n"
                    f"<b>Мин. уверенность:</b> {self.user_settings['min_confidence']:.0%}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._get_settings_keyboard()
                )
            
            elif data == "toggle_notifications":
                self.user_settings["notifications"] = not self.user_settings["notifications"]
                status = "включены" if self.user_settings["notifications"] else "отключены"
                
                await query.edit_message_text(
                    f"⚙️ <b>Настройки бота</b>\n\n"
                    f"✅ Уведомления {status}!\n\n"
                    f"<b>Уведомления:</b> {'🔔 Включены' if self.user_settings['notifications'] else '🔕 Отключены'}\n"
                    f"<b>Типы сигналов:</b> {', '.join(self.user_settings['signal_types'])}\n"
                    f"<b>Мин. уверенность:</b> {self.user_settings['min_confidence']:.0%}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._get_settings_keyboard()
                )
            
            elif data == "help":
                await self._cmd_help(update, context)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки callback: {e}")
            await query.edit_message_text(f"❌ Произошла ошибка: {e}")
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                "🤔 Не понял команду. Используйте /help для справки или кнопки ниже:",
                reply_markup=self._get_main_keyboard()
            )
    
    # Отправка информации
    async def _send_market_info(self, chat_id: int, edit_message: bool = False, message_id: int = None):
        """Отправка рыночной информации"""
        try:
            if self.websocket_manager:
                market_data = self.websocket_manager.get_market_data()
            else:
                market_data = {}
            
            if market_data:
                trend_emoji = {"bullish": "📈", "bearish": "📉", "sideways": "➡️"}.get(market_data.get("trend", "sideways"), "➡️")
                
                text = f"""
📈 <b>Рыночные данные - {market_data.get('symbol', 'N/A')}</b>

💰 <b>Цена:</b> <code>${market_data.get('price', 'N/A')}</code>
📊 <b>Изменение 24ч:</b> <code>{market_data.get('change_24h', 'N/A')}</code>
📈 <b>Макс 24ч:</b> <code>${market_data.get('high_24h', 'N/A')}</code>
📉 <b>Мин 24ч:</b> <code>${market_data.get('low_24h', 'N/A')}</code>
💹 <b>Объем 24ч:</b> <code>{market_data.get('volume_24h', 'N/A')}</code>

🎯 <b>Bid:</b> <code>${market_data.get('bid', 'N/A')}</code>
🎯 <b>Ask:</b> <code>${market_data.get('ask', 'N/A')}</code>
📏 <b>Спред:</b> <code>${market_data.get('spread', 'N/A')}</code>

{trend_emoji} <b>Тренд:</b> {market_data.get('trend', 'N/A').title()}

<i>🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
                """
            else:
                text = "❌ Нет данных о рынке. Проверьте соединение WebSocket."
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="market_info"),
                    InlineKeyboardButton("🎯 Сигналы", callback_data="recent_signals")
                ],
                [
                    InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
                ]
            ]
            
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await self.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
                
        except Exception as e:
            error_text = f"❌ Ошибка получения рыночных данных: {e}"
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=error_text
                )
            else:
                await self.send_message(error_text)
    
    async def _send_recent_signals(self, chat_id: int, edit_message: bool = False, message_id: int = None):
        """Отправка последних сигналов"""
        try:
            # Получаем сигналы от стратегии через WebSocket менеджер
            if self.websocket_manager and self.websocket_manager.strategy:
                signals = self.websocket_manager.strategy.get_recent_signals(limit=5)
            else:
                signals = []
            
            if signals:
                text = "🎯 <b>Последние торговые сигналы:</b>\n\n"
                
                for i, signal in enumerate(reversed(signals), 1):
                    signal_emoji = "🟢" if signal['signal_type'] == "BUY" else "🔴"
                    confidence_percent = signal['confidence'] * 100
                    
                    signal_time = datetime.fromisoformat(signal['timestamp'].replace('Z', '+00:00')) if isinstance(signal['timestamp'], str) else signal['timestamp']
                    time_str = signal_time.strftime('%H:%M:%S')
                    
                    text += f"{i}. {signal_emoji} <b>{signal['signal_type']}</b> @ <code>${signal['price']:.4f}</code>\n"
                    text += f"   🎯 Уверенность: <b>{confidence_percent:.1f}%</b>\n"
                    text += f"   ⏰ Время: {time_str}\n"
                    text += f"   💭 Причина: {signal['reason'][:50]}...\n\n"
                
                text += f"<i>Всего сигналов сегодня: {len(signals)}</i>"
            else:
                text = "📭 <b>Нет недавних сигналов</b>\n\nСигналы появятся после анализа рыночных данных."
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="recent_signals"),
                    InlineKeyboardButton("📊 Стратегия", callback_data="strategy_status")
                ],
                [
                    InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
                ]
            ]
            
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await self.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
                
        except Exception as e:
            error_text = f"❌ Ошибка получения сигналов: {e}"
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=error_text
                )
            else:
                await self.send_message(error_text)
    
    async def _send_strategy_status(self, chat_id: int, edit_message: bool = False, message_id: int = None):
        """Отправка статуса стратегии"""
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
Текущая цена: <code>${indicators.get('current_price', 0):.4f}</code>

<b>Настройки:</b>
RSI период: {status['settings']['rsi_period']}
RSI уровни: {status['settings']['rsi_oversold']}/{status['settings']['rsi_overbought']}
MA периоды: {status['settings']['ma_short']}/{status['settings']['ma_long']}
Мин. уверенность: {status['settings']['min_confidence']:.0%}

<i>Обновлено: {datetime.now().strftime('%H:%M:%S')}</i>
                """
            else:
                text = "❌ Стратегия не инициализирована"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Обновить", callback_data="strategy_status"),
                    InlineKeyboardButton("🎯 Сигналы", callback_data="recent_signals")
                ],
                [
                    InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")
                ]
            ]
            
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await self.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
                
        except Exception as e:
            error_text = f"❌ Ошибка получения статуса стратегии: {e}"
            if edit_message and message_id:
                await self.application.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=error_text
                )
            else:
                await self.send_message(error_text)
    
    async def _send_bot_status(self, chat_id: int, edit_message: bool = False, message_id: int = None):
        """Отправка статуса бота"""
        # Аналогично _cmd_status, но для callback
        await self._send_market_info(chat_id, edit_message, message_id)  # Временно показываем рыночные данные
    
    # Отправка уведомлений
    async def send_signal_notification(self, signal_data: dict):
        """Отправка уведомления о торговом сигнале"""
        try:
            if not self.user_settings["notifications"]:
                return
            
            # Проверяем тип сигнала
            signal_type = signal_data.get("signal_type", "")
            if signal_type not in self.user_settings["signal_types"]:
                return
            
            # Проверяем уверенность
            confidence = signal_data.get("confidence", 0)
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

💭 <b>Причина:</b>
{signal_data.get('reason', 'Нет описания')}

<b>Индикаторы:</b>
RSI: <code>{signal_data.get('indicators', {}).get('rsi', 0):.1f}</code>
MA: <code>{signal_data.get('indicators', {}).get('sma_short', 0):.2f}/{signal_data.get('indicators', {}).get('sma_long', 0):.2f}</code>

⚠️ <i>Торгуйте ответственно!</i>
            """
            
            keyboard = [
                [
                    InlineKeyboardButton("📈 Узнать рынок", callback_data="market_info"),
                    InlineKeyboardButton("🎯 Все сигналы", callback_data="recent_signals")
                ]
            ]
            
            await self.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
            
            self.logger.info(f"📤 Отправлено уведомление о сигнале: {signal_type} {signal_data.get('symbol', '')}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки уведомления: {e}")
    
    async def send_message(self, text: str, reply_markup=None):
        """Отправка сообщения в чат"""
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except TelegramError as e:
            self.logger.error(f"❌ Ошибка отправки сообщения Telegram: {e}")
        except Exception as e:
            self.logger.error(f"❌ Неожиданная ошибка отправки: {e}")
