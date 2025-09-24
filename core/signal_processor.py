"""
Синхронная обработка торговых сигналов
Анализ данных и генерация сигналов БЕЗ асинхронных вызовов
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

from config.settings import get_settings


@dataclass
class TradingSignal:
    """Торговый сигнал"""
    signal_id: str
    symbol: str
    signal_type: str  # BUY, SELL, HOLD
    price: float
    confidence: float  # 0.0 - 1.0
    timestamp: datetime
    reason: str
    indicators: Dict[str, Any]
    timeframe: str
    metadata: Dict[str, Any] = None


class SignalProcessor:
    """Синхронная обработка торговых сигналов"""
    
    def __init__(self):
        self.settings = get_settings()
        
        # История сигналов
        self.signals_history = []
        self.last_signal_time = None
        
        # Callback для отправки сигналов
        self.on_signal_generated = None
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("SignalProcessor инициализирован")
    
    def set_signal_callback(self, callback: Callable[[TradingSignal], None]):
        """Установка callback для отправки сигналов"""
        self.on_signal_generated = callback
    
    def analyze_market_data(self, market_data: Dict) -> Optional[TradingSignal]:
        """
        Анализ рыночных данных и генерация сигналов
        СИНХРОННАЯ функция - НЕ async!
        """
        try:
            # Проверяем cooldown между сигналами
            if self._is_signal_cooldown():
                return None
            
            # Извлекаем данные для анализа
            klines = market_data.get("recent_klines", [])
            ticker = market_data.get("basic_market", {})
            orderbook = market_data.get("orderbook", {})
            trades = market_data.get("recent_trades", [])
            
            if not klines or len(klines) < 30:
                self.logger.debug("Недостаточно kline данных для анализа")
                return None
            
            # Вычисляем технические индикаторы
            from core.data_processor import DataProcessor
            processor = DataProcessor()
            indicators = processor.calculate_technical_indicators(klines)
            
            if not indicators:
                self.logger.debug("Не удалось вычислить индикаторы")
                return None
            
            # Анализируем условия для генерации сигнала
            signal_type, confidence, reason = self._analyze_trading_conditions(
                indicators, ticker, orderbook, trades
            )
            
            # Проверяем минимальную уверенность
            if signal_type == "HOLD" or confidence < self.settings.MIN_SIGNAL_CONFIDENCE:
                return None
            
            # Создаем сигнал
            signal = TradingSignal(
                signal_id=f"{self.settings.TRADING_PAIR}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                symbol=self.settings.TRADING_PAIR,
                signal_type=signal_type,
                price=indicators.get("current_price", 0),
                confidence=confidence,
                timestamp=datetime.now(),
                reason=reason,
                indicators=indicators,
                timeframe=self.settings.STRATEGY_TIMEFRAME,
                metadata={
                    "data_quality": market_data.get("metadata", {}).get("data_quality", {}),
                    "analysis_timestamp": datetime.now().isoformat()
                }
            )
            
            # Сохраняем в истории
            self.signals_history.append(signal)
            self.last_signal_time = datetime.now()
            
            # Ограничиваем размер истории
            if len(self.signals_history) > 100:
                self.signals_history = self.signals_history[-100:]
            
            # Отправляем callback если настроен
            if self.on_signal_generated:
                try:
                    self.on_signal_generated(signal)
                except Exception as e:
                    self.logger.error(f"Ошибка callback сигнала: {e}")
            
            self.logger.info(f"Сгенерирован сигнал: {signal_type} {signal.symbol} @ {signal.price:.4f} (уверенность: {confidence:.2%})")
            self.logger.info(f"Причина: {reason}")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа рыночных данных: {e}")
            return None
    
    def _analyze_trading_conditions(self, indicators: Dict, ticker: Dict, orderbook: Dict, trades: List) -> tuple:
        """Анализ торговых условий"""
        signals = []
        reasons = []
        
        try:
            current_price = indicators.get("current_price", 0)
            if not current_price:
                return "HOLD", 0.0, "Нет данных о текущей цене"
            
            # 1. RSI анализ
            rsi = indicators.get("rsi", 50)
            if rsi <= self.settings.RSI_OVERSOLD:
                signals.append(("BUY", 0.8, f"RSI пересыщен: {rsi:.1f}"))
            elif rsi >= self.settings.RSI_OVERBOUGHT:
                signals.append(("SELL", 0.8, f"RSI перекуплен: {rsi:.1f}"))
            
            # 2. Moving Average анализ
            sma_short = indicators.get("sma_short", 0)
            sma_long = indicators.get("sma_long", 0)
            
            if sma_short and sma_long:
                if sma_short > sma_long and current_price > sma_short:
                    signals.append(("BUY", 0.6, f"Цена выше коротких MA (короткая: {sma_short:.2f}, длинная: {sma_long:.2f})"))
                elif sma_short < sma_long and current_price < sma_short:
                    signals.append(("SELL", 0.6, f"Цена ниже коротких MA (короткая: {sma_short:.2f}, длинная: {sma_long:.2f})"))
            
            # 3. MACD анализ
            macd = indicators.get("macd", 0)
            macd_signal = indicators.get("macd_signal", 0)
            if macd and macd_signal:
                if macd > macd_signal and macd > 0:
                    signals.append(("BUY", 0.5, f"MACD бычий (MACD: {macd:.4f} > Signal: {macd_signal:.4f})"))
                elif macd < macd_signal and macd < 0:
                    signals.append(("SELL", 0.5, f"MACD медвежий (MACD: {macd:.4f} < Signal: {macd_signal:.4f})"))
            
            # 4. Bollinger Bands анализ
            bb_upper = indicators.get("bb_upper", 0)
            bb_lower = indicators.get("bb_lower", 0)
            bb_middle = indicators.get("bb_middle", 0)
            
            if bb_upper and bb_lower:
                if current_price <= bb_lower:
                    signals.append(("BUY", 0.7, f"Цена касается нижней полосы Боллинджера ({current_price:.2f} <= {bb_lower:.2f})"))
                elif current_price >= bb_upper:
                    signals.append(("SELL", 0.7, f"Цена касается верхней полосы Боллинджера ({current_price:.2f} >= {bb_upper:.2f})"))
            
            # 5. Анализ объема
            volume_boost = self._analyze_volume(indicators, trades)
            
            # 6. Анализ orderbook
            orderbook_signal = self._analyze_orderbook_imbalance(orderbook)
            if orderbook_signal:
                signals.append(orderbook_signal)
            
            # 7. Анализ momentum
            momentum_signal = self._analyze_price_momentum(indicators)
            if momentum_signal:
                signals.append(momentum_signal)
            
            # Объединяем сигналы
            if not signals:
                return "HOLD", 0.0, "Нет четких торговых сигналов"
            
            # Группируем по типу
            buy_signals = [s for s in signals if s[0] == "BUY"]
            sell_signals = [s for s in signals if s[0] == "SELL"]
            
            if len(buy_signals) > len(sell_signals):
                avg_confidence = sum(s[1] for s in buy_signals) / len(buy_signals)
                total_confidence = min(avg_confidence + volume_boost, 1.0)
                combined_reason = " + ".join([s[2] for s in buy_signals[:3]])  # Топ 3 причины
                return "BUY", total_confidence, combined_reason
                
            elif len(sell_signals) > len(buy_signals):
                avg_confidence = sum(s[1] for s in sell_signals) / len(sell_signals)
                total_confidence = min(avg_confidence + volume_boost, 1.0)
                combined_reason = " + ".join([s[2] for s in sell_signals[:3]])  # Топ 3 причины
                return "SELL", total_confidence, combined_reason
                
            else:
                return "HOLD", 0.0, "Противоречивые сигналы (покупка/продажа сбалансированы)"
                
        except Exception as e:
            self.logger.error(f"Ошибка анализа торговых условий: {e}")
            return "HOLD", 0.0, f"Ошибка анализа: {e}"
    
    def _analyze_volume(self, indicators: Dict, trades: List) -> float:
        """Анализ объема для усиления сигнала"""
        try:
            current_volume = indicators.get("current_volume", 0)
            
            if not trades or len(trades) < 10:
                return 0
            
            # Средний объем за последние сделки
            recent_volumes = [t.get("size", 0) for t in trades[-10:]]
            avg_volume = sum(recent_volumes) / len(recent_volumes)
            
            # Усиливаем сигнал если текущий объем выше среднего
            if current_volume > avg_volume * 1.5:
                return 0.1  # Бонус к уверенности
            elif current_volume > avg_volume * 2.0:
                return 0.15  # Больший бонус
            
            return 0
            
        except Exception as e:
            self.logger.debug(f"Ошибка анализа объема: {e}")
            return 0
    
    def _analyze_orderbook_imbalance(self, orderbook: Dict) -> Optional[tuple]:
        """Анализ дисбаланса ордербука"""
        try:
            order_imbalance = orderbook.get("order_imbalance", 0)
            
            if order_imbalance > 0.3:
                return ("BUY", 0.4, f"Сильный дисбаланс в пользу покупок ({order_imbalance:.2%})")
            elif order_imbalance < -0.3:
                return ("SELL", 0.4, f"Сильный дисбаланс в пользу продаж ({order_imbalance:.2%})")
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Ошибка анализа orderbook imbalance: {e}")
            return None
    
    def _analyze_price_momentum(self, indicators: Dict) -> Optional[tuple]:
        """Анализ ценового momentum"""
        try:
            ema_short = indicators.get("ema_short", 0)
            ema_long = indicators.get("ema_long", 0)
            current_price = indicators.get("current_price", 0)
            
            if not (ema_short and ema_long and current_price):
                return None
            
            # Сильный momentum если цена значительно выше/ниже EMA
            short_deviation = (current_price - ema_short) / ema_short if ema_short else 0
            long_deviation = (current_price - ema_long) / ema_long if ema_long else 0
            
            if short_deviation > 0.02 and long_deviation > 0.01:  # 2% и 1%
                return ("BUY", 0.3, f"Сильный восходящий momentum (цена выше EMA на {short_deviation:.2%})")
            elif short_deviation < -0.02 and long_deviation < -0.01:
                return ("SELL", 0.3, f"Сильный нисходящий momentum (цена ниже EMA на {abs(short_deviation):.2%})")
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Ошибка анализа momentum: {e}")
            return None
    
    def _is_signal_cooldown(self) -> bool:
        """Проверка cooldown между сигналами"""
        if not self.last_signal_time:
            return False
        
        cooldown_minutes = self.settings.SIGNAL_COOLDOWN_MINUTES
        time_diff = datetime.now() - self.last_signal_time
        
        return time_diff < timedelta(minutes=cooldown_minutes)
    
    def get_recent_signals(self, limit: int = 10) -> List[Dict]:
        """Получение последних сигналов"""
        try:
            recent_signals = self.signals_history[-limit:] if self.signals_history else []
            return [self._signal_to_dict(signal) for signal in recent_signals]
            
        except Exception as e:
            self.logger.error(f"Ошибка получения recent signals: {e}")
            return []
    
    def get_signal_statistics(self) -> Dict:
        """Статистика по сигналам"""
        try:
            if not self.signals_history:
                return {}
            
            total_signals = len(self.signals_history)
            buy_signals = [s for s in self.signals_history if s.signal_type == "BUY"]
            sell_signals = [s for s in self.signals_history if s.signal_type == "SELL"]
            
            # Статистика за сегодня
            today = datetime.now().date()
            today_signals = [s for s in self.signals_history if s.timestamp.date() == today]
            
            # Средняя уверенность
            avg_confidence = sum(s.confidence for s in self.signals_history) / total_signals
            
            return {
                "total_signals": total_signals,
                "buy_signals": len(buy_signals),
                "sell_signals": len(sell_signals),
                "signals_today": len(today_signals),
                "average_confidence": avg_confidence,
                "last_signal_time": self.last_signal_time.isoformat() if self.last_signal_time else None,
                "cooldown_active": self._is_signal_cooldown(),
                "signal_types_distribution": {
                    "BUY": len(buy_signals) / total_signals,
                    "SELL": len(sell_signals) / total_signals
                }
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка получения signal statistics: {e}")
            return {}
    
    def _signal_to_dict(self, signal: TradingSignal) -> Dict:
        """Преобразование сигнала в словарь"""
        return {
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "signal_type": signal.signal_type,
            "price": signal.price,
            "confidence": signal.confidence,
            "timestamp": signal.timestamp.isoformat(),
            "reason": signal.reason,
            "timeframe": signal.timeframe,
            "indicators_summary": {
                "rsi": signal.indicators.get("rsi"),
                "current_price": signal.indicators.get("current_price"),
                "sma_short": signal.indicators.get("sma_short"),
                "sma_long": signal.indicators.get("sma_long")
            },
            "metadata": signal.metadata
        }
    
    def clear_old_signals(self, max_age_days: int = 7):
        """Очистка старых сигналов"""
        try:
            cutoff_date = datetime.now() - timedelta(days=max_age_days)
            
            old_count = len(self.signals_history)
            self.signals_history = [
                s for s in self.signals_history 
                if s.timestamp > cutoff_date
            ]
            new_count = len(self.signals_history)
            
            if old_count > new_count:
                self.logger.info(f"Очищено {old_count - new_count} старых сигналов (старше {max_age_days} дней)")
                
        except Exception as e:
            self.logger.error(f"Ошибка очистки старых сигналов: {e}")
    
    def validate_signal_conditions(self, market_data: Dict) -> Dict:
        """Валидация условий для генерации сигналов"""
        validation_result = {
            "can_generate_signals": True,
            "issues": [],
            "recommendations": []
        }
        
        try:
            # Проверяем качество данных
            klines = market_data.get("recent_klines", [])
            if len(klines) < 30:
                validation_result["issues"].append(f"Недостаточно kline данных: {len(klines)}/30")
                validation_result["can_generate_signals"] = False
            
            # Проверяем свежесть данных
            metadata = market_data.get("metadata", {})
            data_quality = metadata.get("data_quality", {})
            
            for data_type, quality_info in data_quality.items():
                if isinstance(quality_info, dict) and not quality_info.get("is_fresh", True):
                    validation_result["issues"].append(f"Устаревшие данные: {data_type}")
            
            # Проверяем cooldown
            if self._is_signal_cooldown():
                validation_result["issues"].append(f"Активен cooldown сигналов ({self.settings.SIGNAL_COOLDOWN_MINUTES} мин)")
                validation_result["can_generate_signals"] = False
            
            # Рекомендации
            if not validation_result["can_generate_signals"]:
                validation_result["recommendations"].append("Дождитесь получения достаточного количества данных")
                validation_result["recommendations"].append("Проверьте стабильность WebSocket соединения")
            
            return validation_result
            
        except Exception as e:
            self.logger.error(f"Ошибка валидации signal conditions: {e}")
            return {
                "can_generate_signals": False,
                "issues": [f"Ошибка валидации: {e}"],
                "recommendations": ["Проверьте работоспособность системы"]
            }
