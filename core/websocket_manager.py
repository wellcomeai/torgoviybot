"""
WebSocket менеджер для подключения к Bybit
Обработка потоков данных и управление соединением
Обновлено: добавлен метод get_comprehensive_market_data() для ИИ-анализа
"""

import asyncio
import json
import logging
import time
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from config.settings import get_settings


class WebSocketManager:
    """Менеджер WebSocket соединения с Bybit"""
    
    def __init__(self, symbol: str, strategy, on_signal_callback: Optional[Callable] = None):
        self.settings = get_settings()
        self.symbol = symbol
        self.strategy = strategy
        self.on_signal_callback = on_signal_callback
        
        self.websocket = None
        self.is_connected = False
        self.reconnect_count = 0
        self.last_ping = 0
        self.last_data_time = time.time()
        
        # Хранение данных
        self.ticker_data = {}
        self.kline_data = []
        self.orderbook_data = {}
        self.trade_data = []
        
        # Расширенное хранение для ИИ-анализа
        self.extended_kline_data = []  # Больше свечей для анализа
        self.extended_orderbook_history = []  # История изменений ордербука
        self.volume_profile = {}  # Профиль объема
        self.price_levels = {"support": [], "resistance": []}  # Уровни поддержки/сопротивления
        
        # Задачи asyncio
        self.ping_task = None
        self.reconnect_task = None
        self.main_task = None
        
        # Лимиты данных
        self.max_klines = self.settings.KLINE_LIMIT
        self.max_trades = 1000
        self.max_extended_klines = self.settings.AI_KLINES_COUNT  # Для ИИ-анализа
        self.max_orderbook_history = 50  # История ордербука
        
        self.logger = logging.getLogger(__name__)
        
    async def start(self):
        """Запуск WebSocket соединения"""
        try:
            self.logger.info(f"🔌 Подключение к Bybit WebSocket...")
            self.logger.info(f"   URL: {self.settings.websocket_url}")
            self.logger.info(f"   Символ: {self.symbol}")
            self.logger.info(f"   Расширенный сбор данных для ИИ: включен")
            
            # Запуск основной задачи
            self.main_task = asyncio.create_task(self._main_loop())
            
            # Ждем установления соединения
            for _ in range(10):  # 10 секунд максимум
                if self.is_connected:
                    break
                await asyncio.sleep(1)
            
            if not self.is_connected:
                raise Exception("Не удалось установить соединение в течение 10 секунд")
            
            self.logger.info("✅ WebSocket соединение установлено")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска WebSocket: {e}")
            raise
    
    async def stop(self):
        """Остановка WebSocket соединения"""
        try:
            self.logger.info("🛑 Остановка WebSocket соединения...")
            
            self.is_connected = False
            
            # Отмена всех задач
            if self.main_task and not self.main_task.done():
                self.main_task.cancel()
            
            if self.ping_task and not self.ping_task.done():
                self.ping_task.cancel()
            
            if self.reconnect_task and not self.reconnect_task.done():
                self.reconnect_task.cancel()
            
            # Закрытие WebSocket соединения
            if self.websocket:
                await self.websocket.close()
                
            self.logger.info("✅ WebSocket соединение закрыто")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка закрытия WebSocket: {e}")
    
    async def _main_loop(self):
        """Основной цикл WebSocket соединения"""
        while True:
            try:
                await self._connect_and_subscribe()
                await self._listen_messages()
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка в главном цикле WebSocket: {e}")
                self.is_connected = False
                
                if self.reconnect_count < self.settings.WS_RECONNECT_ATTEMPTS:
                    self.reconnect_count += 1
                    delay = self.settings.WS_RECONNECT_DELAY * self.reconnect_count
                    self.logger.info(f"🔄 Переподключение через {delay} сек (попытка {self.reconnect_count})")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error("❌ Превышен лимит попыток переподключения")
                    break
    
    async def _connect_and_subscribe(self):
        """Подключение и подписка на данные"""
        try:
            # Подключение к WebSocket
            self.websocket = await websockets.connect(
                self.settings.websocket_url,
                ping_interval=None,  # Отключаем автоматический ping
                ping_timeout=None,
                close_timeout=10
            )
            
            self.logger.info("🔌 WebSocket соединение установлено")
            
            # Подписка на данные (расширенная для ИИ-анализа)
            subscriptions = [
                self.settings.get_ticker_subscription(),
                self.settings.get_kline_subscription(),
                self.settings.get_orderbook_subscription(),
                f"publicTrade.{self.symbol}"
            ]
            
            subscribe_message = {
                "op": "subscribe",
                "args": subscriptions
            }
            
            await self.websocket.send(json.dumps(subscribe_message))
            self.logger.info(f"📡 Подписка на данные: {subscriptions}")
            
            # Запуск ping задачи
            if self.ping_task and not self.ping_task.done():
                self.ping_task.cancel()
            
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            self.is_connected = True
            self.reconnect_count = 0
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка подключения: {e}")
            raise
    
    async def _listen_messages(self):
        """Прослушивание сообщений WebSocket"""
        async for message in self.websocket:
            try:
                data = json.loads(message)
                await self._handle_message(data)
                self.last_data_time = time.time()
                
            except json.JSONDecodeError as e:
                self.logger.error(f"❌ Ошибка парсинга JSON: {e}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка обработки сообщения: {e}")
    
    async def _handle_message(self, data: dict):
        """Обработка входящих сообщений"""
        try:
            # Обработка подтверждения подписки
            if data.get("success") and data.get("op") == "subscribe":
                self.logger.info(f"✅ Подписка подтверждена: {data.get('ret_msg', 'OK')}")
                return
            
            # Обработка pong ответов
            if data.get("op") == "ping":
                pong_message = {"op": "pong", "args": data.get("args", [])}
                await self.websocket.send(json.dumps(pong_message))
                return
            
            # Получение топика из данных
            topic = data.get("topic", "")
            
            if not topic:
                return
            
            # Обработка ticker данных
            if topic.startswith("tickers."):
                await self._handle_ticker_data(data)
            
            # Обработка kline данных
            elif topic.startswith("kline."):
                await self._handle_kline_data(data)
            
            # Обработка orderbook данных
            elif topic.startswith("orderbook."):
                await self._handle_orderbook_data(data)
            
            # Обработка trade данных
            elif topic.startswith("publicTrade."):
                await self._handle_trade_data(data)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки сообщения: {e}")
    
    async def _handle_ticker_data(self, data: dict):
        """Обработка ticker данных"""
        try:
            ticker_info = data.get("data", {})
            
            if not ticker_info:
                return
            
            self.ticker_data = {
                "symbol": ticker_info.get("symbol"),
                "price": float(ticker_info.get("lastPrice", 0)),
                "change_24h": float(ticker_info.get("price24hPcnt", 0)) * 100,
                "volume_24h": float(ticker_info.get("volume24h", 0)),
                "high_24h": float(ticker_info.get("highPrice24h", 0)),
                "low_24h": float(ticker_info.get("lowPrice24h", 0)),
                "bid": float(ticker_info.get("bid1Price", 0)),
                "ask": float(ticker_info.get("ask1Price", 0)),
                "timestamp": datetime.now().isoformat()
            }
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_ticker(self.ticker_data)
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки ticker: {e}")
    
    async def _handle_kline_data(self, data: dict):
        """Обработка kline (свечи) данных с расширенным сбором"""
        try:
            klines = data.get("data", [])
            
            for kline_info in klines:
                kline = {
                    "timestamp": int(kline_info.get("start", 0)),
                    "datetime": datetime.fromtimestamp(int(kline_info.get("start", 0)) / 1000),
                    "open": float(kline_info.get("open", 0)),
                    "high": float(kline_info.get("high", 0)),
                    "low": float(kline_info.get("low", 0)),
                    "close": float(kline_info.get("close", 0)),
                    "volume": float(kline_info.get("volume", 0)),
                    "confirm": kline_info.get("confirm", False)
                }
                
                # Добавляем только подтвержденные свечи
                if kline["confirm"]:
                    # Обычное хранение
                    self.kline_data.append(kline)
                    if len(self.kline_data) > self.max_klines:
                        self.kline_data = self.kline_data[-self.max_klines:]
                    
                    # Расширенное хранение для ИИ-анализа
                    enhanced_kline = self._enhance_kline_data(kline)
                    self.extended_kline_data.append(enhanced_kline)
                    if len(self.extended_kline_data) > self.max_extended_klines:
                        self.extended_kline_data = self.extended_kline_data[-self.max_extended_klines:]
                    
                    # Обновляем уровни поддержки/сопротивления
                    self._update_price_levels(kline)
                
                # Обновляем стратегию
                if self.strategy:
                    signal = await self.strategy.analyze_kline(kline)
                    if signal and self.on_signal_callback:
                        await self.on_signal_callback(signal)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки kline: {e}")
    
    def _enhance_kline_data(self, kline: dict) -> dict:
        """Расширение данных свечи для ИИ-анализа"""
        enhanced = kline.copy()
        
        try:
            # Дополнительные метрики
            open_price = kline["open"]
            high_price = kline["high"]
            low_price = kline["low"]
            close_price = kline["close"]
            volume = kline["volume"]
            
            # Размах свечи
            enhanced["range"] = high_price - low_price
            enhanced["range_percent"] = (enhanced["range"] / open_price) * 100 if open_price > 0 else 0
            
            # Тело свечи
            enhanced["body"] = abs(close_price - open_price)
            enhanced["body_percent"] = (enhanced["body"] / enhanced["range"]) * 100 if enhanced["range"] > 0 else 0
            
            # Тени
            enhanced["upper_shadow"] = high_price - max(open_price, close_price)
            enhanced["lower_shadow"] = min(open_price, close_price) - low_price
            
            # Тип свечи
            enhanced["candle_type"] = "bullish" if close_price > open_price else "bearish" if close_price < open_price else "doji"
            
            # Относительная позиция закрытия
            enhanced["close_position"] = ((close_price - low_price) / enhanced["range"]) * 100 if enhanced["range"] > 0 else 50
            
            # Объем на цену
            enhanced["volume_price_ratio"] = volume / close_price if close_price > 0 else 0
            
            # VWAP для данной свечи (приблизительно)
            enhanced["vwap_estimate"] = (high_price + low_price + close_price) / 3
            
            return enhanced
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка улучшения данных свечи: {e}")
            return kline
    
    def _update_price_levels(self, kline: dict):
        """Обновление уровней поддержки и сопротивления"""
        try:
            high_price = kline["high"]
            low_price = kline["low"]
            
            # Простое определение уровней (можно улучшить)
            # Сопротивление - локальные максимумы
            if len(self.extended_kline_data) >= 3:
                recent_highs = [k["high"] for k in self.extended_kline_data[-3:]]
                if high_price == max(recent_highs):
                    self.price_levels["resistance"].append({
                        "price": high_price,
                        "timestamp": kline["timestamp"],
                        "strength": 1
                    })
            
            # Поддержка - локальные минимумы
            if len(self.extended_kline_data) >= 3:
                recent_lows = [k["low"] for k in self.extended_kline_data[-3:]]
                if low_price == min(recent_lows):
                    self.price_levels["support"].append({
                        "price": low_price,
                        "timestamp": kline["timestamp"],
                        "strength": 1
                    })
            
            # Ограничиваем количество уровней
            if len(self.price_levels["resistance"]) > 20:
                self.price_levels["resistance"] = self.price_levels["resistance"][-20:]
            if len(self.price_levels["support"]) > 20:
                self.price_levels["support"] = self.price_levels["support"][-20:]
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления уровней цен: {e}")
    
    async def _handle_orderbook_data(self, data: dict):
        """Обработка orderbook данных с расширенным анализом"""
        try:
            orderbook_info = data.get("data", {})
            
            enhanced_orderbook = {
                "symbol": self.symbol,
                "bids": [[float(bid[0]), float(bid[1])] for bid in orderbook_info.get("b", [])],
                "asks": [[float(ask[0]), float(ask[1])] for ask in orderbook_info.get("a", [])],
                "timestamp": datetime.now().isoformat()
            }
            
            # Расширенный анализ ордербука
            enhanced_orderbook.update(self._analyze_orderbook_depth(enhanced_orderbook))
            
            self.orderbook_data = enhanced_orderbook
            
            # Сохраняем историю ордербука для анализа
            self.extended_orderbook_history.append({
                "timestamp": enhanced_orderbook["timestamp"],
                "spread": enhanced_orderbook.get("spread", 0),
                "bid_volume": enhanced_orderbook.get("total_bid_volume", 0),
                "ask_volume": enhanced_orderbook.get("total_ask_volume", 0),
                "imbalance": enhanced_orderbook.get("order_imbalance", 0)
            })
            
            if len(self.extended_orderbook_history) > self.max_orderbook_history:
                self.extended_orderbook_history = self.extended_orderbook_history[-self.max_orderbook_history:]
            
            # Обновляем профиль объема
            self._update_volume_profile(enhanced_orderbook)
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_orderbook(self.orderbook_data)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки orderbook: {e}")
    
    def _analyze_orderbook_depth(self, orderbook: dict) -> dict:
        """Расширенный анализ глубины ордербука"""
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            analysis = {}
            
            if not bids or not asks:
                return analysis
            
            # Основные метрики
            best_bid = float(bids[0][0]) if bids else 0
            best_ask = float(asks[0][0]) if asks else 0
            spread = best_ask - best_bid
            
            # Объемы
            total_bid_volume = sum(float(bid[1]) for bid in bids)
            total_ask_volume = sum(float(ask[1]) for ask in asks)
            
            # Дисбаланс ордеров
            order_imbalance = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume) if (total_bid_volume + total_ask_volume) > 0 else 0
            
            # Глубина на разных уровнях
            levels_analysis = {}
            for depth in [5, 10, 20]:
                if len(bids) >= depth and len(asks) >= depth:
                    bid_volume = sum(float(bid[1]) for bid in bids[:depth])
                    ask_volume = sum(float(ask[1]) for ask in asks[:depth])
                    levels_analysis[f"depth_{depth}"] = {
                        "bid_volume": bid_volume,
                        "ask_volume": ask_volume,
                        "ratio": bid_volume / ask_volume if ask_volume > 0 else 0
                    }
            
            # Средний размер ордера
            avg_bid_size = total_bid_volume / len(bids) if bids else 0
            avg_ask_size = total_ask_volume / len(asks) if asks else 0
            
            # Концентрация ликвидности (топ 10% ордеров)
            top_bid_count = max(1, len(bids) // 10)
            top_ask_count = max(1, len(asks) // 10)
            
            top_bid_volume = sum(float(bid[1]) for bid in sorted(bids, key=lambda x: float(x[1]), reverse=True)[:top_bid_count])
            top_ask_volume = sum(float(ask[1]) for ask in sorted(asks, key=lambda x: float(x[1]), reverse=True)[:top_ask_count])
            
            concentration_bid = (top_bid_volume / total_bid_volume) * 100 if total_bid_volume > 0 else 0
            concentration_ask = (top_ask_volume / total_ask_volume) * 100 if total_ask_volume > 0 else 0
            
            analysis.update({
                "spread": spread,
                "spread_percent": (spread / best_bid) * 100 if best_bid > 0 else 0,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "total_bid_volume": total_bid_volume,
                "total_ask_volume": total_ask_volume,
                "order_imbalance": order_imbalance,
                "bid_ask_ratio": total_bid_volume / total_ask_volume if total_ask_volume > 0 else 0,
                "avg_bid_size": avg_bid_size,
                "avg_ask_size": avg_ask_size,
                "liquidity_concentration": {
                    "bid_percent": concentration_bid,
                    "ask_percent": concentration_ask
                },
                "levels_analysis": levels_analysis,
                "market_sentiment": "bullish" if order_imbalance > 0.1 else "bearish" if order_imbalance < -0.1 else "neutral"
            })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа ордербука: {e}")
            return {}
    
    def _update_volume_profile(self, orderbook: dict):
        """Обновление профиля объема"""
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            # Создаем ценовые уровни для профиля объема
            for bid in bids[:10]:  # Топ 10 bid'ов
                price = float(bid[0])
                volume = float(bid[1])
                price_level = round(price, 2)  # Округляем для группировки
                
                if price_level not in self.volume_profile:
                    self.volume_profile[price_level] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self.volume_profile[price_level]["bid_volume"] += volume
                self.volume_profile[price_level]["total_volume"] += volume
            
            for ask in asks[:10]:  # Топ 10 ask'ов
                price = float(ask[0])
                volume = float(ask[1])
                price_level = round(price, 2)
                
                if price_level not in self.volume_profile:
                    self.volume_profile[price_level] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self.volume_profile[price_level]["ask_volume"] += volume
                self.volume_profile[price_level]["total_volume"] += volume
            
            # Ограничиваем размер профиля объема
            if len(self.volume_profile) > 100:
                # Оставляем только самые активные уровни
                sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
                self.volume_profile = dict(sorted_levels[:100])
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления профиля объема: {e}")
    
    async def _handle_trade_data(self, data: dict):
        """Обработка данных о сделках с расширенным анализом"""
        try:
            trades = data.get("data", [])
            
            for trade_info in trades:
                trade = {
                    "timestamp": int(trade_info.get("T", 0)),
                    "datetime": datetime.fromtimestamp(int(trade_info.get("T", 0)) / 1000),
                    "price": float(trade_info.get("p", 0)),
                    "size": float(trade_info.get("v", 0)),
                    "side": trade_info.get("S", ""),
                    "trade_id": trade_info.get("i", "")
                }
                
                # Добавляем расширенную информацию
                trade["value"] = trade["price"] * trade["size"]
                trade["is_large"] = trade["size"] > self._calculate_average_trade_size() * 2
                
                self.trade_data.append(trade)
                
                # Ограничиваем количество сделок
                if len(self.trade_data) > self.max_trades:
                    self.trade_data = self.trade_data[-self.max_trades:]
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_trades(trades)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки trades: {e}")
    
    def _calculate_average_trade_size(self) -> float:
        """Вычисление среднего размера сделки"""
        if not self.trade_data:
            return 0
        
        recent_trades = self.trade_data[-50:]  # Последние 50 сделок
        total_size = sum(trade["size"] for trade in recent_trades)
        return total_size / len(recent_trades)
    
    async def _ping_loop(self):
        """Цикл отправки ping сообщений"""
        while self.is_connected:
            try:
                await asyncio.sleep(self.settings.WS_PING_INTERVAL)
                
                if self.websocket and not self.websocket.closed:
                    ping_message = {
                        "op": "ping",
                        "args": [str(int(time.time() * 1000))]
                    }
                    await self.websocket.send(json.dumps(ping_message))
                    self.last_ping = time.time()
                
            except Exception as e:
                self.logger.error(f"❌ Ошибка ping: {e}")
                break
    
    def get_market_data(self, symbol: str = None) -> dict:
        """Получить текущие рыночные данные (базовые)"""
        if symbol and symbol != self.symbol:
            return {}
        
        if not self.ticker_data:
            return {}
        
        # Определяем тренд на основе изменения за 24ч
        change_24h = self.ticker_data.get("change_24h", 0)
        if change_24h > 2:
            trend = "bullish"
        elif change_24h < -2:
            trend = "bearish"
        else:
            trend = "sideways"
        
        return {
            "symbol": self.ticker_data.get("symbol", self.symbol),
            "price": f"{self.ticker_data.get('price', 0):.4f}",
            "change_24h": f"{change_24h:+.2f}%",
            "volume_24h": f"{self.ticker_data.get('volume_24h', 0):,.0f}",
            "high_24h": f"{self.ticker_data.get('high_24h', 0):.4f}",
            "low_24h": f"{self.ticker_data.get('low_24h', 0):.4f}",
            "bid": f"{self.ticker_data.get('bid', 0):.4f}",
            "ask": f"{self.ticker_data.get('ask', 0):.4f}",
            "spread": f"{abs(self.ticker_data.get('ask', 0) - self.ticker_data.get('bid', 0)):.4f}",
            "timestamp": self.ticker_data.get("timestamp"),
            "trend": trend,
            "klines_count": len(self.kline_data),
            "trades_count": len(self.trade_data)
        }
    
    def get_comprehensive_market_data(self, symbol: str = None) -> dict:
        """
        НОВЫЙ МЕТОД: Получить ВСЕ рыночные данные для ИИ-анализа
        """
        if symbol and symbol != self.symbol:
            return {}
        
        try:
            comprehensive_data = {
                # Основные рыночные данные
                "basic_market": self._get_basic_market_summary(),
                
                # Расширенные данные свечей
                "extended_klines": self._get_extended_klines_summary(),
                
                # Детальный анализ ордербука
                "orderbook_analysis": self._get_orderbook_analysis(),
                
                # Анализ сделок и активности
                "trading_activity": self._get_trading_activity_analysis(),
                
                # Технический анализ уровней
                "price_levels": self._get_price_levels_analysis(),
                
                # Профиль объема
                "volume_profile": self._get_volume_profile_analysis(),
                
                # Рыночная микроструктура
                "market_microstructure": self._get_microstructure_analysis(),
                
                # Временные метки и качество данных
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol or self.symbol,
                    "data_quality": self._assess_data_quality(),
                    "collection_period": self._get_collection_period()
                }
            }
            
            return comprehensive_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора полных рыночных данных: {e}")
            return {}
    
    def _get_basic_market_summary(self) -> dict:
        """Основные рыночные данные"""
        if not self.ticker_data:
            return {}
        
        return {
            "symbol": self.ticker_data.get("symbol", self.symbol),
            "current_price": self.ticker_data.get("price", 0),
            "change_24h_percent": self.ticker_data.get("change_24h", 0),
            "volume_24h": self.ticker_data.get("volume_24h", 0),
            "high_24h": self.ticker_data.get("high_24h", 0),
            "low_24h": self.ticker_data.get("low_24h", 0),
            "best_bid": self.ticker_data.get("bid", 0),
            "best_ask": self.ticker_data.get("ask", 0),
            "spread": abs(self.ticker_data.get("ask", 0) - self.ticker_data.get("bid", 0)),
            "spread_percent": (abs(self.ticker_data.get("ask", 0) - self.ticker_data.get("bid", 0)) / self.ticker_data.get("bid", 1)) * 100
        }
    
    def _get_extended_klines_summary(self) -> dict:
        """Расширенная сводка по свечам"""
        if not self.extended_kline_data:
            return {}
        
        try:
            recent_klines = self.extended_kline_data[-50:]  # Последние 50 свечей
            
            # Ценовые данные
            closes = [k["close"] for k in recent_klines]
            highs = [k["high"] for k in recent_klines]
            lows = [k["low"] for k in recent_klines]
            volumes = [k["volume"] for k in recent_klines]
            ranges = [k.get("range", 0) for k in recent_klines]
            
            # Статистика цен
            price_stats = {
                "current_price": closes[-1] if closes else 0,
                "avg_price": sum(closes) / len(closes) if closes else 0,
                "max_price": max(highs) if highs else 0,
                "min_price": min(lows) if lows else 0,
                "price_volatility": self._calculate_volatility(closes),
                "price_trend": self._determine_price_trend(closes)
            }
            
            # Статистика объемов
            volume_stats = {
                "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
                "max_volume": max(volumes) if volumes else 0,
                "min_volume": min(volumes) if volumes else 0,
                "volume_trend": self._determine_volume_trend(volumes),
                "volume_price_correlation": self._calculate_volume_price_correlation(closes, volumes)
            }
            
            # Анализ свечей
            candle_analysis = {
                "bullish_candles": len([k for k in recent_klines if k.get("candle_type") == "bullish"]),
                "bearish_candles": len([k for k in recent_klines if k.get("candle_type") == "bearish"]),
                "doji_candles": len([k for k in recent_klines if k.get("candle_type") == "doji"]),
                "avg_body_percent": sum(k.get("body_percent", 0) for k in recent_klines) / len(recent_klines),
                "avg_range": sum(ranges) / len(ranges) if ranges else 0,
                "high_volatility_periods": len([r for r in ranges if r > sum(ranges) / len(ranges) * 1.5])
            }
            
            return {
                "total_klines": len(self.extended_kline_data),
                "analyzed_period": len(recent_klines),
                "price_statistics": price_stats,
                "volume_statistics": volume_stats,
                "candle_analysis": candle_analysis,
                "raw_klines": recent_klines[-20:]  # Последние 20 свечей с полными данными
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа свечей: {e}")
            return {}
    
    def _get_orderbook_analysis(self) -> dict:
        """Детальный анализ ордербука"""
        if not self.orderbook_data:
            return {}
        
        try:
            orderbook = self.orderbook_data.copy()
            
            # История изменений ордербука
            history_analysis = {}
            if len(self.extended_orderbook_history) > 1:
                recent_history = self.extended_orderbook_history[-10:]
                spreads = [h["spread"] for h in recent_history]
                imbalances = [h["imbalance"] for h in recent_history]
                
                history_analysis = {
                    "avg_spread": sum(spreads) / len(spreads),
                    "spread_volatility": self._calculate_volatility(spreads),
                    "avg_imbalance": sum(imbalances) / len(imbalances),
                    "imbalance_trend": "increasing" if imbalances[-1] > imbalances[0] else "decreasing",
                    "stability_score": self._calculate_orderbook_stability(recent_history)
                }
            
            # Текущий анализ
            current_analysis = {
                "market_sentiment": orderbook.get("market_sentiment", "neutral"),
                "liquidity_score": self._calculate_liquidity_score(orderbook),
                "order_flow_pressure": self._calculate_order_flow_pressure(orderbook),
                "depth_imbalance": orderbook.get("order_imbalance", 0)
            }
            
            return {
                "current_orderbook": orderbook,
                "historical_analysis": history_analysis,
                "current_analysis": current_analysis,
                "top_levels": {
                    "bids": orderbook.get("bids", [])[:5],
                    "asks": orderbook.get("asks", [])[:5]
                }
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа ордербука: {e}")
            return {}
    
    def _get_trading_activity_analysis(self) -> dict:
        """Анализ торговой активности"""
        if not self.trade_data:
            return {}
        
        try:
            recent_trades = self.trade_data[-100:]
            
            # Базовые метрики
            buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
            sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
            large_trades = [t for t in recent_trades if t.get("is_large", False)]
            
            # Анализ объемов
            total_buy_volume = sum(t["size"] for t in buy_trades)
            total_sell_volume = sum(t["size"] for t in sell_trades)
            total_buy_value = sum(t.get("value", 0) for t in buy_trades)
            total_sell_value = sum(t.get("value", 0) for t in sell_trades)
            
            # Анализ цен
            trade_prices = [t["price"] for t in recent_trades]
            price_impact = self._calculate_price_impact(recent_trades)
            
            # Активность во времени
            time_analysis = self._analyze_trading_time_patterns(recent_trades)
            
            return {
                "total_trades": len(recent_trades),
                "buy_sell_ratio": {
                    "trades": len(buy_trades) / len(sell_trades) if sell_trades else 0,
                    "volume": total_buy_volume / total_sell_volume if total_sell_volume > 0 else 0,
                    "value": total_buy_value / total_sell_value if total_sell_value > 0 else 0
                },
                "large_trades": {
                    "count": len(large_trades),
                    "percentage": (len(large_trades) / len(recent_trades)) * 100,
                    "avg_size": sum(t["size"] for t in large_trades) / len(large_trades) if large_trades else 0
                },
                "price_analysis": {
                    "avg_price": sum(trade_prices) / len(trade_prices) if trade_prices else 0,
                    "price_range": max(trade_prices) - min(trade_prices) if trade_prices else 0,
                    "price_impact": price_impact,
                    "trend": "up" if trade_prices[-1] > trade_prices[0] else "down" if len(trade_prices) > 1 else "neutral"
                },
                "time_patterns": time_analysis,
                "recent_trades_sample": recent_trades[-10:]  # Последние 10 сделок
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа торговой активности: {e}")
            return {}
    
    def _get_price_levels_analysis(self) -> dict:
        """Анализ уровней поддержки и сопротивления"""
        try:
            # Кластеризация уровней поддержки
            support_clusters = self._cluster_price_levels(self.price_levels["support"])
            resistance_clusters = self._cluster_price_levels(self.price_levels["resistance"])
            
            # Определение ключевых уровней
            key_levels = self._identify_key_levels(support_clusters, resistance_clusters)
            
            return {
                "support_levels": support_clusters,
                "resistance_levels": resistance_clusters,
                "key_levels": key_levels,
                "current_price_context": self._analyze_current_price_context(key_levels),
                "level_strength": self._calculate_level_strength(support_clusters, resistance_clusters)
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа ценовых уровней: {e}")
            return {}
    
    def _get_volume_profile_analysis(self) -> dict:
        """Анализ профиля объема"""
        try:
            if not self.volume_profile:
                return {}
            
            # Сортируем уровни по объему
            sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
            
            # VPOC (Volume Point of Control) - уровень с максимальным объемом
            vpoc = sorted_levels[0] if sorted_levels else None
            
            # Высокообъемные узлы (HVN) и низкообъемные узлы (LVN)
            avg_volume = sum(data["total_volume"] for data in self.volume_profile.values()) / len(self.volume_profile)
            hvn_levels = [(price, data) for price, data in sorted_levels if data["total_volume"] > avg_volume * 1.5]
            lvn_levels = [(price, data) for price, data in sorted_levels if data["total_volume"] < avg_volume * 0.5]
            
            return {
                "vpoc": {"price": vpoc[0], "volume": vpoc[1]["total_volume"]} if vpoc else None,
                "high_volume_nodes": [{"price": price, "volume": data["total_volume"]} for price, data in hvn_levels[:10]],
                "low_volume_nodes": [{"price": price, "volume": data["total_volume"]} for price, data in lvn_levels[:10]],
                "volume_distribution": self._analyze_volume_distribution(),
                "price_acceptance": self._analyze_price_acceptance()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа профиля объема: {e}")
            return {}
    
    def _get_microstructure_analysis(self) -> dict:
        """Анализ микроструктуры рынка"""
        try:
            # Агрегация различных аспектов микроструктуры
            return {
                "liquidity_metrics": self._calculate_liquidity_metrics(),
                "order_flow_metrics": self._calculate_order_flow_metrics(),
                "price_discovery": self._analyze_price_discovery(),
                "market_efficiency": self._assess_market_efficiency(),
                "volatility_clustering": self._detect_volatility_clustering()
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка анализа микроструктуры: {e}")
            return {}
    
    # Вспомогательные методы для анализа
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Расчет волатильности"""
        if len(prices) < 2:
            return 0
        
        mean_price = sum(prices) / len(prices)
        variance = sum((price - mean_price) ** 2 for price in prices) / len(prices)
        return math.sqrt(variance) / mean_price * 100
    
    def _determine_price_trend(self, prices: List[float]) -> str:
        """Определение тренда цены"""
        if len(prices) < 2:
            return "neutral"
        
        recent_avg = sum(prices[-5:]) / len(prices[-5:])
        earlier_avg = sum(prices[-10:-5]) / len(prices[-10:-5]) if len(prices) >= 10 else prices[0]
        
        if recent_avg > earlier_avg * 1.002:
            return "uptrend"
        elif recent_avg < earlier_avg * 0.998:
            return "downtrend"
        else:
            return "sideways"
    
    def _determine_volume_trend(self, volumes: List[float]) -> str:
        """Определение тренда объема"""
        if len(volumes) < 2:
            return "neutral"
        
        recent_avg = sum(volumes[-5:]) / len(volumes[-5:])
        earlier_avg = sum(volumes[-10:-5]) / len(volumes[-10:-5]) if len(volumes) >= 10 else volumes[0]
        
        if recent_avg > earlier_avg * 1.1:
            return "increasing"
        elif recent_avg < earlier_avg * 0.9:
            return "decreasing"
        else:
            return "stable"
    
    def _calculate_volume_price_correlation(self, prices: List[float], volumes: List[float]) -> float:
        """Корреляция объема и цены"""
        if len(prices) != len(volumes) or len(prices) < 2:
            return 0
        
        # Простая корреляция
        price_changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        volume_changes = [volumes[i] - volumes[i-1] for i in range(1, len(volumes))]
        
        if not price_changes or not volume_changes:
            return 0
        
        mean_price_change = sum(price_changes) / len(price_changes)
        mean_volume_change = sum(volume_changes) / len(volume_changes)
        
        numerator = sum((price_changes[i] - mean_price_change) * (volume_changes[i] - mean_volume_change) for i in range(len(price_changes)))
        
        price_variance = sum((pc - mean_price_change) ** 2 for pc in price_changes)
        volume_variance = sum((vc - mean_volume_change) ** 2 for vc in volume_changes)
        
        denominator = math.sqrt(price_variance * volume_variance)
        
        return numerator / denominator if denominator != 0 else 0
    
    def _assess_data_quality(self) -> dict:
        """Оценка качества данных"""
        return {
            "websocket_connected": self.is_connected,
            "data_freshness": time.time() - self.last_data_time,
            "klines_available": len(self.extended_kline_data),
            "orderbook_available": bool(self.orderbook_data),
            "trades_available": len(self.trade_data),
            "price_levels_identified": len(self.price_levels["support"]) + len(self.price_levels["resistance"]),
            "volume_profile_depth": len(self.volume_profile)
        }
    
    def _get_collection_period(self) -> dict:
        """Период сбора данных"""
        if not self.extended_kline_data:
            return {}
        
        first_kline = self.extended_kline_data[0]
        last_kline = self.extended_kline_data[-1]
        
        return {
            "start_time": first_kline["datetime"].isoformat(),
            "end_time": last_kline["datetime"].isoformat(),
            "duration_minutes": (last_kline["datetime"] - first_kline["datetime"]).total_seconds() / 60,
            "timeframe": self.settings.STRATEGY_TIMEFRAME
        }
    
    # Остальные вспомогательные методы (заглушки для полноты)
    
    def _calculate_orderbook_stability(self, history: List[dict]) -> float:
        """Оценка стабильности ордербука"""
        return 0.5  # Заглушка
    
    def _calculate_liquidity_score(self, orderbook: dict) -> float:
        """Оценка ликвидности"""
        return 0.5  # Заглушка
    
    def _calculate_order_flow_pressure(self, orderbook: dict) -> float:
        """Давление ордер-флоу"""
        return 0.0  # Заглушка
    
    def _calculate_price_impact(self, trades: List[dict]) -> float:
        """Ценовое воздействие сделок"""
        return 0.0  # Заглушка
    
    def _analyze_trading_time_patterns(self, trades: List[dict]) -> dict:
        """Анализ временных паттернов торговли"""
        return {}  # Заглушка
    
    def _cluster_price_levels(self, levels: List[dict]) -> List[dict]:
        """Кластеризация ценовых уровней"""
        return levels[:10]  # Заглушка
    
    def _identify_key_levels(self, support: List[dict], resistance: List[dict]) -> dict:
        """Определение ключевых уровней"""
        return {}  # Заглушка
    
    def _analyze_current_price_context(self, key_levels: dict) -> dict:
        """Анализ текущего ценового контекста"""
        return {}  # Заглушка
    
    def _calculate_level_strength(self, support: List[dict], resistance: List[dict]) -> dict:
        """Расчет силы уровней"""
        return {}  # Заглушка
    
    def _analyze_volume_distribution(self) -> dict:
        """Анализ распределения объема"""
        return {}  # Заглушка
    
    def _analyze_price_acceptance(self) -> dict:
        """Анализ принятия цены"""
        return {}  # Заглушка
    
    def _calculate_liquidity_metrics(self) -> dict:
        """Метрики ликвидности"""
        return {}  # Заглушка
    
    def _calculate_order_flow_metrics(self) -> dict:
        """Метрики ордер-флоу"""
        return {}  # Заглушка
    
    def _analyze_price_discovery(self) -> dict:
        """Анализ ценообразования"""
        return {}  # Заглушка
    
    def _assess_market_efficiency(self) -> dict:
        """Оценка эффективности рынка"""
        return {}  # Заглушка
    
    def _detect_volatility_clustering(self) -> dict:
        """Обнаружение кластеров волатильности"""
        return {}  # Заглушка
    
    def get_connection_status(self) -> dict:
        """Получить статус соединения"""
        return {
            "is_connected": self.is_connected,
            "reconnect_count": self.reconnect_count,
            "last_ping": self.last_ping,
            "last_data_time": self.last_data_time,
            "data_delay": time.time() - self.last_data_time if self.last_data_time else 0,
            "websocket_url": self.settings.websocket_url,
            "subscribed_symbol": self.symbol,
            "extended_data_available": {
                "klines": len(self.extended_kline_data),
                "orderbook_history": len(self.extended_orderbook_history),
                "volume_profile": len(self.volume_profile),
                "price_levels": len(self.price_levels["support"]) + len(self.price_levels["resistance"])
            }
        }
