"""
Базовая торговая стратегия
RSI + Moving Average стратегия для фьючерсов
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from config.settings import get_settings


@dataclass
class TradingSignal:
    """Структура торгового сигнала"""
    signal_id: str
    symbol: str
    signal_type: str  # BUY, SELL, HOLD
    price: float
    confidence: float  # 0.0 - 1.0
    timestamp: datetime
    reason: str
    indicators: dict
    timeframe: str


class TechnicalIndicators:
    """Технические индикаторы для анализа"""
    
    @staticmethod
    def sma(data: List[float], period: int) -> float:
        """Простая скользящая средняя"""
        if len(data) < period:
            return 0.0
        return sum(data[-period:]) / period
    
    @staticmethod
    def ema(data: List[float], period: int) -> float:
        """Экспоненциальная скользящая средняя"""
        if len(data) < period:
            return 0.0
        
        multiplier = 2 / (period + 1)
        ema_values = [data[0]]  # Первое значение
        
        for price in data[1:]:
            ema_value = (price * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema_value)
        
        return ema_values[-1]
    
    @staticmethod
    def rsi(data: List[float], period: int = 14) -> float:
        """Relative Strength Index"""
        if len(data) < period + 1:
            return 50.0  # Нейтральное значение
        
        gains = []
        losses = []
        
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
        """MACD индикатор"""
        if len(data) < slow:
            return {"macd": 0, "signal": 0, "histogram": 0}
        
        ema_fast = TechnicalIndicators.ema(data, fast)
        ema_slow = TechnicalIndicators.ema(data, slow)
        
        macd_line = ema_fast - ema_slow
        
        # Для упрощения, signal line = простая средняя из последних значений MACD
        signal_line = macd_line * 0.9  # Примерное значение
        histogram = macd_line - signal_line
        
        return {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": histogram
        }
    
    @staticmethod
    def bollinger_bands(data: List[float], period: int = 20, std_dev: int = 2) -> Dict[str, float]:
        """Полосы Боллинджера"""
        if len(data) < period:
            middle = data[-1] if data else 0
            return {"upper": middle, "middle": middle, "lower": middle}
        
        sma = TechnicalIndicators.sma(data, period)
        variance = sum([(x - sma) ** 2 for x in data[-period:]]) / period
        std = variance ** 0.5
        
        return {
            "upper": sma + (std * std_dev),
            "middle": sma,
            "lower": sma - (std * std_dev)
        }


class BaseStrategy:
    """Базовая торговая стратегия RSI + MA"""
    
    def __init__(self, symbol: str, timeframe: str = "5m"):
        self.settings = get_settings()
        self.symbol = symbol
        self.timeframe = timeframe
        
        # Данные для анализа
        self.kline_data = []
        self.ticker_data = {}
        self.orderbook_data = {}
        self.trade_data = []
        
        # История цен для индикаторов
        self.close_prices = []
        self.high_prices = []
        self.low_prices = []
        self.volumes = []
        
        # Сгенерированные сигналы
        self.signals_history = []
        self.last_signal_time = None
        
        # Состояние стратегии
        self.current_indicators = {}
        self.is_active = True
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"🎯 Стратегия инициализирована для {symbol} ({timeframe})")
    
    def update_ticker(self, ticker_data: dict):
        """Обновление ticker данных"""
        self.ticker_data = ticker_data
    
    def update_orderbook(self, orderbook_data: dict):
        """Обновление orderbook данных"""
        self.orderbook_data = orderbook_data
    
    def update_trades(self, trades: List[dict]):
        """Обновление данных о сделках"""
        self.trade_data.extend(trades)
        
        # Ограничиваем размер данных
        if len(self.trade_data) > 1000:
            self.trade_data = self.trade_data[-1000:]
    
    async def analyze_kline(self, kline: dict) -> Optional[TradingSignal]:
        """Анализ новой свечи и генерация сигнала"""
        try:
            # Добавляем данные свечи
            self.kline_data.append(kline)
            self.close_prices.append(kline["close"])
            self.high_prices.append(kline["high"])
            self.low_prices.append(kline["low"])
            self.volumes.append(kline["volume"])
            
            # Ограничиваем размер данных
            max_data = self.settings.KLINE_LIMIT
            if len(self.close_prices) > max_data:
                self.close_prices = self.close_prices[-max_data:]
                self.high_prices = self.high_prices[-max_data:]
                self.low_prices = self.low_prices[-max_data:]
                self.volumes = self.volumes[-max_data:]
                self.kline_data = self.kline_data[-max_data:]
            
            # Генерируем сигнал только для подтвержденных свечей
            if kline.get("confirm", False) and len(self.close_prices) >= 30:
                return await self._generate_signal()
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа kline: {e}")
            return None
    
    async def _generate_signal(self) -> Optional[TradingSignal]:
        """Генерация торгового сигнала"""
        try:
            # Проверяем cooldown между сигналами
            if self._is_signal_cooldown():
                return None
            
            # Вычисляем индикаторы
            indicators = self._calculate_indicators()
            
            # Анализируем условия для сигнала
            signal_type, confidence, reason = self._analyze_conditions(indicators)
            
            if signal_type == "HOLD" or confidence < self.settings.MIN_SIGNAL_CONFIDENCE:
                return None
            
            # Создаем сигнал
            signal = TradingSignal(
                signal_id=f"{self.symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                symbol=self.symbol,
                signal_type=signal_type,
                price=self.close_prices[-1],
                confidence=confidence,
                timestamp=datetime.now(),
                reason=reason,
                indicators=indicators,
                timeframe=self.timeframe
            )
            
            # Сохраняем сигнал
            self.signals_history.append(signal)
            self.last_signal_time = datetime.now()
            
            # Ограничиваем историю сигналов
            if len(self.signals_history) > 100:
                self.signals_history = self.signals_history[-100:]
            
            self.logger.info(f"🎯 Новый сигнал: {signal_type} {self.symbol} @ {signal.price:.4f} (уверенность: {confidence:.2%})")
            self.logger.info(f"   Причина: {reason}")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации сигнала: {e}")
            return None
    
    def _calculate_indicators(self) -> dict:
        """Вычисление технических индикаторов"""
        indicators = {}
        
        try:
            # RSI
            indicators["rsi"] = TechnicalIndicators.rsi(
                self.close_prices, 
                self.settings.RSI_PERIOD
            )
            
            # Moving Averages
            indicators["sma_short"] = TechnicalIndicators.sma(
                self.close_prices, 
                self.settings.MA_SHORT_PERIOD
            )
            indicators["sma_long"] = TechnicalIndicators.sma(
                self.close_prices, 
                self.settings.MA_LONG_PERIOD
            )
            
            # EMA
            indicators["ema_short"] = TechnicalIndicators.ema(
                self.close_prices, 
                self.settings.MA_SHORT_PERIOD
            )
            indicators["ema_long"] = TechnicalIndicators.ema(
                self.close_prices, 
                self.settings.MA_LONG_PERIOD
            )
            
            # MACD
            macd_data = TechnicalIndicators.macd(self.close_prices)
            indicators.update(macd_data)
            
            # Bollinger Bands
            bb_data = TechnicalIndicators.bollinger_bands(self.close_prices)
            indicators.update({f"bb_{k}": v for k, v in bb_data.items()})
            
            # Текущая цена
            indicators["current_price"] = self.close_prices[-1]
            
            # Волатильность (стандартное отклонение за 20 периодов)
            if len(self.close_prices) >= 20:
                recent_prices = self.close_prices[-20:]
                mean_price = sum(recent_prices) / len(recent_prices)
                variance = sum((price - mean_price) ** 2 for price in recent_prices) / len(recent_prices)
                indicators["volatility"] = (variance ** 0.5) / mean_price * 100
            else:
                indicators["volatility"] = 0
            
            # Объем (средний за последние 10 свечей)
            if len(self.volumes) >= 10:
                indicators["avg_volume"] = sum(self.volumes[-10:]) / 10
            else:
                indicators["avg_volume"] = self.volumes[-1] if self.volumes else 0
            
            self.current_indicators = indicators
            return indicators
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка вычисления индикаторов: {e}")
            return {}
    
    def _analyze_conditions(self, indicators: dict) -> tuple:
        """Анализ условий для генерации сигнала"""
        if not indicators:
            return "HOLD", 0.0, "Нет данных индикаторов"
        
        signals = []
        reasons = []
        
        # RSI анализ
        rsi = indicators.get("rsi", 50)
        if rsi <= self.settings.RSI_OVERSOLD:
            signals.append(("BUY", 0.8, f"RSI пересыщен: {rsi:.1f}"))
        elif rsi >= self.settings.RSI_OVERBOUGHT:
            signals.append(("SELL", 0.8, f"RSI перекуплен: {rsi:.1f}"))
        
        # Moving Average анализ
        sma_short = indicators.get("sma_short", 0)
        sma_long = indicators.get("sma_long", 0)
        current_price = indicators.get("current_price", 0)
        
        if sma_short > sma_long and current_price > sma_short:
            signals.append(("BUY", 0.6, f"Цена выше коротких MA"))
        elif sma_short < sma_long and current_price < sma_short:
            signals.append(("SELL", 0.6, f"Цена ниже коротких MA"))
        
        # MACD анализ
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("signal", 0)
        if macd > macd_signal and macd > 0:
            signals.append(("BUY", 0.5, "MACD бычий"))
        elif macd < macd_signal and macd < 0:
            signals.append(("SELL", 0.5, "MACD медвежий"))
        
        # Bollinger Bands анализ
        bb_lower = indicators.get("bb_lower", 0)
        bb_upper = indicators.get("bb_upper", 0)
        if current_price <= bb_lower:
            signals.append(("BUY", 0.7, "Цена касается нижней полосы Боллинджера"))
        elif current_price >= bb_upper:
            signals.append(("SELL", 0.7, "Цена касается верхней полосы Боллинджера"))
        
        # Анализ объема
        avg_volume = indicators.get("avg_volume", 0)
        current_volume = self.volumes[-1] if self.volumes else 0
        if current_volume > avg_volume * 1.5:  # Увеличенный объем
            volume_boost = 0.1
        else:
            volume_boost = 0
        
        # Объединяем сигналы
        if not signals:
            return "HOLD", 0.0, "Нет четких сигналов"
        
        # Группируем по типу сигнала
        buy_signals = [s for s in signals if s[0] == "BUY"]
        sell_signals = [s for s in signals if s[0] == "SELL"]
        
        if len(buy_signals) > len(sell_signals):
            total_confidence = min(sum(s[1] for s in buy_signals) / len(buy_signals) + volume_boost, 1.0)
            combined_reason = " + ".join([s[2] for s in buy_signals])
            return "BUY", total_confidence, combined_reason
        elif len(sell_signals) > len(buy_signals):
            total_confidence = min(sum(s[1] for s in sell_signals) / len(sell_signals) + volume_boost, 1.0)
            combined_reason = " + ".join([s[2] for s in sell_signals])
            return "SELL", total_confidence, combined_reason
        else:
            return "HOLD", 0.0, "Противоречивые сигналы"
    
    def _is_signal_cooldown(self) -> bool:
        """Проверка cooldown между сигналами"""
        if not self.last_signal_time:
            return False
        
        cooldown_minutes = self.settings.SIGNAL_COOLDOWN_MINUTES
        time_diff = datetime.now() - self.last_signal_time
        
        return time_diff < timedelta(minutes=cooldown_minutes)
    
    def get_current_data(self) -> dict:
        """Получить текущие данные стратегии"""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "is_active": self.is_active,
            "klines_count": len(self.kline_data),
            "prices_count": len(self.close_prices),
            "current_indicators": self.current_indicators,
            "last_price": self.close_prices[-1] if self.close_prices else 0,
            "signals_today": len([s for s in self.signals_history 
                                  if s.timestamp.date() == datetime.now().date()]),
            "last_signal": self.signals_history[-1].__dict__ if self.signals_history else None
        }
    
    def get_recent_signals(self, limit: int = 10) -> List[dict]:
        """Получить последние сигналы"""
        recent_signals = self.signals_history[-limit:] if self.signals_history else []
        return [signal.__dict__ for signal in recent_signals]
    
    def get_status(self) -> dict:
        """Получить статус стратегии"""
        return {
            "strategy_name": "RSI + Moving Average",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "is_active": self.is_active,
            "data_points": len(self.close_prices),
            "total_signals": len(self.signals_history),
            "signals_today": len([s for s in self.signals_history 
                                  if s.timestamp.date() == datetime.now().date()]),
            "last_signal_time": self.last_signal_time.isoformat() if self.last_signal_time else None,
            "current_indicators": self.current_indicators,
            "settings": {
                "rsi_period": self.settings.RSI_PERIOD,
                "rsi_oversold": self.settings.RSI_OVERSOLD,
                "rsi_overbought": self.settings.RSI_OVERBOUGHT,
                "ma_short": self.settings.MA_SHORT_PERIOD,
                "ma_long": self.settings.MA_LONG_PERIOD,
                "min_confidence": self.settings.MIN_SIGNAL_CONFIDENCE,
                "cooldown_minutes": self.settings.SIGNAL_COOLDOWN_MINUTES
            }
        }
