"""
WebSocket менеджер для подключения к Bybit
Обработка потоков данных и управление соединением
Обновлено: детальное логирование для диагностики проблем с данными
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
                
            self.logger.info("WebSocket соединение закрыто")
            
        except Exception as e:
            self.logger.error(f"Ошибка закрытия WebSocket: {e}")
    
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
            
            # ИСПРАВЛЕНО: правильные топики для Bybit API v5
            subscriptions = [
                self.settings.get_ticker_subscription(),      # tickers.BTCUSDT
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
            self.logger.info("Запрос подписки отправлен")
            
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
        self.logger.info(f"  ticker_data: {bool(self.ticker_data)}")
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
                    self.message_counts["ticker"] += 1
                    await self._handle_ticker_data(data)
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
    
    async def _handle_ticker_data(self, data: dict):
        """Обработка ticker данных"""
        try:
            self.logger.debug("Обработка ticker данных...")
            ticker_info = data.get("data", {})
            
            if not ticker_info:
                self.logger.warning("Пустые ticker данные")
                return
            
            symbol = ticker_info.get("symbol")
            last_price = ticker_info.get("lastPrice")
            
            self.logger.info(f"Ticker получен: {symbol} = ${last_price}")
            
            self.ticker_data = {
                "symbol": symbol,
                "price": float(last_price) if last_price else 0,
                "change_24h": float(ticker_info.get("price24hPcnt", 0)) * 100,
                "volume_24h": float(ticker_info.get("volume24h", 0)),
                "high_24h": float(ticker_info.get("highPrice24h", 0)),
                "low_24h": float(ticker_info.get("lowPrice24h", 0)),
                "bid": float(ticker_info.get("bid1Price", 0)),
                "ask": float(ticker_info.get("ask1Price", 0)),
                "timestamp": datetime.now().isoformat()
            }
            
            self.logger.info(f"Ticker данные сохранены: цена ${self.ticker_data['price']}")
            
            # Обновляем стратегию
            if self.strategy:
                self.strategy.update_ticker(self.ticker_data)
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки ticker: {e}")
            self.logger.error(f"Ticker данные: {data}")
    
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
            
            # Концентрация ликвидности
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
        
        if not self.ticker_data:
            self.logger.warning("ticker_data пуст при запросе get_market_data")
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
        """Получить ВСЕ рыночные данные для ИИ-анализа"""
        if symbol and symbol != self.symbol:
            self.logger.warning(f"Запрошен символ {symbol}, но WebSocket подключен к {self.symbol}")
            return {}
        
        try:
            self.logger.info("Начинаем сбор comprehensive market data...")
            
            # Проверяем доступность данных
            if not self.ticker_data:
                self.logger.warning("ticker_data пуст")
            else:
                self.logger.info(f"ticker_data доступен: {self.ticker_data.get('symbol')} @ ${self.ticker_data.get('price')}")
            
            if not self.kline_data:
                self.logger.warning("kline_data пуст")
            else:
                self.logger.info(f"kline_data: {len(self.kline_data)} обычных свечей")
            
            if not self.extended_kline_data:
                self.logger.warning("extended_kline_data пуст")
            else:
                self.logger.info(f"extended_kline_data: {len(self.extended_kline_data)} расширенных свечей")
            
            comprehensive_data = {
                "basic_market": self._get_basic_market_summary(),
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
                    "collection_period": self._get_collection_period()
                }
            }
            
            self.logger.info(f"Comprehensive data собраны: {len(comprehensive_data)} секций")
            
            # Логируем что в каждой секции
            for section, data in comprehensive_data.items():
                if isinstance(data, dict):
                    self.logger.debug(f"  {section}: {len(data)} полей")
                else:
                    self.logger.debug(f"  {section}: {type(data)}")
            
            return comprehensive_data
            
        except Exception as e:
            self.logger.error(f"Ошибка сбора полных рыночных данных: {e}")
            return {}
    
    def _get_basic_market_summary(self) -> dict:
        """Основные рыночные данные"""
        if not self.ticker_data:
            self.logger.warning("ticker_data пуст в _get_basic_market_summary")
            return {}
        
        summary = {
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
        
        self.logger.debug(f"Basic market summary: price={summary['current_price']}")
        return summary
    
    def _get_extended_klines_summary(self) -> dict:
        """Расширенная сводка по свечам"""
        if not self.extended_kline_data:
            self.logger.warning("extended_kline_data пуст в _get_extended_klines_summary")
            return {}
        
        try:
            recent_klines = self.extended_kline_data[-50:]
            
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
                "raw_klines": recent_klines[-20:]
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа свечей: {e}")
            return {}
    
    def _get_orderbook_analysis(self) -> dict:
        """Детальный анализ ордербука"""
        if not self.orderbook_data:
            self.logger.warning("orderbook_data пуст в _get_orderbook_analysis")
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
            self.logger.error(f"Ошибка анализа ордербука: {e}")
            return {}
    
    def _get_trading_activity_analysis(self) -> dict:
        """Анализ торговой активности"""
        if not self.trade_data:
            self.logger.warning("trade_data пуст в _get_trading_activity_analysis")
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
                "recent_trades_sample": recent_trades[-10:]
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа торговой активности: {e}")
            return {}
    
    def _get_price_levels_analysis(self) -> dict:
        """Анализ уровней поддержки и сопротивления"""
        try:
            support_clusters = self._cluster_price_levels(self.price_levels["support"])
            resistance_clusters = self._cluster_price_levels(self.price_levels["resistance"])
            key_levels = self._identify_key_levels(support_clusters, resistance_clusters)
            
            return {
                "support_levels": support_clusters,
                "resistance_levels": resistance_clusters,
                "key_levels": key_levels,
                "current_price_context": self._analyze_current_price_context(key_levels),
                "level_strength": self._calculate_level_strength(support_clusters, resistance_clusters)
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа ценовых уровней: {e}")
            return {}
    
    def _get_volume_profile_analysis(self) -> dict:
        """Анализ профиля объема"""
        try:
            if not self.volume_profile:
                return {}
            
            sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
            vpoc = sorted_levels[0] if sorted_levels else None
            
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
            self.logger.error(f"Ошибка анализа профиля объема: {e}")
            return {}
    
    def _get_microstructure_analysis(self) -> dict:
        """Анализ микроструктуры рынка"""
        try:
            return {
                "liquidity_metrics": self._calculate_liquidity_metrics(),
                "order_flow_metrics": self._calculate_order_flow_metrics(),
                "price_discovery": self._analyze_price_discovery(),
                "market_efficiency": self._assess_market_efficiency(),
                "volatility_clustering": self._detect_volatility_clustering()
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа микроструктуры: {e}")
            return {}
    
    # Реальные методы для анализа (заменяем заглушки)
    
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
    
    def _calculate_orderbook_stability(self, history: List[dict]) -> float:
        """Расчет стабильности ордербука"""
        if len(history) < 2:
            return 0.5
        
        spreads = [h["spread"] for h in history]
        imbalances = [h["imbalance"] for h in history]
        
        spread_stability = 1 - (self._calculate_volatility(spreads) / 100)
        imbalance_stability = 1 - abs(sum(imbalances) / len(imbalances))
        
        return (spread_stability + imbalance_stability) / 2
    
    def _calculate_liquidity_score(self, orderbook: dict) -> float:
        """Расчет оценки ликвидности"""
        spread = orderbook.get("spread", 0)
        total_volume = orderbook.get("total_bid_volume", 0) + orderbook.get("total_ask_volume", 0)
        best_bid = orderbook.get("best_bid", 0)
        
        if best_bid == 0 or spread == 0:
            return 0.5
        
        spread_score = max(0, 1 - (spread / best_bid) * 1000)  # Нормализация спреда
        volume_score = min(1, total_volume / 1000000)  # Нормализация объема
        
        return (spread_score + volume_score) / 2
    
    def _calculate_order_flow_pressure(self, orderbook: dict) -> float:
        """Расчет давления потока ордеров"""
        return orderbook.get("order_imbalance", 0)
    
    def _calculate_price_impact(self, trades: List[dict]) -> float:
        """Расчет влияния на цену"""
        if len(trades) < 2:
            return 0
        
        prices = [t["price"] for t in trades]
        volumes = [t["size"] for t in trades]
        
        price_changes = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        volume_weights = [volumes[i] for i in range(1, len(volumes))]
        
        if not price_changes or not volume_weights:
            return 0
        
        weighted_impact = sum(pc * vw for pc, vw in zip(price_changes, volume_weights))
        total_volume = sum(volume_weights)
        
        return weighted_impact / total_volume if total_volume > 0 else 0
    
    def _analyze_trading_time_patterns(self, trades: List[dict]) -> dict:
        """Анализ временных паттернов торговли"""
        if not trades:
            return {}
        
        # Группируем по минутам
        minute_volumes = {}
        for trade in trades:
            minute = trade["datetime"].replace(second=0, microsecond=0)
            minute_key = minute.strftime("%H:%M")
            
            if minute_key not in minute_volumes:
                minute_volumes[minute_key] = {"volume": 0, "count": 0, "value": 0}
            
            minute_volumes[minute_key]["volume"] += trade["size"]
            minute_volumes[minute_key]["count"] += 1
            minute_volumes[minute_key]["value"] += trade.get("value", 0)
        
        # Находим пики активности
        sorted_minutes = sorted(minute_volumes.items(), key=lambda x: x[1]["volume"], reverse=True)
        peak_minutes = sorted_minutes[:5]
        
        return {
            "total_minutes": len(minute_volumes),
            "peak_activity": [{"time": m[0], "volume": m[1]["volume"], "trades": m[1]["count"]} for m in peak_minutes],
            "avg_volume_per_minute": sum(m["volume"] for m in minute_volumes.values()) / len(minute_volumes),
            "avg_trades_per_minute": sum(m["count"] for m in minute_volumes.values()) / len(minute_volumes)
        }
    
    def _cluster_price_levels(self, levels: List[dict]) -> List[dict]:
        """Кластеризация ценовых уровней"""
        if not levels:
            return []
        
        # Группируем близкие цены
        clusters = []
        sorted_levels = sorted(levels, key=lambda x: x["price"])
        
        current_cluster = [sorted_levels[0]]
        cluster_threshold = sorted_levels[0]["price"] * 0.001  # 0.1% разница
        
        for level in sorted_levels[1:]:
            if abs(level["price"] - current_cluster[-1]["price"]) <= cluster_threshold:
                current_cluster.append(level)
            else:
                # Завершаем текущий кластер
                avg_price = sum(l["price"] for l in current_cluster) / len(current_cluster)
                total_strength = sum(l["strength"] for l in current_cluster)
                
                clusters.append({
                    "price": avg_price,
                    "strength": total_strength,
                    "touches": len(current_cluster),
                    "first_touch": min(l["timestamp"] for l in current_cluster),
                    "last_touch": max(l["timestamp"] for l in current_cluster)
                })
                
                current_cluster = [level]
        
        # Добавляем последний кластер
        if current_cluster:
            avg_price = sum(l["price"] for l in current_cluster) / len(current_cluster)
            total_strength = sum(l["strength"] for l in current_cluster)
            
            clusters.append({
                "price": avg_price,
                "strength": total_strength,
                "touches": len(current_cluster),
                "first_touch": min(l["timestamp"] for l in current_cluster),
                "last_touch": max(l["timestamp"] for l in current_cluster)
            })
        
        return sorted(clusters, key=lambda x: x["strength"], reverse=True)[:10]
    
    def _identify_key_levels(self, support: List[dict], resistance: List[dict]) -> dict:
        """Идентификация ключевых уровней"""
        all_levels = []
        
        for s in support:
            all_levels.append({**s, "type": "support"})
        
        for r in resistance:
            all_levels.append({**r, "type": "resistance"})
        
        # Сортируем по силе
        key_levels = sorted(all_levels, key=lambda x: x["strength"], reverse=True)[:5]
        
        return {
            "strongest_levels": key_levels,
            "nearest_support": min([s for s in support if s["price"] < self.ticker_data.get("price", 0)], 
                                 key=lambda x: abs(x["price"] - self.ticker_data.get("price", 0)), default=None),
            "nearest_resistance": min([r for r in resistance if r["price"] > self.ticker_data.get("price", 0)], 
                                    key=lambda x: abs(x["price"] - self.ticker_data.get("price", 0)), default=None)
        }
    
    def _analyze_current_price_context(self, key_levels: dict) -> dict:
        """Анализ контекста текущей цены"""
        current_price = self.ticker_data.get("price", 0)
        
        if not current_price:
            return {}
        
        nearest_support = key_levels.get("nearest_support")
        nearest_resistance = key_levels.get("nearest_resistance")
        
        context = {
            "current_price": current_price,
            "price_position": "middle"
        }
        
        if nearest_support:
            support_distance = current_price - nearest_support["price"]
            context["support_distance"] = support_distance
            context["support_distance_percent"] = (support_distance / current_price) * 100
        
        if nearest_resistance:
            resistance_distance = nearest_resistance["price"] - current_price
            context["resistance_distance"] = resistance_distance
            context["resistance_distance_percent"] = (resistance_distance / current_price) * 100
        
        # Определяем позицию цены
        if nearest_support and nearest_resistance:
            total_range = nearest_resistance["price"] - nearest_support["price"]
            price_in_range = (current_price - nearest_support["price"]) / total_range
            
            if price_in_range < 0.3:
                context["price_position"] = "near_support"
            elif price_in_range > 0.7:
                context["price_position"] = "near_resistance"
            else:
                context["price_position"] = "middle_range"
        
        return context
    
    def _calculate_level_strength(self, support: List[dict], resistance: List[dict]) -> dict:
        """Расчет силы уровней"""
        support_strength = sum(s["strength"] for s in support) / len(support) if support else 0
        resistance_strength = sum(r["strength"] for r in resistance) / len(resistance) if resistance else 0
        
        return {
            "support_strength": support_strength,
            "resistance_strength": resistance_strength,
            "support_count": len(support),
            "resistance_count": len(resistance),
            "level_balance": "support_stronger" if support_strength > resistance_strength else "resistance_stronger" if resistance_strength > support_strength else "balanced"
        }
    
    def _analyze_volume_distribution(self) -> dict:
        """Анализ распределения объема"""
        if not self.volume_profile:
            return {}
        
        total_volume = sum(data["total_volume"] for data in self.volume_profile.values())
        avg_volume = total_volume / len(self.volume_profile)
        
        distribution = {
            "total_volume": total_volume,
            "average_volume_per_level": avg_volume,
            "price_levels_count": len(self.volume_profile),
            "volume_concentration": {}
        }
        
        # Анализ концентрации объема
        sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
        
        top_10_percent_count = max(1, len(sorted_levels) // 10)
        top_10_percent_volume = sum(data["total_volume"] for _, data in sorted_levels[:top_10_percent_count])
        
        distribution["volume_concentration"] = {
            "top_10_percent_levels_volume": top_10_percent_volume,
            "top_10_percent_concentration": (top_10_percent_volume / total_volume) * 100,
            "distribution_type": "concentrated" if (top_10_percent_volume / total_volume) > 0.5 else "distributed"
        }
        
        return distribution
    
    def _analyze_price_acceptance(self) -> dict:
        """Анализ принятия цены"""
        if not self.volume_profile or not self.extended_kline_data:
            return {}
        
        current_price = self.ticker_data.get("price", 0)
        
        # Находим ценовые уровни с высоким объемом
        sorted_levels = sorted(self.volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
        high_volume_levels = [float(price) for price, _ in sorted_levels[:5]]
        
        # Анализируем, как долго цена держалась на каждом уровне
        acceptance_levels = []
        
        for level_price in high_volume_levels:
            time_at_level = 0
            volume_at_level = 0
            
            for kline in self.extended_kline_data[-20:]:
                if abs(kline["close"] - level_price) <= level_price * 0.005:  # 0.5% толерантность
                    time_at_level += 1
                    volume_at_level += kline["volume"]
            
            if time_at_level > 0:
                acceptance_levels.append({
                    "price": level_price,
                    "time_periods": time_at_level,
                    "volume": volume_at_level,
                    "acceptance_score": time_at_level * volume_at_level
                })
        
        # Сортируем по принятию
        acceptance_levels.sort(key=lambda x: x["acceptance_score"], reverse=True)
        
        return {
            "high_acceptance_levels": acceptance_levels[:3],
            "current_price_acceptance": self._calculate_current_price_acceptance(current_price),
            "price_rejection_zones": self._identify_rejection_zones()
        }
    
    def _calculate_current_price_acceptance(self, current_price: float) -> dict:
        """Расчет принятия текущей цены"""
        if not current_price:
            return {}
        
        # Ищем объем на текущем ценовом уровне
        price_level = round(current_price, 2)
        volume_data = self.volume_profile.get(price_level, {"total_volume": 0})
        
        # Анализируем недавнюю активность на этом уровне
        recent_klines = self.extended_kline_data[-10:]
        time_at_current = sum(1 for k in recent_klines if abs(k["close"] - current_price) <= current_price * 0.003)
        
        return {
            "volume_at_level": volume_data["total_volume"],
            "time_at_level": time_at_current,
            "acceptance_strength": "high" if time_at_current >= 3 and volume_data["total_volume"] > 0 else "low"
        }
    
    def _identify_rejection_zones(self) -> List[dict]:
        """Идентификация зон отторжения цены"""
        rejection_zones = []
        
        if len(self.extended_kline_data) < 5:
            return rejection_zones
        
        for i in range(len(self.extended_kline_data) - 4):
            klines_window = self.extended_kline_data[i:i+5]
            
            # Ищем паттерны отторжения (быстрое движение от уровня)
            for kline in klines_window:
                upper_shadow_ratio = kline.get("upper_shadow", 0) / kline.get("range", 1)
                lower_shadow_ratio = kline.get("lower_shadow", 0) / kline.get("range", 1)
                
                if upper_shadow_ratio > 0.6:  # Большая верхняя тень = отторжение сверху
                    rejection_zones.append({
                        "price": kline["high"],
                        "type": "resistance_rejection",
                        "strength": upper_shadow_ratio,
                        "timestamp": kline["timestamp"]
                    })
                
                if lower_shadow_ratio > 0.6:  # Большая нижняя тень = отторжение снизу
                    rejection_zones.append({
                        "price": kline["low"],
                        "type": "support_rejection", 
                        "strength": lower_shadow_ratio,
                        "timestamp": kline["timestamp"]
                    })
        
        return sorted(rejection_zones, key=lambda x: x["strength"], reverse=True)[:5]
    
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
            "total_liquidity": total_bid_volume + total_ask_volume,
            "liquidity_asymmetry": abs(total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume) if (total_bid_volume + total_ask_volume) > 0 else 0,
            "effective_spread": self._calculate_effective_spread(),
            "market_impact": self._calculate_market_impact_cost(),
            "liquidity_score": self._calculate_liquidity_score(self.orderbook_data)
        }
    
    def _calculate_effective_spread(self) -> float:
        """Расчет эффективного спреда"""
        if not self.trade_data:
            return 0
        
        recent_trades = self.trade_data[-10:]
        if len(recent_trades) < 2:
            return 0
        
        # Простое приближение эффективного спреда
        prices = [t["price"] for t in recent_trades]
        price_volatility = self._calculate_volatility(prices)
        
        return price_volatility * 0.1  # Упрощенная формула
    
    def _calculate_market_impact_cost(self) -> float:
        """Расчет стоимости рыночного воздействия"""
        if not self.orderbook_data:
            return 0
        
        bids = self.orderbook_data.get("bids", [])
        asks = self.orderbook_data.get("asks", [])
        
        if not bids or not asks:
            return 0
        
        # Симулируем крупную сделку и рассчитываем воздействие
        trade_size = 1000  # Условный размер сделки
        current_size = 0
        levels_consumed = 0
        
        for bid in bids:
            current_size += bid[1]
            levels_consumed += 1
            if current_size >= trade_size:
                break
        
        return levels_consumed / len(bids) if bids else 0
    
    def _calculate_order_flow_metrics(self) -> dict:
        """Расчет метрик потока ордеров"""
        if not self.trade_data:
            return {}
        
        recent_trades = self.trade_data[-50:]
        
        buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
        sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
        
        buy_volume = sum(t["size"] for t in buy_trades)
        sell_volume = sum(t["size"] for t in sell_trades)
        
        return {
            "buy_sell_ratio": buy_volume / sell_volume if sell_volume > 0 else 0,
            "order_flow_imbalance": (buy_volume - sell_volume) / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0,
            "aggressive_trades_ratio": len([t for t in recent_trades if t.get("is_large", False)]) / len(recent_trades),
            "average_trade_size": sum(t["size"] for t in recent_trades) / len(recent_trades),
            "trade_frequency": len(recent_trades) / 10,  # trades per 10 periods
            "volume_weighted_price": sum(t["price"] * t["size"] for t in recent_trades) / sum(t["size"] for t in recent_trades) if recent_trades else 0
        }
    
    def _analyze_price_discovery(self) -> dict:
        """Анализ ценообразования"""
        if not self.extended_kline_data or not self.trade_data:
            return {}
        
        recent_klines = self.extended_kline_data[-10:]
        recent_trades = self.trade_data[-50:]
        
        # Анализ эффективности ценообразования
        kline_prices = [k["close"] for k in recent_klines]
        trade_prices = [t["price"] for t in recent_trades]
        
        price_convergence = self._calculate_price_convergence(kline_prices, trade_prices)
        information_efficiency = self._calculate_information_efficiency(recent_klines)
        
        return {
            "price_convergence": price_convergence,
            "information_efficiency": information_efficiency,
            "price_leadership": self._determine_price_leadership(),
            "arbitrage_opportunities": self._detect_arbitrage_opportunities(),
            "price_stability": self._assess_price_stability(kline_prices)
        }
    
    def _calculate_price_convergence(self, kline_prices: List[float], trade_prices: List[float]) -> float:
        """Расчет сходимости цен"""
        if not kline_prices or not trade_prices:
            return 0
        
        avg_kline_price = sum(kline_prices) / len(kline_prices)
        avg_trade_price = sum(trade_prices) / len(trade_prices)
        
        convergence = 1 - abs(avg_kline_price - avg_trade_price) / avg_kline_price
        return max(0, convergence)
    
    def _calculate_information_efficiency(self, klines: List[dict]) -> float:
        """Расчет информационной эффективности"""
        if len(klines) < 3:
            return 0.5
        
        # Анализ того, как быстро цена реагирует на новую информацию
        price_changes = [abs(klines[i]["close"] - klines[i-1]["close"]) for i in range(1, len(klines))]
        volume_changes = [klines[i]["volume"] / klines[i-1]["volume"] if klines[i-1]["volume"] > 0 else 1 for i in range(1, len(klines))]
        
        # Корреляция изменений цены и объема как мера эффективности
        correlation = self._calculate_volume_price_correlation(price_changes, volume_changes)
        
        return abs(correlation)
    
    def _determine_price_leadership(self) -> str:
        """Определение лидерства в ценообразовании"""
        if not self.trade_data or not self.extended_kline_data:
            return "unknown"
        
        recent_trades = self.trade_data[-20:]
        large_trades = [t for t in recent_trades if t.get("is_large", False)]
        
        if not large_trades:
            return "distributed"
        
        # Анализ воздействия крупных сделок на цену
        price_impact_count = 0
        for trade in large_trades:
            # Ищем изменение цены после крупной сделки
            trade_time = trade["timestamp"]
            subsequent_klines = [k for k in self.extended_kline_data if k["timestamp"] > trade_time]
            
            if subsequent_klines:
                price_change = abs(subsequent_klines[0]["close"] - trade["price"]) / trade["price"]
                if price_change > 0.001:  # 0.1% изменение
                    price_impact_count += 1
        
        impact_ratio = price_impact_count / len(large_trades)
        
        if impact_ratio > 0.7:
            return "institutional_led"
        elif impact_ratio > 0.3:
            return "mixed"
        else:
            return "retail_led"
    
    def _detect_arbitrage_opportunities(self) -> List[dict]:
        """Детектирование арбитражных возможностей"""
        opportunities = []
        
        if not self.orderbook_data or not self.ticker_data:
            return opportunities
        
        best_bid = self.orderbook_data.get("best_bid", 0)
        best_ask = self.orderbook_data.get("best_ask", 0)
        current_price = self.ticker_data.get("price", 0)
        
        # Простые арбитражные сигналы
        spread_percentage = ((best_ask - best_bid) / best_bid) * 100 if best_bid > 0 else 0
        
        if spread_percentage > 0.1:  # Спред больше 0.1%
            opportunities.append({
                "type": "wide_spread",
                "opportunity": spread_percentage,
                "description": f"Wide bid-ask spread: {spread_percentage:.3f}%"
            })
        
        # Анализ отклонений от справедливой цены
        if self.extended_kline_data:
            recent_vwap = sum(k.get("vwap_estimate", 0) for k in self.extended_kline_data[-5:]) / 5
            vwap_deviation = abs(current_price - recent_vwap) / recent_vwap * 100
            
            if vwap_deviation > 0.5:
                opportunities.append({
                    "type": "vwap_deviation",
                    "opportunity": vwap_deviation,
                    "description": f"Price deviation from VWAP: {vwap_deviation:.3f}%"
                })
        
        return opportunities
    
    def _assess_price_stability(self, prices: List[float]) -> dict:
        """Оценка стабильности цены"""
        if len(prices) < 2:
            return {"stability": "unknown"}
        
        volatility = self._calculate_volatility(prices)
        price_range = (max(prices) - min(prices)) / sum(prices) * len(prices) * 100
        
        stability_score = max(0, 1 - volatility / 10)  # Нормализация
        
        if stability_score > 0.8:
            stability_level = "very_stable"
        elif stability_score > 0.6:
            stability_level = "stable"
        elif stability_score > 0.4:
            stability_level = "moderate"
        elif stability_score > 0.2:
            stability_level = "volatile"
        else:
            stability_level = "very_volatile"
        
        return {
            "stability": stability_level,
            "stability_score": stability_score,
            "volatility": volatility,
            "price_range_percent": price_range
        }
    
    def _assess_market_efficiency(self) -> dict:
        """Оценка рыночной эффективности"""
        efficiency_metrics = {
            "information_efficiency": 0.5,
            "pricing_efficiency": 0.5,
            "operational_efficiency": 0.5,
            "overall_efficiency": 0.5
        }
        
        # Информационная эффективность
        if self.extended_kline_data:
            efficiency_metrics["information_efficiency"] = self._calculate_information_efficiency(self.extended_kline_data[-10:])
        
        # Ценовая эффективность (на основе спреда и волатильности)
        if self.orderbook_data:
            spread_efficiency = 1 - min(1, self.orderbook_data.get("spread_percent", 100) / 100)
            efficiency_metrics["pricing_efficiency"] = spread_efficiency
        
        # Операционная эффективность (на основе объемов и ликвидности)
        if self.trade_data and self.orderbook_data:
            liquidity_score = self._calculate_liquidity_score(self.orderbook_data)
            trade_frequency = len(self.trade_data[-50:]) / 50
            efficiency_metrics["operational_efficiency"] = (liquidity_score + min(1, trade_frequency)) / 2
        
        # Общая эффективность
        efficiency_metrics["overall_efficiency"] = sum(efficiency_metrics.values()) / len(efficiency_metrics)
        
        return efficiency_metrics
    
    def _detect_volatility_clustering(self) -> dict:
        """Детектирование кластеризации волатильности"""
        if not self.extended_kline_data or len(self.extended_kline_data) < 10:
            return {"clustering_detected": False}
        
        # Рассчитываем волатильность для скользящих окон
        window_size = 5
        volatilities = []
        
        for i in range(len(self.extended_kline_data) - window_size + 1):
            window = self.extended_kline_data[i:i + window_size]
            prices = [k["close"] for k in window]
            vol = self._calculate_volatility(prices)
            volatilities.append(vol)
        
        if len(volatilities) < 3:
            return {"clustering_detected": False}
        
        # Анализ кластеризации
        high_vol_threshold = sum(volatilities) / len(volatilities) * 1.5
        high_vol_periods = [i for i, vol in enumerate(volatilities) if vol > high_vol_threshold]
        
        # Проверяем, идут ли периоды высокой волатильности подряд
        clustering_score = 0
        consecutive_count = 0
        
        for i in range(1, len(high_vol_periods)):
            if high_vol_periods[i] - high_vol_periods[i-1] == 1:
                consecutive_count += 1
            else:
                if consecutive_count > 0:
                    clustering_score += consecutive_count
                consecutive_count = 0
        
        if consecutive_count > 0:
            clustering_score += consecutive_count
        
        clustering_detected = clustering_score > 0
        
        return {
            "clustering_detected": clustering_detected,
            "clustering_score": clustering_score,
            "high_volatility_periods": len(high_vol_periods),
            "average_volatility": sum(volatilities) / len(volatilities),
            "max_volatility": max(volatilities),
            "volatility_trend": self._determine_volume_trend(volatilities)
        }
    
    def _assess_data_quality(self) -> dict:
        """Оценка качества данных"""
        return {
            "websocket_connected": self.is_connected,
            "data_freshness": time.time() - self.last_data_time,
            "klines_available": len(self.extended_kline_data),
            "orderbook_available": bool(self.orderbook_data),
            "trades_available": len(self.trade_data),
            "price_levels_identified": len(self.price_levels["support"]) + len(self.price_levels["resistance"]),
            "volume_profile_depth": len(self.volume_profile),
            "message_statistics": self.message_counts.copy()
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
        """Получить статус соединения"""
        return {
            "is_connected": self.is_connected,
            "reconnect_count": self.reconnect_count,
            "last_ping": self.last_ping,
            "last_data_time": self.last_data_time,
            "data_delay": time.time() - self.last_data_time if self.last_data_time else 0,
            "websocket_url": self.settings.websocket_url,
            "subscribed_symbol": self.symbol,
            "message_counts": self.message_counts.copy(),
            "extended_data_available": {
                "klines": len(self.extended_kline_data),
                "orderbook_history": len(self.extended_orderbook_history),
                "volume_profile": len(self.volume_profile),
                "price_levels": len(self.price_levels["support"]) + len(self.price_levels["resistance"])
            }
        }
