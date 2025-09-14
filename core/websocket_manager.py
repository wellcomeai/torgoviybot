"""
WebSocket менеджер для подключения к Bybit
Обработка потоков данных и управление соединением
"""

import asyncio
import json
import logging
import time
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
        
        # Задачи asyncio
        self.ping_task = None
        self.reconnect_task = None
        self.main_task = None
        
        # Лимиты данных
        self.max_klines = self.settings.KLINE_LIMIT
        self.max_trades = 1000
        
        self.logger = logging.getLogger(__name__)
        
    async def start(self):
        """Запуск WebSocket соединения"""
        try:
            self.logger.info(f"🔌 Подключение к Bybit WebSocket...")
            self.logger.info(f"   URL: {self.settings.websocket_url}")
            self.logger.info(f"   Символ: {self.symbol}")
            
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
            
            # Подписка на данные
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
        """Обработка kline (свечи) данных"""
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
                    self.kline_data.append(kline)
                    
                    # Ограничиваем количество свечей
                    if len(self.kline_data) > self.max_klines:
                        self.kline_data = self.kline_data[-self.max_klines:]
                
                # Обновляем стратегию
                if self.strategy:
                    signal = await self.strategy.analyze_kline(kline)
                    if signal and self.on_signal_callback:
                        await self.on_signal_callback(signal)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки kline: {e}")
    
    async def _handle_orderbook_data(self, data: dict):
        """Обработка orderbook данных"""
        try:
            orderbook_info = data.get("data", {})
            
            self.orderbook_data = {
                "symbol": self.symbol,
                "bids": [[float(bid[0]), float(bid[1])] for bid in orderbook_info.get("b", [])[:10]],
                "asks": [[float(ask[0]), float(ask[1])] for ask in orderbook_info.get("a", [])[:10]],
                "timestamp": datetime.now().isoformat()
            }
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_orderbook(self.orderbook_data)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки orderbook: {e}")
    
    async def _handle_trade_data(self, data: dict):
        """Обработка данных о сделках"""
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
                
                self.trade_data.append(trade)
                
                # Ограничиваем количество сделок
                if len(self.trade_data) > self.max_trades:
                    self.trade_data = self.trade_data[-self.max_trades:]
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_trades(trades)
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки trades: {e}")
    
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
        """Получить текущие рыночные данные"""
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
    
    def get_connection_status(self) -> dict:
        """Получить статус соединения"""
        return {
            "is_connected": self.is_connected,
            "reconnect_count": self.reconnect_count,
            "last_ping": self.last_ping,
            "last_data_time": self.last_data_time,
            "data_delay": time.time() - self.last_data_time if self.last_data_time else 0,
            "websocket_url": self.settings.websocket_url,
            "subscribed_symbol": self.symbol
        }
