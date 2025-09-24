"""
ИИ анализатор рынка через OpenAI GPT-4
Исправлено: правильный сбор данных через get_comprehensive_market_data с pybit
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Добавить импорт
from pybit.unified_trading import HTTP as PybitHTTP

from config.settings import get_settings


class MarketAnalyzer:
    """ИИ анализатор рынка через OpenAI GPT-4 (исправленная версия с pybit)"""
    
    def __init__(self, websocket_manager=None):
        self.settings = get_settings()
        self.websocket_manager = websocket_manager
        self.logger = logging.getLogger(__name__)
        
        # OpenAI настройки
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = "gpt-4"
        self.max_tokens = 2000
        self.temperature = 0.3
        
        # Проверка доступности OpenAI
        if not OPENAI_AVAILABLE:
            self.logger.error("OpenAI библиотека не установлена")
            return
        
        if not self.api_key:
            self.logger.warning("OPENAI_API_KEY не установлен")
            return
        
        # Инициализация OpenAI клиента
        try:
            openai.api_key = self.api_key
            self.client = openai.OpenAI(api_key=self.api_key)
            self.logger.info("OpenAI клиент инициализирован")
        except Exception as e:
            self.logger.error(f"Ошибка инициализации OpenAI: {e}")
            self.client = None
    
    async def analyze_market(self, symbol: str = None) -> Tuple[Dict[str, Any], str]:
        """
        Полный анализ рынка через ИИ
        Возвращает: (market_data, ai_analysis)
        """
        try:
            if not OPENAI_AVAILABLE:
                error_msg = "OpenAI библиотека недоступна. Установите: pip install openai"
                self.logger.error(error_msg)
                return {}, error_msg
            
            if not self.client:
                error_msg = "OpenAI клиент не инициализирован. Проверьте OPENAI_API_KEY"
                return {}, error_msg
            
            # Шаг 1: Сбор всех рыночных данных
            self.logger.info(f"Начинаем сбор данных для анализа {symbol or 'текущего символа'}...")
            market_data = await self._collect_comprehensive_market_data(symbol)
            
            if not market_data:
                error_msg = "Не удалось собрать рыночные данные"
                self.logger.error(error_msg)
                return {}, error_msg
            
            # Проверяем качество собранных данных
            data_quality = self._assess_collected_data_quality(market_data)
            self.logger.info(f"Качество данных: {data_quality}")
            
            # Шаг 2: Формирование промпта для GPT-4
            prompt = self._create_analysis_prompt(market_data)
            self.logger.info(f"Промпт создан, длина: {len(prompt)} символов")
            
            # Шаг 3: Отправка запроса в OpenAI
            self.logger.info("Отправляем данные в GPT-4 для анализа...")
            ai_analysis = await self._get_ai_analysis(prompt)
            
            if not ai_analysis:
                error_msg = "Не удалось получить анализ от OpenAI"
                return market_data, error_msg
            
            self.logger.info("ИИ анализ успешно получен")
            return market_data, ai_analysis
            
        except Exception as e:
            error_msg = f"Ошибка анализа рынка: {str(e)}"
            self.logger.error(error_msg)
            return {}, error_msg
    
    async def _collect_comprehensive_market_data(self, symbol: str = None) -> Dict[str, Any]:
        """Сбор данных через pybit HTTP API"""
        try:
            if not self.websocket_manager:
                self.logger.error("WebSocket manager не инициализирован")
                return {}
            
            self.logger.info("Сбор данных через pybit HTTP API...")
            
            # Используем pybit HTTP клиент
            if hasattr(self.websocket_manager, 'http_client'):
                http_client = self.websocket_manager.http_client
            else:
                # Создаем временный клиент
                settings = get_settings()
                http_client = PybitHTTP(testnet=settings.BYBIT_WS_TESTNET)
            
            # Собираем данные через pybit (один запрос вместо множественных)
            symbol = symbol or self.settings.TRADING_PAIR
            
            # Данные уже доступны в websocket_manager
            comprehensive_data = await self.websocket_manager.get_comprehensive_market_data(symbol)
            
            if comprehensive_data:
                self.logger.info("✅ Comprehensive данные получены через pybit")
                return comprehensive_data
            else:
                self.logger.warning("Нет данных от pybit, используем fallback")
                return await self._collect_fallback_data(symbol)
                
        except Exception as e:
            self.logger.error(f"Ошибка сбора данных через pybit: {e}")
            return {}
    
    async def _collect_fallback_data(self, symbol: str = None) -> Dict[str, Any]:
        """Fallback сбор данных если comprehensive метод не работает"""
        try:
            self.logger.info("Используем fallback метод сбора данных...")
            
            # Базовые рыночные данные
            basic_market = self.websocket_manager.get_market_data(symbol)
            self.logger.info(f"Базовые данные: {bool(basic_market)}")
            
            # Данные стратегии
            strategy_data = {}
            if hasattr(self.websocket_manager, 'strategy') and self.websocket_manager.strategy:
                strategy_data = self.websocket_manager.strategy.get_current_data()
                self.logger.info(f"Данные стратегии: {len(strategy_data.get('current_indicators', {}))}")
            
            # Формируем структуру данных
            fallback_data = {
                "basic_market": basic_market or {},
                "technical_indicators": strategy_data.get('current_indicators', {}),
                "recent_klines": self._get_basic_klines_data(),
                "orderbook": self._get_basic_orderbook_data(),
                "recent_trades": self._get_basic_trades_data(),
                "market_stats": self._calculate_basic_stats(),
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol or self.websocket_manager.symbol,
                "timeframe": self.settings.STRATEGY_TIMEFRAME,
                "data_quality": {
                    "websocket_connected": True,
                    "data_delay": 0,
                    "klines_available": len(getattr(self.websocket_manager, 'kline_data', [])),
                    "indicators_calculated": len(strategy_data.get('current_indicators', {}))
                }
            }
            
            return fallback_data
            
        except Exception as e:
            self.logger.error(f"Ошибка fallback сбора данных: {e}")
            return {}
    
    def _get_basic_klines_data(self) -> List[Dict]:
        """Получить базовые данные свечей"""
        try:
            if not hasattr(self.websocket_manager, 'kline_data'):
                return []
            
            klines = self.websocket_manager.kline_data[-20:]  # Последние 20 свечей
            return [
                {
                    "timestamp": kline.get("timestamp", 0),
                    "open": kline.get("open", 0),
                    "high": kline.get("high", 0),
                    "low": kline.get("low", 0),
                    "close": kline.get("close", 0),
                    "volume": kline.get("volume", 0)
                }
                for kline in klines
            ]
        except Exception as e:
            self.logger.error(f"Ошибка получения klines: {e}")
            return []
    
    def _get_basic_orderbook_data(self) -> Dict:
        """Получить базовые данные ордербука"""
        try:
            if not hasattr(self.websocket_manager, 'orderbook_data'):
                return {}
            
            orderbook = self.websocket_manager.orderbook_data
            if not orderbook:
                return {}
            
            return {
                "bids": orderbook.get("bids", [])[:5],
                "asks": orderbook.get("asks", [])[:5],
                "spread": orderbook.get("spread", 0),
                "timestamp": orderbook.get("timestamp")
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения orderbook: {e}")
            return {}
    
    def _get_basic_trades_data(self) -> Dict:
        """Получить базовые данные сделок"""
        try:
            if not hasattr(self.websocket_manager, 'trade_data'):
                return {}
            
            trades = self.websocket_manager.trade_data[-50:]  # Последние 50 сделок
            if not trades:
                return {}
            
            buy_trades = [t for t in trades if t.get("side", "").upper() == "BUY"]
            sell_trades = [t for t in trades if t.get("side", "").upper() == "SELL"]
            
            return {
                "total_trades": len(trades),
                "buy_trades": len(buy_trades),
                "sell_trades": len(sell_trades),
                "latest_trades": trades[-10:] if trades else []
            }
        except Exception as e:
            self.logger.error(f"Ошибка получения trades: {e}")
            return {}
    
    def _calculate_basic_stats(self) -> Dict:
        """Вычислить базовую статистику"""
        try:
            if not hasattr(self.websocket_manager, 'kline_data'):
                return {}
            
            klines = self.websocket_manager.kline_data[-20:]
            if not klines:
                return {}
            
            closes = [k.get("close", 0) for k in klines]
            volumes = [k.get("volume", 0) for k in klines]
            
            return {
                "avg_price": sum(closes) / len(closes) if closes else 0,
                "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
                "price_range": max(closes) - min(closes) if closes else 0,
                "klines_analyzed": len(klines)
            }
        except Exception as e:
            self.logger.error(f"Ошибка вычисления статистики: {e}")
            return {}
    
    def _log_collected_data(self, data: Dict[str, Any]):
        """Логирование собранных данных"""
        try:
            self.logger.info("=== СОБРАННЫЕ ДАННЫЕ ===")
            self.logger.info(f"Basic market: {bool(data.get('basic_market'))}")
            
            basic_market = data.get('basic_market', {})
            if basic_market:
                self.logger.info(f"  Цена: {basic_market.get('price', 'N/A')}")
                self.logger.info(f"  Символ: {basic_market.get('symbol', 'N/A')}")
            
            indicators = data.get('technical_indicators', {})
            self.logger.info(f"Индикаторы: {len(indicators)}")
            if indicators:
                self.logger.info(f"  RSI: {indicators.get('rsi', 'N/A')}")
                self.logger.info(f"  SMA short: {indicators.get('sma_short', 'N/A')}")
            
            klines = data.get('recent_klines', [])
            self.logger.info(f"Свечи: {len(klines)}")
            
            orderbook = data.get('orderbook', {})
            self.logger.info(f"Ордербук: {bool(orderbook)}")
            
            trades = data.get('recent_trades', {})
            self.logger.info(f"Сделки: {trades.get('total_trades', 0) if isinstance(trades, dict) else len(trades)}")
            
        except Exception as e:
            self.logger.error(f"Ошибка логирования данных: {e}")
    
    def _assess_collected_data_quality(self, data: Dict[str, Any]) -> str:
        """Оценка качества собранных данных"""
        try:
            issues = []
            
            if not data:
                return "КРИТИЧНО: Нет данных"
            
            if not data.get('basic_market'):
                issues.append("Нет базовых рыночных данных")
            
            indicators = data.get('technical_indicators', {})
            if not indicators:
                issues.append("Нет технических индикаторов")
            
            klines = data.get('recent_klines', [])
            if not klines:
                issues.append("Нет данных свечей")
            elif len(klines) < 10:
                issues.append(f"Мало свечей: {len(klines)}")
            
            if issues:
                return f"ПРОБЛЕМЫ: {', '.join(issues)}"
            
            return "ХОРОШО: Все данные доступны"
            
        except Exception as e:
            return f"ОШИБКА: {e}"
    
    def _create_analysis_prompt(self, market_data: Dict) -> str:
        """Создание промпта для GPT-4 анализа - УЛУЧШЕННАЯ ВЕРСИЯ"""
        
        symbol = market_data.get("symbol", "UNKNOWN")
        timeframe = market_data.get("timeframe", "5m")
        
        # Извлекаем данные с проверками
        basic_market = market_data.get("basic_market", {})
        indicators = market_data.get("technical_indicators", {})
        klines = market_data.get("recent_klines", [])
        orderbook = market_data.get("orderbook", {})
        trades = market_data.get("recent_trades", {})
        stats = market_data.get("market_stats", {})
        
        # Проверяем наличие критически важных данных
        if not basic_market:
            return "ОШИБКА: Нет базовых рыночных данных для анализа"
        
        # Текущая цена
        current_price = basic_market.get('price', 'N/A')
        if current_price == 'N/A':
            return "ОШИБКА: Нет данных о текущей цене"
        
        prompt = f"""Ты профессиональный трейдер-аналитик фьючерсов с 15-летним опытом. Проведи ПОДРОБНЫЙ технический анализ для {symbol} на таймфрейме {timeframe}.

📊 РЫНОЧНЫЕ ДАННЫЕ:
Текущая цена: ${current_price}
Изменение 24ч: {basic_market.get('change_24h', 'N/A')}
Объем 24ч: {basic_market.get('volume_24h', 'N/A')}
Максимум 24ч: ${basic_market.get('high_24h', 'N/A')}
Минимум 24ч: ${basic_market.get('low_24h', 'N/A')}
Тренд: {basic_market.get('trend', 'N/A')}"""

        # Добавляем технические индикаторы если есть
        if indicators:
            prompt += f"""

📈 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:
RSI: {indicators.get('rsi', 'N/A')}
MA короткая ({self.settings.MA_SHORT_PERIOD}): {indicators.get('sma_short', 'N/A')}
MA длинная ({self.settings.MA_LONG_PERIOD}): {indicators.get('sma_long', 'N/A')}
EMA короткая: {indicators.get('ema_short', 'N/A')}
EMA длинная: {indicators.get('ema_long', 'N/A')}
MACD: {indicators.get('macd', 'N/A')}
MACD Signal: {indicators.get('signal', 'N/A')}
Bollinger Upper: {indicators.get('bb_upper', 'N/A')}
Bollinger Middle: {indicators.get('bb_middle', 'N/A')}
Bollinger Lower: {indicators.get('bb_lower', 'N/A')}"""

        # Добавляем данные ордербука если есть
        if orderbook and orderbook.get('bids'):
            prompt += f"""

📚 ОРДЕРБУК:
Лучший BID: ${orderbook.get('best_bid', orderbook.get('bids', [[0]])[0][0] if orderbook.get('bids') else 'N/A')}
Лучший ASK: ${orderbook.get('best_ask', orderbook.get('asks', [[0]])[0][0] if orderbook.get('asks') else 'N/A')}
Спред: ${orderbook.get('spread', 'N/A')}"""

        # Добавляем данные о сделках если есть
        if trades and isinstance(trades, dict) and trades.get('total_trades'):
            prompt += f"""

💹 АНАЛИЗ СДЕЛОК:
Всего сделок: {trades.get('total_trades', 'N/A')}
Покупки: {trades.get('buy_trades', 'N/A')}
Продажи: {trades.get('sell_trades', 'N/A')}"""

        # Добавляем данные свечей если есть
        if klines and len(klines) >= 5:
            recent_closes = [k.get('close', 0) for k in klines[-5:]]
            prompt += f"""

🕯️ ПОСЛЕДНИЕ СВЕЧИ (закрытие):
{[f"${price:.2f}" for price in recent_closes if price > 0]}
Всего свечей проанализировано: {len(klines)}"""

        # Добавляем статистику если есть
        if stats:
            prompt += f"""

📊 СТАТИСТИКА:
Средняя цена: ${stats.get('avg_price', 'N/A')}
Средний объем: {stats.get('avg_volume', 'N/A')}
Ценовой диапазон: ${stats.get('price_range', 'N/A')}"""

        prompt += f"""

ЗАДАЧА: Проведи ГЛУБОКИЙ технический анализ и дай КОНКРЕТНЫЕ рекомендации для фьючерсной торговли:

1. 📊 ТЕХНИЧЕСКИЙ АНАЛИЗ:
   - Анализ всех доступных индикаторов
   - Определение тренда (краткосрочный, среднесрочный)
   - Уровни поддержки и сопротивления
   - Анализ объемов и активности

2. 🎯 ТОРГОВЫЕ РЕКОМЕНДАЦИИ:
   - Рекомендация: BUY/SELL/HOLD с обоснованием
   - Точка входа (конкретная цена)
   - STOP LOSS (конкретная цена и % от входа)
   - TAKE PROFIT уровни (TP1, TP2, TP3 с ценами)
   - Размер позиции (% от депозита)

3. 📈 ПРОГНОЗ:
   - Краткосрочный прогноз (1-4 часа)
   - Среднесрочный прогноз (1-3 дня)
   - Ключевые уровни для наблюдения
   - Возможные сценарии развития

4. ⚠️ РИСКИ:
   - Основные риски позиции
   - Уровни ликвидации
   - События, которые могут повлиять на цену

Отвечай СТРУКТУРИРОВАННО с эмодзи, будь КОНКРЕТНЫМ в ценах и процентах. Это реальная торговля фьючерсами!

ВРЕМЯ АНАЛИЗА: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

        return prompt
    
    async def _get_ai_analysis(self, prompt: str) -> str:
        """Получение анализа от OpenAI GPT-4"""
        try:
            if not self.client:
                return "OpenAI клиент не инициализирован"
            
            # Проверяем промпт
            if "ОШИБКА:" in prompt:
                return prompt
            
            # Создаем запрос к GPT-4
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Ты опытный трейдер-аналитик фьючерсов. Отвечай структурированно, с конкретными цифрами и рекомендациями."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )
            )
            
            if response and response.choices:
                analysis = response.choices[0].message.content
                self.logger.info(f"Получен анализ от GPT-4 ({len(analysis)} символов)")
                return analysis
            else:
                return "Пустой ответ от OpenAI"
                
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"Ошибка запроса к OpenAI: {error_msg}")
            
            # Специфичные ошибки OpenAI
            if "invalid api key" in error_msg.lower():
                return "НЕВЕРНЫЙ OPENAI_API_KEY! Проверьте ключ в настройках."
            elif "insufficient_quota" in error_msg.lower():
                return "Превышен лимит OpenAI API. Проверьте баланс аккаунта."
            elif "rate_limit" in error_msg.lower():
                return "Превышен лимит запросов OpenAI. Попробуйте позже."
            else:
                return f"Ошибка OpenAI API: {error_msg}"
    
    def format_market_data_message(self, market_data: Dict) -> str:
        """Форматирование рыночных данных для телеграма"""
        try:
            basic_market = market_data.get("basic_market", {})
            indicators = market_data.get("technical_indicators", {})
            orderbook = market_data.get("orderbook", {})
            trades = market_data.get("recent_trades", {})
            
            symbol = market_data.get("symbol", "UNKNOWN")
            
            # Определяем тренд по изменению
            change_24h = basic_market.get("change_24h", "0%")
            if isinstance(change_24h, str) and "%" in change_24h:
                try:
                    change_value = float(change_24h.replace("%", "").replace("+", ""))
                    trend_emoji = "🚀" if change_value > 2 else "📈" if change_value > 0 else "📉" if change_value < -2 else "➡️"
                except:
                    trend_emoji = "📊"
            else:
                trend_emoji = "📊"
            
            # RSI состояние
            rsi = indicators.get("rsi", 50) if indicators else 50
            rsi_emoji = "🔥" if rsi > 70 else "❄️" if rsi < 30 else "⚖️"
            
            message = f"""
📊 РЫНОЧНЫЕ ДАННЫЕ - {symbol} {trend_emoji}

💰 Цена: ${basic_market.get('price', 'N/A')}
📈 Изменение 24ч: {basic_market.get('change_24h', 'N/A')}
📊 Объем 24ч: {basic_market.get('volume_24h', 'N/A')}

🔝 Максимум 24ч: ${basic_market.get('high_24h', 'N/A')}
🔻 Минимум 24ч: ${basic_market.get('low_24h', 'N/A')}"""

            if indicators:
                message += f"""

📊 ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:
{rsi_emoji} RSI: {rsi:.1f}
📈 MA короткая: {indicators.get('sma_short', 0):.2f}
📉 MA длинная: {indicators.get('sma_long', 0):.2f}"""

            if orderbook:
                message += f"""

📚 ОРДЕРБУК:
💚 Лучший BID: ${orderbook.get('best_bid', orderbook.get('bids', [[0]])[0][0] if orderbook.get('bids') else 0):.4f}
❤️ Лучший ASK: ${orderbook.get('best_ask', orderbook.get('asks', [[0]])[0][0] if orderbook.get('asks') else 0):.4f}
⚡ Спред: ${orderbook.get('spread', 0):.4f}"""

            if trades and isinstance(trades, dict):
                message += f"""

💹 АКТИВНОСТЬ:
🔄 Сделок: {trades.get('total_trades', 0)}
📊 Покупки/Продажи: {trades.get('buy_trades', 0)}/{trades.get('sell_trades', 0)}"""

            message += f"""

🕐 Данные на {datetime.now().strftime('%H:%M:%S')}
            """
            
            return message.strip()
            
        except Exception as e:
            self.logger.error(f"Ошибка форматирования данных: {e}")
            return f"Ошибка форматирования рыночных данных: {e}"
    
    def get_status(self) -> Dict:
        """Получить статус анализатора"""
        return {
            "openai_available": OPENAI_AVAILABLE,
            "api_key_configured": bool(self.api_key),
            "client_initialized": self.client is not None,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "websocket_manager": self.websocket_manager is not None,
            "websocket_connected": self.websocket_manager.is_connected if self.websocket_manager else False
        }
