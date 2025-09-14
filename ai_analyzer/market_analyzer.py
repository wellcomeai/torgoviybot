"""
ИИ анализатор рынка через OpenAI GPT-4
Подробный технический анализ фьючерсов с прогнозами и уровнями TP/SL
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

from config.settings import get_settings


class MarketAnalyzer:
    """ИИ анализатор рынка через OpenAI GPT-4"""
    
    def __init__(self, websocket_manager=None):
        self.settings = get_settings()
        self.websocket_manager = websocket_manager
        self.logger = logging.getLogger(__name__)
        
        # OpenAI настройки
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = "gpt-4"
        self.max_tokens = 2000
        self.temperature = 0.3  # Более консервативная температура для финансового анализа
        
        # Проверка доступности OpenAI
        if not OPENAI_AVAILABLE:
            self.logger.error("❌ OpenAI библиотека не установлена")
            return
        
        if not self.api_key:
            self.logger.warning("⚠️ OPENAI_API_KEY не установлен")
            return
        
        # Инициализация OpenAI клиента
        try:
            openai.api_key = self.api_key
            self.client = openai.OpenAI(api_key=self.api_key)
            self.logger.info("✅ OpenAI клиент инициализирован")
        except Exception as e:
            self.logger.error(f"❌ Ошибка инициализации OpenAI: {e}")
            self.client = None
    
    async def analyze_market(self, symbol: str = None) -> Tuple[Dict[str, Any], str]:
        """
        Полный анализ рынка через ИИ
        Возвращает: (market_data, ai_analysis)
        """
        try:
            if not OPENAI_AVAILABLE:
                error_msg = "❌ OpenAI библиотека недоступна. Установите: pip install openai"
                self.logger.error(error_msg)
                return {}, error_msg
            
            if not self.client:
                error_msg = "❌ OpenAI клиент не инициализирован. Проверьте OPENAI_API_KEY"
                return {}, error_msg
            
            # Шаг 1: Сбор всех рыночных данных
            self.logger.info(f"🔍 Начинаем сбор данных для анализа {symbol or 'текущего символа'}...")
            market_data = await self._collect_comprehensive_market_data(symbol)
            
            if not market_data:
                error_msg = "❌ Не удалось собрать рыночные данные"
                return {}, error_msg
            
            # Шаг 2: Формирование промпта для GPT-4
            prompt = self._create_analysis_prompt(market_data)
            
            # Шаг 3: Отправка запроса в OpenAI
            self.logger.info("🤖 Отправляем данные в GPT-4 для анализа...")
            ai_analysis = await self._get_ai_analysis(prompt)
            
            if not ai_analysis:
                error_msg = "❌ Не удалось получить анализ от OpenAI"
                return market_data, error_msg
            
            self.logger.info("✅ ИИ анализ успешно получен")
            return market_data, ai_analysis
            
        except Exception as e:
            error_msg = f"❌ Ошибка анализа рынка: {str(e)}"
            self.logger.error(error_msg)
            return {}, error_msg
    
    async def _collect_comprehensive_market_data(self, symbol: str = None) -> Dict[str, Any]:
        """Сбор всех доступных рыночных данных"""
        try:
            if not self.websocket_manager:
                return {}
            
            # Базовые рыночные данные
            market_data = self.websocket_manager.get_market_data(symbol)
            
            # Расширенные данные из WebSocket менеджера
            ws_status = self.websocket_manager.get_connection_status()
            
            # Собираем данные стратегии
            strategy_data = {}
            if hasattr(self.websocket_manager, 'strategy') and self.websocket_manager.strategy:
                strategy_data = self.websocket_manager.strategy.get_current_data()
            
            # Формируем полный набор данных
            comprehensive_data = {
                # Основные рыночные данные
                "basic_market": market_data,
                
                # Технические индикаторы
                "technical_indicators": strategy_data.get('current_indicators', {}),
                
                # Данные свечей (последние 50)
                "recent_klines": self._get_recent_klines_data(),
                
                # Ордербук данные
                "orderbook": self._get_orderbook_summary(),
                
                # Данные о сделках
                "recent_trades": self._get_recent_trades_summary(),
                
                # Волатильность и статистика
                "market_stats": self._calculate_market_statistics(),
                
                # Временные метки
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol or self.websocket_manager.symbol,
                "timeframe": self.settings.STRATEGY_TIMEFRAME,
                
                # Статус подключения
                "data_quality": {
                    "websocket_connected": ws_status.get("is_connected", False),
                    "data_delay": ws_status.get("data_delay", 0),
                    "klines_available": strategy_data.get('klines_count', 0),
                    "indicators_calculated": len(strategy_data.get('current_indicators', {}))
                }
            }
            
            return comprehensive_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора рыночных данных: {e}")
            return {}
    
    def _get_recent_klines_data(self) -> List[Dict]:
        """Получить данные последних свечей"""
        try:
            if not hasattr(self.websocket_manager, 'kline_data'):
                return []
            
            klines = self.websocket_manager.kline_data[-50:]  # Последние 50 свечей
            
            formatted_klines = []
            for kline in klines:
                formatted_klines.append({
                    "timestamp": kline.get("timestamp", 0),
                    "open": kline.get("open", 0),
                    "high": kline.get("high", 0),
                    "low": kline.get("low", 0),
                    "close": kline.get("close", 0),
                    "volume": kline.get("volume", 0)
                })
            
            return formatted_klines
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения данных свечей: {e}")
            return []
    
    def _get_orderbook_summary(self) -> Dict:
        """Получить сводку ордербука"""
        try:
            if not hasattr(self.websocket_manager, 'orderbook_data'):
                return {}
            
            orderbook = self.websocket_manager.orderbook_data
            
            if not orderbook:
                return {}
            
            bids = orderbook.get("bids", [])[:10]  # Топ 10 bid'ов
            asks = orderbook.get("asks", [])[:10]  # Топ 10 ask'ов
            
            # Вычисляем спред и глубину рынка
            spread = 0
            if bids and asks:
                best_bid = float(bids[0][0]) if bids[0] else 0
                best_ask = float(asks[0][0]) if asks[0] else 0
                spread = best_ask - best_bid
            
            # Общий объем в ордербуке
            total_bid_volume = sum(float(bid[1]) for bid in bids if len(bid) > 1)
            total_ask_volume = sum(float(ask[1]) for ask in asks if len(ask) > 1)
            
            return {
                "spread": spread,
                "best_bid": float(bids[0][0]) if bids and bids[0] else 0,
                "best_ask": float(asks[0][0]) if asks and asks[0] else 0,
                "total_bid_volume": total_bid_volume,
                "total_ask_volume": total_ask_volume,
                "bid_ask_ratio": total_bid_volume / total_ask_volume if total_ask_volume > 0 else 0,
                "top_bids": bids[:5],
                "top_asks": asks[:5]
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа ордербука: {e}")
            return {}
    
    def _get_recent_trades_summary(self) -> Dict:
        """Получить сводку последних сделок"""
        try:
            if not hasattr(self.websocket_manager, 'trade_data'):
                return {}
            
            trades = self.websocket_manager.trade_data[-100:]  # Последние 100 сделок
            
            if not trades:
                return {}
            
            # Анализ сделок
            buy_trades = [t for t in trades if t.get("side", "").upper() == "BUY"]
            sell_trades = [t for t in trades if t.get("side", "").upper() == "SELL"]
            
            total_buy_volume = sum(t.get("size", 0) for t in buy_trades)
            total_sell_volume = sum(t.get("size", 0) for t in sell_trades)
            
            avg_trade_size = sum(t.get("size", 0) for t in trades) / len(trades) if trades else 0
            
            # Последние цены
            recent_prices = [t.get("price", 0) for t in trades[-10:]]
            price_trend = "up" if recent_prices[-1] > recent_prices[0] else "down" if recent_prices else "neutral"
            
            return {
                "total_trades": len(trades),
                "buy_trades": len(buy_trades),
                "sell_trades": len(sell_trades),
                "buy_sell_ratio": len(buy_trades) / len(sell_trades) if sell_trades else 0,
                "total_buy_volume": total_buy_volume,
                "total_sell_volume": total_sell_volume,
                "volume_ratio": total_buy_volume / total_sell_volume if total_sell_volume > 0 else 0,
                "avg_trade_size": avg_trade_size,
                "price_trend": price_trend,
                "latest_price": recent_prices[-1] if recent_prices else 0
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа сделок: {e}")
            return {}
    
    def _calculate_market_statistics(self) -> Dict:
        """Вычислить дополнительную рыночную статистику"""
        try:
            stats = {}
            
            # Анализ свечей для волатильности
            if hasattr(self.websocket_manager, 'kline_data') and self.websocket_manager.kline_data:
                klines = self.websocket_manager.kline_data[-20:]  # Последние 20 свечей
                
                if klines:
                    closes = [k.get("close", 0) for k in klines]
                    highs = [k.get("high", 0) for k in klines]
                    lows = [k.get("low", 0) for k in klines]
                    volumes = [k.get("volume", 0) for k in klines]
                    
                    # Волатильность (стандартное отклонение цен закрытия)
                    if len(closes) > 1:
                        mean_price = sum(closes) / len(closes)
                        variance = sum((price - mean_price) ** 2 for price in closes) / len(closes)
                        volatility = (variance ** 0.5) / mean_price * 100  # В процентах
                        stats["volatility_percent"] = volatility
                    
                    # Средний объем
                    stats["avg_volume"] = sum(volumes) / len(volumes) if volumes else 0
                    
                    # Диапазон цен
                    stats["price_range"] = {
                        "high": max(highs) if highs else 0,
                        "low": min(lows) if lows else 0,
                        "range_percent": ((max(highs) - min(lows)) / min(lows) * 100) if lows and min(lows) > 0 else 0
                    }
            
            return stats
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка вычисления статистики: {e}")
            return {}
    
    def _create_analysis_prompt(self, market_data: Dict) -> str:
        """Создание промпта для GPT-4 анализа"""
        
        symbol = market_data.get("symbol", "UNKNOWN")
        timeframe = market_data.get("timeframe", "5m")
        
        # Извлекаем ключевые данные
        basic_market = market_data.get("basic_market", {})
        indicators = market_data.get("technical_indicators", {})
        orderbook = market_data.get("orderbook", {})
        trades = market_data.get("recent_trades", {})
        stats = market_data.get("market_stats", {})
        
        prompt = f"""Ты профессиональный трейдер-аналитик фьючерсов с 15-летним опытом. Проведи ПОДРОБНЫЙ технический анализ для {symbol} на таймфрейме {timeframe}.

📊 РЫНОЧНЫЕ ДАННЫЕ:
Текущая цена: ${basic_market.get('price', 'N/A')}
Изменение 24ч: {basic_market.get('change_24h', 'N/A')}
Объем 24ч: {basic_market.get('volume_24h', 'N/A')}
Максимум 24ч: ${basic_market.get('high_24h', 'N/A')}
Минимум 24ч: ${basic_market.get('low_24h', 'N/A')}
Спред: ${orderbook.get('spread', 'N/A')}

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
Bollinger Lower: {indicators.get('bb_lower', 'N/A')}
Волатильность: {stats.get('volatility_percent', 'N/A')}%

📚 ОРДЕРБУК:
Лучший BID: ${orderbook.get('best_bid', 'N/A')}
Лучший ASK: ${orderbook.get('best_ask', 'N/A')}
Соотношение BID/ASK объемов: {orderbook.get('bid_ask_ratio', 'N/A')}
Общий объем BID: {orderbook.get('total_bid_volume', 'N/A')}
Общий объем ASK: {orderbook.get('total_ask_volume', 'N/A')}

💹 АНАЛИЗ СДЕЛОК:
Всего сделок: {trades.get('total_trades', 'N/A')}
Покупки: {trades.get('buy_trades', 'N/A')}
Продажи: {trades.get('sell_trades', 'N/A')}
Соотношение покупок/продаж: {trades.get('buy_sell_ratio', 'N/A')}
Соотношение объемов: {trades.get('volume_ratio', 'N/A')}
Тренд цены: {trades.get('price_trend', 'N/A')}

ЗАДАЧА: Проведи ГЛУБОКИЙ технический анализ и дай КОНКРЕТНЫЕ рекомендации для фьючерсной торговли:

1. 📊 ТЕХНИЧЕСКИЙ АНАЛИЗ:
   - Анализ всех индикаторов
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

Отвечай СТРУКТУРИРОВАННО с эмодзи, будь КОНКРЕТНЫМ в ценах и процентах. Это реальная торговля фьючерсами!"""

        return prompt
    
    async def _get_ai_analysis(self, prompt: str) -> str:
        """Получение анализа от OpenAI GPT-4"""
        try:
            if not self.client:
                return "❌ OpenAI клиент не инициализирован"
            
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
                self.logger.info(f"✅ Получен анализ от GPT-4 ({len(analysis)} символов)")
                return analysis
            else:
                return "❌ Пустой ответ от OpenAI"
                
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"❌ Ошибка запроса к OpenAI: {error_msg}")
            
            # Специфичные ошибки OpenAI
            if "invalid api key" in error_msg.lower():
                return "❌ НЕВЕРНЫЙ OPENAI_API_KEY! Проверьте ключ в настройках."
            elif "insufficient_quota" in error_msg.lower():
                return "❌ Превышен лимит OpenAI API. Проверьте баланс аккаунта."
            elif "rate_limit" in error_msg.lower():
                return "❌ Превышен лимит запросов OpenAI. Попробуйте позже."
            else:
                return f"❌ Ошибка OpenAI API: {error_msg}"
    
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
            if "%" in str(change_24h):
                change_value = float(change_24h.replace("%", "").replace("+", ""))
                trend_emoji = "🚀" if change_value > 2 else "📈" if change_value > 0 else "📉" if change_value < -2 else "➡️"
            else:
                trend_emoji = "📊"
            
            # RSI состояние
            rsi = indicators.get("rsi", 50)
            rsi_emoji = "🔥" if rsi > 70 else "❄️" if rsi < 30 else "⚖️"
            
            message = f"""
📊 <b>РЫНОЧНЫЕ ДАННЫЕ - {symbol}</b> {trend_emoji}

💰 <b>Цена:</b> <code>${basic_market.get('price', 'N/A')}</code>
📈 <b>Изменение 24ч:</b> <code>{basic_market.get('change_24h', 'N/A')}</code>
📊 <b>Объем 24ч:</b> <code>{basic_market.get('volume_24h', 'N/A')}</code>

🔝 <b>Максимум 24ч:</b> <code>${basic_market.get('high_24h', 'N/A')}</code>
🔻 <b>Минимум 24ч:</b> <code>${basic_market.get('low_24h', 'N/A')}</code>

📊 <b>ТЕХНИЧЕСКИЕ ИНДИКАТОРЫ:</b>
{rsi_emoji} <b>RSI:</b> <code>{rsi:.1f}</code>
📈 <b>MA короткая:</b> <code>{indicators.get('sma_short', 0):.2f}</code>
📉 <b>MA длинная:</b> <code>{indicators.get('sma_long', 0):.2f}</code>

📚 <b>ОРДЕРБУК:</b>
💚 <b>Лучший BID:</b> <code>${orderbook.get('best_bid', 0):.4f}</code>
❤️ <b>Лучший ASK:</b> <code>${orderbook.get('best_ask', 0):.4f}</code>
⚡ <b>Спред:</b> <code>${orderbook.get('spread', 0):.4f}</code>

💹 <b>АКТИВНОСТЬ:</b>
🔄 <b>Сделок:</b> <code>{trades.get('total_trades', 0)}</code>
📊 <b>Покупки/Продажи:</b> <code>{trades.get('buy_trades', 0)}/{trades.get('sell_trades', 0)}</code>

🕐 <i>Данные на {datetime.now().strftime('%H:%M:%S')}</i>
            """
            
            return message.strip()
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка форматирования данных: {e}")
            return f"❌ Ошибка форматирования рыночных данных: {e}"
    
    def get_status(self) -> Dict:
        """Получить статус анализатора"""
        return {
            "openai_available": OPENAI_AVAILABLE,
            "api_key_configured": bool(self.api_key),
            "client_initialized": self.client is not None,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "websocket_manager": self.websocket_manager is not None
        }
