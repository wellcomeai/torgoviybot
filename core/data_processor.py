"""
Синхронная обработка и валидация рыночных данных
БЕЗ асинхронных вызовов, только чистые функции
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple


class DataProcessor:
    """Обработка и валидация рыночных данных"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("DataProcessor инициализирован")
    
    def process_kline(self, raw_kline: Dict) -> Optional[Dict]:
        """Обработка и валидация kline данных"""
        try:
            if not self._validate_kline(raw_kline):
                return None
            
            processed_kline = {
                # Основные данные
                "symbol": raw_kline["symbol"],
                "timestamp": raw_kline["timestamp"],
                "datetime": datetime.fromtimestamp(raw_kline["timestamp"] / 1000) if raw_kline["timestamp"] else datetime.now(),
                "interval": raw_kline.get("interval", "5"),
                "confirm": raw_kline.get("confirm", False),
                
                # OHLCV
                "open": float(raw_kline["open"]),
                "high": float(raw_kline["high"]),
                "low": float(raw_kline["low"]),
                "close": float(raw_kline["close"]),
                "volume": float(raw_kline["volume"]),
                
                # Дополнительные метрики
                "body": abs(float(raw_kline["close"]) - float(raw_kline["open"])),
                "range": float(raw_kline["high"]) - float(raw_kline["low"]),
                "upper_shadow": float(raw_kline["high"]) - max(float(raw_kline["open"]), float(raw_kline["close"])),
                "lower_shadow": min(float(raw_kline["open"]), float(raw_kline["close"])) - float(raw_kline["low"]),
                
                # Метаданные обработки
                "processed_at": datetime.now(),
                "data_source": "websocket"
            }
            
            # Вычисляем дополнительные метрики
            processed_kline.update(self._calculate_kline_metrics(processed_kline))
            
            return processed_kline
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки kline: {e}")
            return None
    
    def process_ticker(self, raw_ticker: Dict) -> Optional[Dict]:
        """Обработка и валидация ticker данных"""
        try:
            if not self._validate_ticker(raw_ticker):
                return None
            
            processed_ticker = {
                "symbol": raw_ticker["symbol"],
                "last_price": float(raw_ticker["last_price"]),
                "price_24h_pcnt": float(raw_ticker.get("price_24h_pcnt", 0)),
                "change_24h": float(raw_ticker.get("price_24h_pcnt", 0)) * 100,  # В процентах
                "volume_24h": float(raw_ticker.get("volume_24h", 0)),
                "high_24h": float(raw_ticker.get("high_24h", 0)),
                "low_24h": float(raw_ticker.get("low_24h", 0)),
                "bid_price": float(raw_ticker.get("bid1_price", 0)),
                "ask_price": float(raw_ticker.get("ask1_price", 0)),
                
                # Вычисляемые поля
                "spread": float(raw_ticker.get("ask1_price", 0)) - float(raw_ticker.get("bid1_price", 0)),
                "mid_price": (float(raw_ticker.get("ask1_price", 0)) + float(raw_ticker.get("bid1_price", 0))) / 2,
                
                # Метаданные
                "processed_at": datetime.now(),
                "data_source": "websocket"
            }
            
            # Вычисляем спред в процентах
            if processed_ticker["bid_price"] > 0:
                processed_ticker["spread_percent"] = (processed_ticker["spread"] / processed_ticker["bid_price"]) * 100
            else:
                processed_ticker["spread_percent"] = 0
            
            return processed_ticker
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки ticker: {e}")
            return None
    
    def process_orderbook(self, raw_orderbook: Dict) -> Optional[Dict]:
        """Обработка и валидация orderbook данных"""
        try:
            if not self._validate_orderbook(raw_orderbook):
                return None
            
            bids = raw_orderbook.get("bids", [])
            asks = raw_orderbook.get("asks", [])
            
            processed_orderbook = {
                "symbol": raw_orderbook["symbol"],
                "bids": bids,
                "asks": asks,
                "timestamp": raw_orderbook.get("timestamp", int(datetime.now().timestamp() * 1000)),
                
                # Вычисляемые поля
                "best_bid": float(bids[0][0]) if bids else 0,
                "best_ask": float(asks[0][0]) if asks else 0,
                "best_bid_size": float(bids[0][1]) if bids else 0,
                "best_ask_size": float(asks[0][1]) if asks else 0,
                
                # Метаданные
                "processed_at": datetime.now(),
                "data_source": "websocket"
            }
            
            # Вычисляем дополнительные метрики
            processed_orderbook.update(self._calculate_orderbook_metrics(processed_orderbook))
            
            return processed_orderbook
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки orderbook: {e}")
            return None
    
    def process_trades(self, raw_trades: List[Dict]) -> List[Dict]:
        """Обработка и валидация trade данных"""
        processed_trades = []
        
        try:
            for trade in raw_trades:
                if not self._validate_trade(trade):
                    continue
                
                processed_trade = {
                    "symbol": trade["symbol"],
                    "trade_id": trade.get("trade_id", ""),
                    "timestamp": trade["timestamp"],
                    "datetime": datetime.fromtimestamp(trade["timestamp"] / 1000) if trade["timestamp"] else datetime.now(),
                    "price": float(trade["price"]),
                    "size": float(trade["size"]),
                    "side": trade["side"].upper(),
                    "value": float(trade["price"]) * float(trade["size"]),
                    
                    # Метаданные
                    "processed_at": datetime.now(),
                    "data_source": "websocket"
                }
                
                processed_trades.append(processed_trade)
                
            return processed_trades
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки trades: {e}")
            return []
    
    def _validate_kline(self, kline: Dict) -> bool:
        """Валидация kline данных"""
        required_fields = ["symbol", "timestamp", "open", "high", "low", "close", "volume"]
        
        for field in required_fields:
            if field not in kline or kline[field] is None:
                self.logger.warning(f"Отсутствует поле {field} в kline данных")
                return False
        
        # Проверка OHLC логики
        try:
            o, h, l, c = float(kline["open"]), float(kline["high"]), float(kline["low"]), float(kline["close"])
            if not (l <= o <= h and l <= c <= h):
                self.logger.warning("Некорректные OHLC значения")
                return False
        except (ValueError, TypeError):
            self.logger.warning("Некорректные числовые значения в kline")
            return False
        
        return True
    
    def _validate_ticker(self, ticker: Dict) -> bool:
        """Валидация ticker данных"""
        required_fields = ["symbol", "last_price"]
        
        for field in required_fields:
            if field not in ticker or ticker[field] is None:
                self.logger.warning(f"Отсутствует поле {field} в ticker данных")
                return False
        
        try:
            float(ticker["last_price"])
        except (ValueError, TypeError):
            self.logger.warning("Некорректная цена в ticker")
            return False
        
        return True
    
    def _validate_orderbook(self, orderbook: Dict) -> bool:
        """Валидация orderbook данных"""
        if "symbol" not in orderbook:
            return False
        
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        
        if not bids or not asks:
            return False
        
        # Проверяем формат bid/ask
        try:
            for bid in bids[:3]:
                float(bid[0]), float(bid[1])
            for ask in asks[:3]:
                float(ask[0]), float(ask[1])
        except (ValueError, TypeError, IndexError):
            return False
        
        return True
    
    def _validate_trade(self, trade: Dict) -> bool:
        """Валидация trade данных"""
        required_fields = ["symbol", "timestamp", "price", "size", "side"]
        
        for field in required_fields:
            if field not in trade or trade[field] is None:
                return False
        
        try:
            float(trade["price"])
            float(trade["size"])
        except (ValueError, TypeError):
            return False
        
        return True
    
    def _calculate_kline_metrics(self, kline: Dict) -> Dict:
        """Вычисление дополнительных метрик для kline"""
        metrics = {}
        
        try:
            o, h, l, c = kline["open"], kline["high"], kline["low"], kline["close"]
            
            # Процентные изменения
            if o > 0:
                metrics["change_percent"] = ((c - o) / o) * 100
                metrics["range_percent"] = ((h - l) / o) * 100
                metrics["body_percent"] = (abs(c - o) / (h - l)) * 100 if (h - l) > 0 else 0
            else:
                metrics["change_percent"] = 0
                metrics["range_percent"] = 0
                metrics["body_percent"] = 0
            
            # Тип свечи
            if c > o:
                metrics["candle_type"] = "bullish"
            elif c < o:
                metrics["candle_type"] = "bearish"
            else:
                metrics["candle_type"] = "doji"
            
            # Позиция закрытия (0-100%)
            if (h - l) > 0:
                metrics["close_position"] = ((c - l) / (h - l)) * 100
            else:
                metrics["close_position"] = 50
            
            # Объем на цену
            if c > 0:
                metrics["volume_price_ratio"] = kline["volume"] / c
            else:
                metrics["volume_price_ratio"] = 0
            
        except Exception as e:
            self.logger.debug(f"Ошибка вычисления kline метрик: {e}")
        
        return metrics
    
    def _calculate_orderbook_metrics(self, orderbook: Dict) -> Dict:
        """Вычисление дополнительных метрик для orderbook"""
        metrics = {}
        
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            if not bids or not asks:
                return metrics
            
            # Спред
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            metrics["spread"] = best_ask - best_bid
            metrics["spread_percent"] = (metrics["spread"] / best_bid) * 100 if best_bid > 0 else 0
            metrics["mid_price"] = (best_bid + best_ask) / 2
            
            # Объемы
            total_bid_volume = sum(float(bid[1]) for bid in bids[:5])
            total_ask_volume = sum(float(ask[1]) for ask in asks[:5])
            metrics["total_bid_volume"] = total_bid_volume
            metrics["total_ask_volume"] = total_ask_volume
            metrics["total_volume"] = total_bid_volume + total_ask_volume
            
            # Дисбаланс ордеров
            if metrics["total_volume"] > 0:
                metrics["order_imbalance"] = (total_bid_volume - total_ask_volume) / metrics["total_volume"]
            else:
                metrics["order_imbalance"] = 0
            
            # Настроение рынка
            if metrics["order_imbalance"] > 0.1:
                metrics["market_sentiment"] = "bullish"
            elif metrics["order_imbalance"] < -0.1:
                metrics["market_sentiment"] = "bearish"
            else:
                metrics["market_sentiment"] = "neutral"
                
        except Exception as e:
            self.logger.debug(f"Ошибка вычисления orderbook метрик: {e}")
        
        return metrics
    
    def calculate_technical_indicators(self, klines: List[Dict], periods: Dict = None) -> Dict:
        """Вычисление технических индикаторов"""
        if not klines:
            return {}
        
        # Дефолтные периоды
        if periods is None:
            periods = {
                "rsi": 14,
                "sma_short": 9,
                "sma_long": 21,
                "ema_short": 12,
                "ema_long": 26,
                "bb_period": 20
            }
        
        indicators = {}
        closes = [k["close"] for k in klines]
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        volumes = [k["volume"] for k in klines]
        
        try:
            # RSI
            if len(closes) >= periods["rsi"] + 1:
                indicators["rsi"] = self._calculate_rsi(closes, periods["rsi"])
            
            # Moving Averages
            if len(closes) >= periods["sma_short"]:
                indicators["sma_short"] = self._calculate_sma(closes, periods["sma_short"])
            
            if len(closes) >= periods["sma_long"]:
                indicators["sma_long"] = self._calculate_sma(closes, periods["sma_long"])
            
            if len(closes) >= periods["ema_short"]:
                indicators["ema_short"] = self._calculate_ema(closes, periods["ema_short"])
            
            if len(closes) >= periods["ema_long"]:
                indicators["ema_long"] = self._calculate_ema(closes, periods["ema_long"])
            
            # MACD
            if "ema_short" in indicators and "ema_long" in indicators:
                macd_line = indicators["ema_short"] - indicators["ema_long"]
                indicators["macd"] = macd_line
                indicators["macd_signal"] = macd_line * 0.9  # Упрощенная signal line
                indicators["macd_histogram"] = indicators["macd"] - indicators["macd_signal"]
            
            # Bollinger Bands
            if len(closes) >= periods["bb_period"]:
                bb = self._calculate_bollinger_bands(closes, periods["bb_period"])
                indicators.update(bb)
            
            # Текущие значения
            indicators["current_price"] = closes[-1]
            indicators["current_volume"] = volumes[-1] if volumes else 0
            
            # Волатильность
            if len(closes) >= 20:
                indicators["volatility"] = self._calculate_volatility(closes[-20:])
            
        except Exception as e:
            self.logger.error(f"Ошибка вычисления индикаторов: {e}")
        
        return indicators
    
    def _calculate_rsi(self, prices: List[float], period: int) -> float:
        """Расчет RSI"""
        if len(prices) < period + 1:
            return 50.0
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
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
        return 100 - (100 / (1 + rs))
    
    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """Простая скользящая средняя"""
        if len(prices) < period:
            return 0.0
        return sum(prices[-period:]) / period
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Экспоненциальная скользящая средняя"""
        if len(prices) < period:
            return 0.0
        
        multiplier = 2 / (period + 1)
        ema_values = [prices[0]]
        
        for price in prices[1:]:
            ema_value = (price * multiplier) + (ema_values[-1] * (1 - multiplier))
            ema_values.append(ema_value)
        
        return ema_values[-1]
    
    def _calculate_bollinger_bands(self, prices: List[float], period: int, std_dev: int = 2) -> Dict:
        """Bollinger Bands"""
        if len(prices) < period:
            middle = prices[-1] if prices else 0
            return {"bb_upper": middle, "bb_middle": middle, "bb_lower": middle}
        
        sma = self._calculate_sma(prices, period)
        recent_prices = prices[-period:]
        
        # Стандартное отклонение
        variance = sum((x - sma) ** 2 for x in recent_prices) / period
        std = (variance ** 0.5)
        
        return {
            "bb_upper": sma + (std * std_dev),
            "bb_middle": sma,
            "bb_lower": sma - (std * std_dev)
        }
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Волатильность"""
        if len(prices) < 2:
            return 0.0
        
        mean_price = sum(prices) / len(prices)
        variance = sum((price - mean_price) ** 2 for price in prices) / len(prices)
        return ((variance ** 0.5) / mean_price) * 100
