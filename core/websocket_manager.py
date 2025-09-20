"""
WebSocket менеджер для подключения к Bybit
Обработка потоков данных и управление соединением
ИСПРАВЛЕНО: HTTP интеграция для получения корректных ticker данных
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
import httpx

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
        
        # HTTP клиент для REST API запросов
        self.http_client = httpx.AsyncClient(timeout=10.0)
        
        # Хранение данных
        self.ticker_data = {}
        self.kline_data = []
        self.orderbook_data = {}
        self.trade_data = []
        
        # Расширенное хранение для ИИ-анализа
        self.extended_kline_data = []
        self.extended_orderbook_history = []
        self.volume_profile = {}
        self.price_levels = {"support": [], "resistance": []}
        
        # Задачи asyncio
        self.ping_task = None
        self.reconnect_task = None
        self.main_task = None
        
        # Лимиты данных
        self.max_klines = self.settings.KLINE_LIMIT
        self.max_trades = 1000
        self.max_extended_klines = self.settings.AI_KLINES_COUNT
        self.max_orderbook_history = 50
        
        # Счетчики для диагностики
        self.message_counts = {
            "total": 0,
            "ticker": 0,
            "kline": 0,
            "orderbook": 0,
            "trade": 0,
            "ping": 0,
            "subscribe": 0,
            "unknown": 0
        }
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"WebSocket Manager инициализирован для {symbol}")
        
    async def start(self):
        """Запуск WebSocket соединения"""
        try:
            self.logger.info(f"Подключение к Bybit WebSocket...")
            self.logger.info(f"   URL: {self.settings.websocket_url}")
            self.logger.info(f"   REST API: {self.settings.bybit_rest_url}")
            self.logger.info(f"   Символ: {self.symbol}")
            self.logger.info(f"   Таймфрейм: {self.settings.STRATEGY_TIMEFRAME}")
            
            # Запуск основной задачи
            self.main_task = asyncio.create_task(self._main_loop())
            
            # Ждем установления соединения
            for attempt in range(10):
                if self.is_connected:
                    break
                await asyncio.sleep(1)
                self.logger.info(f"Ожидание подключения... попытка {attempt + 1}/10")
            
            if not self.is_connected:
                raise Exception("Не удалось установить соединение в течение 10 секунд")
            
            self.logger.info("WebSocket соединение установлено")
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска WebSocket: {e}")
            raise
    
    async def stop(self):
        """Остановка WebSocket соединения"""
        try:
            self.logger.info("Остановка WebSocket соединения...")
            
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
            
            # Закрытие HTTP клиента
            await self.http_client.aclose()
                
            self.logger.info("WebSocket соединение закрыто")
            
        except Exception as e:
            self.logger.error(f"Ошибка закрытия WebSocket: {e}")
    
    async def get_fresh_ticker_data(self) -> dict:
        """Получение свежих ticker данных через HTTP REST API"""
        try:
            self.logger.info(f"🌐 Запрос свежих ticker данных через HTTP для {self.symbol}...")
            
            url = f"{self.settings.bybit_rest_url}/v5/market/tickers"
            params = {
                "category": "linear",
                "symbol": self.symbol
            }
            
            response = await self.http_client.get(url, params=params)
            
            if response.status_code != 200:
                self.logger.error(f"HTTP запрос неуспешен: {response.status_code}")
                return {}
            
            data = response.json()
            
            if data.get("retCode") != 0:
                self.logger.error(f"Bybit API ошибка: {data.get('retMsg', 'Unknown error')}")
                return {}
            
            ticker_list = data.get("result", {}).get("list", [])
            
            if not ticker_list:
                self.logger.error(f"Нет ticker данных для {self.symbol}")
                return {}
            
            fresh_ticker = ticker_list[0]
            
            self.logger.info(f"✅ HTTP ticker получен: {fresh_ticker.get('symbol')} @ ${fresh_ticker.get('lastPrice')}")
            self.logger.info(f"   Изменение 24ч: {float(fresh_ticker.get('price24hPcnt', 0)) * 100:.2f}%")
            self.logger.info(f"   Объем 24ч: {fresh_ticker.get('volume24h', 0)}")
            
            return fresh_ticker
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка HTTP запроса ticker данных: {e}")
            return {}
    
    async def _main_loop(self):
        """Основной цикл WebSocket соединения"""
        while True:
            try:
                await self._connect_and_subscribe()
                await self._listen_messages()
                
            except Exception as e:
                self.logger.error(f"Ошибка в главном цикле WebSocket: {e}")
                self.is_connected = False
                
                if self.reconnect_count < self.settings.WS_RECONNECT_ATTEMPTS:
                    self.reconnect_count += 1
                    delay = self.settings.WS_RECONNECT_DELAY * self.reconnect_count
                    self.logger.info(f"Переподключение через {delay} сек (попытка {self.reconnect_count})")
                    await asyncio.sleep(delay)
                else:
                    self.logger.error("Превышен лимит попыток переподключения")
                    break
    
    async def _connect_and_subscribe(self):
        """Подключение и подписка на данные"""
        try:
            self.logger.info("Инициализация WebSocket соединения...")
            
            # Подключение к WebSocket
            self.websocket = await websockets.connect(
                self.settings.websocket_url,
                ping_interval=None,
                ping_timeout=None,
                close_timeout=10
            )
            
            self.logger.info(f"WebSocket подключен к {self.settings.websocket_url}")
            
            # Подписываемся БЕЗ ticker (будем использовать HTTP)
            subscriptions = [
                self.settings.get_kline_subscription(),        # kline.5.BTCUSDT  
                self.settings.get_orderbook_subscription(),    # orderbook.50.BTCUSDT
                self.settings.get_trade_subscription()         # publicTrade.BTCUSDT
            ]
            
            self.logger.info(f"Отправляем подписку на топики: {subscriptions}")
            
            subscribe_message = {
                "op": "subscribe",
                "args": subscriptions
            }
            
            await self.websocket.send(json.dumps(subscribe_message))
            self.logger.info("Запрос подписки отправлен (БЕЗ ticker - используем HTTP)")
            
            # Запуск ping задачи (отправка ping от клиента каждые 20 сек)
            if self.ping_task and not self.ping_task.done():
                self.ping_task.cancel()
            
            self.ping_task = asyncio.create_task(self._ping_loop())
            
            self.is_connected = True
            self.reconnect_count = 0
            
        except Exception as e:
            self.logger.error(f"Ошибка подключения: {e}")
            raise
    
    async def _listen_messages(self):
        """Прослушивание сообщений WebSocket"""
        self.logger.info("Начинаем прослушивание сообщений...")
        
        async for message in self.websocket:
            try:
                self.message_counts["total"] += 1
                
                # Логируем каждое полученное сообщение
                if self.message_counts["total"] <= 10 or self.message_counts["total"] % 100 == 0:
                    self.logger.info(f"Сообщение #{self.message_counts['total']}: {message[:200]}...")
                
                data = json.loads(message)
                await self._handle_message(data)
                self.last_data_time = time.time()
                
                # Периодически логируем статистику
                if self.message_counts["total"] % 50 == 0:
                    self._log_message_statistics()
                
            except json.JSONDecodeError as e:
                self.logger.error(f"Ошибка парсинга JSON: {e}, сообщение: {message}")
            except Exception as e:
                self.logger.error(f"Ошибка обработки сообщения: {e}")
    
    def _log_message_statistics(self):
        """Логирование статистики сообщений"""
        self.logger.info("=== СТАТИСТИКА СООБЩЕНИЙ ===")
        for msg_type, count in self.message_counts.items():
            self.logger.info(f"  {msg_type}: {count}")
        self.logger.info(f"=== ДАННЫЕ В ПАМЯТИ ===")
        self.logger.info(f"  ticker_data: {bool(self.ticker_data)} (через HTTP)")
        self.logger.info(f"  kline_data: {len(self.kline_data)}")
        self.logger.info(f"  orderbook_data: {bool(self.orderbook_data)}")
        self.logger.info(f"  trade_data: {len(self.trade_data)}")
    
    async def _handle_message(self, data: dict):
        """Обработка входящих сообщений"""
        try:
            op = data.get("op", "")
            topic = data.get("topic", "")
            success = data.get("success", None)
            
            # ИСПРАВЛЕНО: правильная обработка ping от сервера
            if op == "ping":
                self.message_counts["ping"] += 1
                # Отвечаем на ping сервера с теми же args
                pong_message = {"op": "pong", "args": data.get("args", [])}
                await self.websocket.send(json.dumps(pong_message))
                self.logger.debug(f"Ответили pong на ping: {data.get('args', [])}")
                return
                
            # Обработка подтверждения подписки
            if success is not None and op == "subscribe":
                self.message_counts["subscribe"] += 1
                if success:
                    self.logger.info(f"✅ Подписка успешна: {data.get('ret_msg', 'OK')}")
                else:
                    self.logger.error(f"❌ Ошибка подписки: {data.get('ret_msg', 'Unknown error')}")
                return
            
            # Обработка данных по топикам
            if topic:
                self.logger.debug(f"Топик: '{topic}', размер данных: {len(data.get('data', []))}")
                
                if topic.startswith("tickers."):
                    # ИГНОРИРУЕМ ticker данные из WebSocket
                    self.message_counts["ticker"] += 1
                    self.logger.debug("Игнорируем WebSocket ticker данные (используем HTTP)")
                elif topic.startswith("kline."):
                    self.message_counts["kline"] += 1
                    await self._handle_kline_data(data)
                elif topic.startswith("orderbook."):
                    self.message_counts["orderbook"] += 1
                    await self._handle_orderbook_data(data)
                elif topic.startswith("publicTrade."):
                    self.message_counts["trade"] += 1
                    await self._handle_trade_data(data)
                else:
                    self.message_counts["unknown"] += 1
                    self.logger.warning(f"Неизвестный топик: {topic}")
            else:
                self.message_counts["unknown"] += 1
                self.logger.warning(f"Сообщение без топика: {json.dumps(data)[:200]}...")
        
        except Exception as e:
            self.logger.error(f"Ошибка обработки сообщения: {e}")
    
    async def _handle_kline_data(self, data: dict):
        """Обработка kline (свечи) данных"""
        try:
            self.logger.debug("Обработка kline данных...")
            klines = data.get("data", [])
            
            if not klines:
                self.logger.warning("Пустые kline данные")
                return
            
            self.logger.info(f"Получено {len(klines)} свечей")
            
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
                
                self.logger.debug(f"Kline: {kline['datetime']}, OHLC: {kline['open']}/{kline['high']}/{kline['low']}/{kline['close']}, confirm: {kline['confirm']}")
                
                # Добавляем только подтвержденные свечи
                if kline["confirm"]:
                    self.logger.info(f"Добавляем подтвержденную свечу: close=${kline['close']}")
                    
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
                    
                    self.logger.info(f"Всего свечей в памяти: обычных={len(self.kline_data)}, расширенных={len(self.extended_kline_data)}")
                
                # Обновляем стратегию
                if self.strategy:
                    signal = await self.strategy.analyze_kline(kline)
                    if signal and self.on_signal_callback:
                        await self.on_signal_callback(signal)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки kline: {e}")
            self.logger.error(f"Kline данные: {data}")
    
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
            self.logger.error(f"Ошибка улучшения данных свечи: {e}")
            return kline
    
    def _update_price_levels(self, kline: dict):
        """Обновление уровней поддержки и сопротивления"""
        try:
            high_price = kline["high"]
            low_price = kline["low"]
            
            # Простое определение уровней
            if len(self.extended_kline_data) >= 3:
                recent_highs = [k["high"] for k in self.extended_kline_data[-3:]]
                if high_price == max(recent_highs):
                    self.price_levels["resistance"].append({
                        "price": high_price,
                        "timestamp": kline["timestamp"],
                        "strength": 1
                    })
            
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
            self.logger.error(f"Ошибка обновления уровней цен: {e}")
    
    async def _handle_orderbook_data(self, data: dict):
        """Обработка orderbook данных"""
        try:
            self.logger.debug("Обработка orderbook данных...")
            orderbook_info = data.get("data", {})
            
            if not orderbook_info:
                self.logger.warning("Пустые orderbook данные")
                return
            
            bids = orderbook_info.get("b", [])
            asks = orderbook_info.get("a", [])
            
            self.logger.debug(f"Orderbook: {len(bids)} bids, {len(asks)} asks")
            
            enhanced_orderbook = {
                "symbol": self.symbol,
                "bids": [[float(bid[0]), float(bid[1])] for bid in bids],
                "asks": [[float(ask[0]), float(ask[1])] for ask in asks],
                "timestamp": datetime.now().isoformat()
            }
            
            # Расширенный анализ ордербука
            enhanced_orderbook.update(self._analyze_orderbook_depth(enhanced_orderbook))
            
            self.orderbook_data = enhanced_orderbook
            
            if enhanced_orderbook.get("best_bid") and enhanced_orderbook.get("best_ask"):
                self.logger.info(f"Orderbook обновлен: bid=${enhanced_orderbook['best_bid']:.4f}, ask=${enhanced_orderbook['best_ask']:.4f}")
            
            # Сохраняем историю ордербука
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
            self.logger.error(f"Ошибка обработки orderbook: {e}")
            self.logger.error(f"Orderbook данные: {data}")
    
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
            
            analysis.update({
                "spread": spread,
                "spread_percent": (spread / best_bid) * 100 if best_bid > 0 else 0,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "total_bid_volume": total_bid_volume,
                "total_ask_volume": total_ask_volume,
                "order_imbalance": order_imbalance,
                "market_sentiment": "bullish" if order_imbalance > 0.1 else "bearish" if order_imbalance < -0.1 else "neutral"
            })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа ордербука: {e}")
            return {}
    
    def _update_volume_profile(self, orderbook: dict):
        """Обновление профиля объема"""
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            for bid in bids[:10]:
                price = float(bid[0])
                volume = float(bid[1])
                price_level = round(price, 2)
                
                if price_level not in self.volume_profile:
                    self.volume_profile[price_level] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self.volume_profile[price_level]["bid_volume"] += volume
                self.volume_profile[price_level]["total_volume"] += volume
            
            for ask in asks[:10]:
                price = float(ask[0])
                volume = float(ask[1])
                price_level = round(price, 2)
                
                if price_level not in self.volume_profile:
                    self.volume_profile[price_level] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self.volume_profile[price_level]["ask_volume"] += volume
                self.volume_profile[price_level]["total_volume"] += volume
            
            # Ограничиваем размер профиля объема
            if len(self.volume_profile) > 100:
                sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
                self.volume_profile = dict(sorted_levels[:100])
                
        except Exception as e:
            self.logger.error(f"Ошибка обновления профиля объема: {e}")
    
    async def _handle_trade_data(self, data: dict):
        """Обработка данных о сделках"""
        try:
            self.logger.debug("Обработка trade данных...")
            trades = data.get("data", [])
            
            if not trades:
                self.logger.warning("Пустые trade данные")
                return
            
            self.logger.debug(f"Получено {len(trades)} сделок")
            
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
            
            self.logger.info(f"Добавлено {len(trades)} сделок, всего в памяти: {len(self.trade_data)}")
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_trades(trades)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки trades: {e}")
            self.logger.error(f"Trade данные: {data}")
    
    def _calculate_average_trade_size(self) -> float:
        """Вычисление среднего размера сделки"""
        if not self.trade_data:
            return 0
        
        recent_trades = self.trade_data[-50:]
        total_size = sum(trade["size"] for trade in recent_trades)
        return total_size / len(recent_trades)
    
    async def _ping_loop(self):
        """Цикл отправки ping сообщений (от клиента)"""
        while self.is_connected:
            try:
                await asyncio.sleep(20)  # Каждые 20 секунд как рекомендует Bybit
                
                if self.websocket and not self.websocket.closed:
                    # Отправляем ping от клиента
                    client_ping = {
                        "op": "ping", 
                        "args": [str(int(time.time() * 1000))]
                    }
                    await self.websocket.send(json.dumps(client_ping))
                    self.last_ping = time.time()
                    self.logger.debug(f"Отправлен client ping: {client_ping['args'][0]}")
                
            except Exception as e:
                self.logger.error(f"Ошибка ping: {e}")
                break
    
    def get_market_data(self, symbol: str = None) -> dict:
        """Получить текущие рыночные данные (базовые)"""
        if symbol and symbol != self.symbol:
            return {}
        
        # ИСПРАВЛЕНИЕ: Если ticker_data пуст, пытаемся получить базовые данные
        if not self.ticker_data and self.kline_data:
            # Используем последнюю свечу как источник данных
            last_kline = self.kline_data[-1]
            current_price = last_kline.get("close", 0)
            
            return {
                "symbol": self.symbol,
                "price": f"{current_price:.4f}",
                "change_24h": "N/A",
                "volume_24h": "N/A", 
                "high_24h": f"{last_kline.get('high', 0):.4f}",
                "low_24h": f"{last_kline.get('low', 0):.4f}",
                "bid": f"{current_price:.4f}",
                "ask": f"{current_price + 1:.4f}",
                "spread": "1.0000",
                "timestamp": datetime.now().isoformat(),
                "trend": "unknown",
                "klines_count": len(self.kline_data),
                "trades_count": len(self.trade_data),
                "data_source": "klines_fallback"
            }
        
        if not self.ticker_data:
            self.logger.warning("ticker_data пуст и нет klines данных")
            return {}
        
        # Остальной код остается прежним...
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
            "trades_count": len(self.trade_data),
            "data_source": "ticker"
        }
    
    async def get_comprehensive_market_data(self, symbol: str = None) -> dict:
        """Получить ВСЕ рыночные данные для ИИ-анализа с HTTP ticker"""
        if symbol and symbol != self.symbol:
            self.logger.warning(f"Запрошен символ {symbol}, но WebSocket подключен к {self.symbol}")
            return {}
        
        try:
            self.logger.info("🔄 Начинаем сбор comprehensive market data с HTTP ticker...")
            
            # НОВОЕ: Получаем свежие ticker данные через HTTP
            fresh_ticker = await self.get_fresh_ticker_data()
            
            if not fresh_ticker:
                self.logger.error("❌ Не удалось получить свежие ticker данные")
                return {}
            
            # Проверяем доступность WebSocket данных
            if not self.kline_data:
                self.logger.warning("kline_data пуст")
            else:
                self.logger.info(f"kline_data: {len(self.kline_data)} обычных свечей")
            
            if not self.extended_kline_data:
                self.logger.warning("extended_kline_data пуст")
            else:
                self.logger.info(f"extended_kline_data: {len(self.extended_kline_data)} расширенных свечей")
            
            # Формируем полные данные
            comprehensive_data = {
                "basic_market": self._get_basic_market_summary_from_http(fresh_ticker),
                "technical_indicators": self._get_technical_indicators_data(),
                "extended_klines": self._get_extended_klines_summary(),
                "orderbook_analysis": self._get_orderbook_analysis(),
                "trading_activity": self._get_trading_activity_analysis(),
                "price_levels": self._get_price_levels_analysis(),
                "volume_profile": self._get_volume_profile_analysis(),
                "market_microstructure": self._get_microstructure_analysis(),
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol or self.symbol,
                    "data_quality": self._assess_data_quality(),
                    "collection_period": self._get_collection_period(),
                    "data_sources": {
                        "ticker": "HTTP REST API",
                        "klines": "WebSocket",
                        "orderbook": "WebSocket", 
                        "trades": "WebSocket"
                    }
                }
            }
            
            self.logger.info(f"✅ Comprehensive data собраны: {len(comprehensive_data)} секций")
            
            # Логируем что в каждой секции
            for section, data in comprehensive_data.items():
                if isinstance(data, dict):
                    self.logger.debug(f"  {section}: {len(data)} полей")
                else:
                    self.logger.debug(f"  {section}: {type(data)}")
            
            return comprehensive_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сбора полных рыночных данных: {e}")
            return {}
    
    def _get_basic_market_summary_from_http(self, http_ticker: dict) -> dict:
        """Основные рыночные данные из HTTP ticker"""
        if not http_ticker:
            self.logger.warning("HTTP ticker данные пусты")
            return {}
        
        try:
            summary = {
                "symbol": http_ticker.get("symbol", self.symbol),
                "current_price": float(http_ticker.get("lastPrice", 0)),
                "change_24h_percent": float(http_ticker.get("price24hPcnt", 0)) * 100,
                "volume_24h": float(http_ticker.get("volume24h", 0)),
                "high_24h": float(http_ticker.get("highPrice24h", 0)),
                "low_24h": float(http_ticker.get("lowPrice24h", 0)),
                "best_bid": float(http_ticker.get("bid1Price", 0)),
                "best_ask": float(http_ticker.get("ask1Price", 0)),
                "mark_price": float(http_ticker.get("markPrice", 0)),
                "index_price": float(http_ticker.get("indexPrice", 0)),
                "funding_rate": float(http_ticker.get("fundingRate", 0)),
                "open_interest": float(http_ticker.get("openInterest", 0)),
                "turnover_24h": float(http_ticker.get("turnover24h", 0))
            }
            
            # Вычисляем спред
            if summary["best_bid"] > 0 and summary["best_ask"] > 0:
                summary["spread"] = summary["best_ask"] - summary["best_bid"]
                summary["spread_percent"] = (summary["spread"] / summary["best_bid"]) * 100
            else:
                summary["spread"] = 0
                summary["spread_percent"] = 0
            
            # Сохраняем в ticker_data для совместимости
            self.ticker_data = {
                "symbol": summary["symbol"],
                "price": summary["current_price"],
                "change_24h": summary["change_24h_percent"],
                "volume_24h": summary["volume_24h"],
                "high_24h": summary["high_24h"],
                "low_24h": summary["low_24h"],
                "bid": summary["best_bid"],
                "ask": summary["best_ask"],
                "timestamp": datetime.now().isoformat()
            }
            
            self.logger.info(f"✅ HTTP ticker обработан: {summary['symbol']} @ ${summary['current_price']:.2f}")
            return summary
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки HTTP ticker: {e}")
            return {}
    
    def _get_technical_indicators_data(self) -> dict:
        """Получить данные технических индикаторов из стратегии"""
        try:
            if self.strategy and hasattr(self.strategy, 'current_indicators'):
                return self.strategy.current_indicators
            return {}
        except Exception as e:
            self.logger.error(f"Ошибка получения технических индикаторов: {e}")
            return {}
    
    # Сокращенные версии методов анализа (основные методы остаются те же)
    
    def _get_extended_klines_summary(self) -> dict:
        """Расширенная сводка по свечам"""
        if not self.extended_kline_data:
            return {}
        
        try:
            recent_klines = self.extended_kline_data[-20:]
            closes = [k["close"] for k in recent_klines]
            volumes = [k["volume"] for k in recent_klines]
            
            return {
                "total_klines": len(self.extended_kline_data),
                "analyzed_period": len(recent_klines),
                "price_statistics": {
                    "current_price": closes[-1] if closes else 0,
                    "avg_price": sum(closes) / len(closes) if closes else 0,
                    "price_volatility": self._calculate_volatility(closes)
                },
                "volume_statistics": {
                    "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
                    "volume_trend": self._determine_volume_trend(volumes)
                },
                "raw_klines": recent_klines[-10:]
            }
        except Exception as e:
            self.logger.error(f"Ошибка анализа свечей: {e}")
            return {}
    
    def _get_orderbook_analysis(self) -> dict:
        """Детальный анализ ордербука"""
        if not self.orderbook_data:
            return {}
        
        return {
            "current_orderbook": self.orderbook_data,
            "top_levels": {
                "bids": self.orderbook_data.get("bids", [])[:5],
                "asks": self.orderbook_data.get("asks", [])[:5]
            }
        }
    
    def _get_trading_activity_analysis(self) -> dict:
        """Анализ торговой активности"""
        if not self.trade_data:
            return {}
        
        try:
            recent_trades = self.trade_data[-50:]
            buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
            sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
            
            return {
                "total_trades": len(recent_trades),
                "buy_sell_ratio": {
                    "trades": len(buy_trades) / len(sell_trades) if sell_trades else 0,
                    "volume": sum(t["size"] for t in buy_trades) / sum(t["size"] for t in sell_trades) if sell_trades else 0
                },
                "recent_trades_sample": recent_trades[-5:]
            }
        except Exception as e:
            self.logger.error(f"Ошибка анализа торговой активности: {e}")
            return {}
    
    def _get_price_levels_analysis(self) -> dict:
        """Анализ уровней поддержки и сопротивления"""
        return {
            "support_levels": self.price_levels["support"][-5:],
            "resistance_levels": self.price_levels["resistance"][-5:]
        }
    
    def _get_volume_profile_analysis(self) -> dict:
        """Анализ профиля объема"""
        if not self.volume_profile:
            return {}
        
        sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
        
        return {
            "high_volume_nodes": [{"price": float(price), "volume": data["total_volume"]} for price, data in sorted_levels[:5]]
        }
    
    def _get_microstructure_analysis(self) -> dict:
        """Анализ микроструктуры рынка"""
        return {
            "liquidity_metrics": self._calculate_liquidity_metrics(),
            "order_flow_metrics": self._calculate_order_flow_metrics()
        }
    
    # Основные вспомогательные методы
    
    def _calculate_volatility(self, prices: List[float]) -> float:
        """Расчет волатильности"""
        if len(prices) < 2:
            return 0
        
        mean_price = sum(prices) / len(prices)
        variance = sum((price - mean_price) ** 2 for price in prices) / len(prices)
        return math.sqrt(variance) / mean_price * 100
    
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
    
    def _calculate_liquidity_metrics(self) -> dict:
        """Расчет метрик ликвидности"""
        if not self.orderbook_data:
            return {}
        
        spread = self.orderbook_data.get("spread", 0)
        best_bid = self.orderbook_data.get("best_bid", 0)
        total_bid_volume = self.orderbook_data.get("total_bid_volume", 0)
        total_ask_volume = self.orderbook_data.get("total_ask_volume", 0)
        
        return {
            "bid_ask_spread": spread,
            "spread_percentage": (spread / best_bid) * 100 if best_bid > 0 else 0,
            "total_liquidity": total_bid_volume + total_ask_volume
        }
    
    def _calculate_order_flow_metrics(self) -> dict:
        """Расчет метрик потока ордеров"""
        if not self.trade_data:
            return {}
        
        recent_trades = self.trade_data[-30:]
        buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
        sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
        
        buy_volume = sum(t["size"] for t in buy_trades)
        sell_volume = sum(t["size"] for t in sell_trades)
        
        return {
            "buy_sell_ratio": buy_volume / sell_volume if sell_volume > 0 else 0,
            "order_flow_imbalance": (buy_volume - sell_volume) / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0,
            "average_trade_size": sum(t["size"] for t in recent_trades) / len(recent_trades) if recent_trades else 0
        }
    
    def _assess_data_quality(self) -> dict:
        """Оценка качества данных"""
        return {
            "websocket_connected": self.is_connected,
            "data_freshness": time.time() - self.last_data_time,
            "klines_available": len(self.extended_kline_data),
            "orderbook_available": bool(self.orderbook_data),
            "trades_available": len(self.trade_data),
            "ticker_source": "HTTP REST API"
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
    
    def get_connection_status(self) -> dict:
        """Получить статус подключения"""
        return {
            "is_connected": self.is_connected,
            "websocket_active": self.websocket is not None and not self.websocket.closed if self.websocket else False,
            "last_data_time": self.last_data_time,
            "reconnect_count": self.reconnect_count,
            "message_counts": self.message_counts.copy()
        }
