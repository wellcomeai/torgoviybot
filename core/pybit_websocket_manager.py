"""
Упрощенный WebSocket менеджер на основе pybit
Заменяет сложный core/websocket_manager.py
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
import json

from pybit.unified_trading import WebSocket as PybitWebSocket, HTTP as PybitHTTP
from config.settings import get_settings


class PybitWebSocketManager:
    """Упрощенный WebSocket менеджер на основе pybit"""
    
    def __init__(self, symbol: str, strategy, on_signal_callback: Optional[Callable] = None):
        self.settings = get_settings()
        self.symbol = symbol
        self.strategy = strategy
        self.on_signal_callback = on_signal_callback
        
        # HTTP клиент pybit для REST запросов
        self.http_client = PybitHTTP(testnet=self.settings.BYBIT_WS_TESTNET)
        
        # WebSocket клиент pybit
        self.ws = None
        
        # Хранение данных (упрощенное)
        self.market_data = {
            "ticker": {},
            "klines": [],
            "orderbook": {},
            "trades": []
        }
        
        self.is_connected = False
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"🚀 PybitWebSocketManager инициализирован для {symbol}")
    
    async def start(self):
        """Запуск WebSocket соединений через pybit"""
        try:
            self.logger.info("Запуск pybit WebSocket соединений...")
            
            # Создаем WebSocket для публичных данных (linear)
            self.ws = PybitWebSocket(
                testnet=self.settings.BYBIT_WS_TESTNET,
                channel_type="linear"
            )
            
            # Подписываемся на потоки данных
            await self._subscribe_to_streams()
            
            self.is_connected = True
            self.logger.info("✅ PybitWebSocket успешно подключен")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка запуска PybitWebSocket: {e}")
            raise
    
    async def _subscribe_to_streams(self):
        """Подписка на потоки данных через pybit"""
        
        # 1. Подписка на kline (свечи)
        self.ws.kline_stream(
            interval=5,  # 5 минут
            symbol=self.symbol,
            callback=self._handle_kline
        )
        self.logger.info(f"✅ Подписка на kline {self.symbol}")
        
        # 2. Подписка на ticker
        self.ws.ticker_stream(
            symbol=self.symbol,
            callback=self._handle_ticker
        )
        self.logger.info(f"✅ Подписка на ticker {self.symbol}")
        
        # 3. Подписка на orderbook
        self.ws.orderbook_stream(
            depth=50,
            symbol=self.symbol,
            callback=self._handle_orderbook
        )
        self.logger.info(f"✅ Подписка на orderbook {self.symbol}")
        
        # 4. Подписка на торги
        self.ws.trade_stream(
            symbol=self.symbol,
            callback=self._handle_trades
        )
        self.logger.info(f"✅ Подписка на trades {self.symbol}")
    
    def _handle_kline(self, message):
        """Обработка kline данных от pybit"""
        try:
            # pybit уже обработал данные!
            if message.get('type') == 'snapshot' and message.get('data'):
                kline_data = message['data']
                
                # Преобразуем в формат для стратегии
                processed_kline = {
                    "timestamp": kline_data.get('start', 0),
                    "datetime": datetime.fromtimestamp(int(kline_data.get('start', 0)) / 1000),
                    "open": float(kline_data.get('open', 0)),
                    "high": float(kline_data.get('high', 0)),
                    "low": float(kline_data.get('low', 0)),
                    "close": float(kline_data.get('close', 0)),
                    "volume": float(kline_data.get('volume', 0)),
                    "confirm": kline_data.get('confirm', False)
                }
                
                # Сохраняем данные
                self.market_data["klines"].append(processed_kline)
                if len(self.market_data["klines"]) > 100:
                    self.market_data["klines"] = self.market_data["klines"][-100:]
                
                # Передаем в стратегию
                if self.strategy:
                    asyncio.create_task(self._process_strategy_signal(processed_kline))
                
                self.logger.debug(f"📊 Kline обработан: {processed_kline['close']}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки kline: {e}")
    
    def _handle_ticker(self, message):
        """Обработка ticker данных от pybit"""
        try:
            if message.get('type') == 'snapshot' and message.get('data'):
                ticker_data = message['data']
                
                # Сохраняем ticker данные
                self.market_data["ticker"] = {
                    "symbol": ticker_data.get('symbol'),
                    "price": float(ticker_data.get('lastPrice', 0)),
                    "change_24h": float(ticker_data.get('price24hPcnt', 0)) * 100,
                    "volume_24h": float(ticker_data.get('volume24h', 0)),
                    "high_24h": float(ticker_data.get('highPrice24h', 0)),
                    "low_24h": float(ticker_data.get('lowPrice24h', 0)),
                    "timestamp": datetime.now().isoformat()
                }
                
                self.logger.debug(f"💰 Ticker обновлен: ${ticker_data.get('lastPrice')}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки ticker: {e}")
    
    def _handle_orderbook(self, message):
        """Обработка orderbook данных от pybit"""
        try:
            if message.get('type') == 'snapshot' and message.get('data'):
                orderbook_data = message['data']
                
                self.market_data["orderbook"] = {
                    "bids": [[float(bid[0]), float(bid[1])] for bid in orderbook_data.get('b', [])[:10]],
                    "asks": [[float(ask[0]), float(ask[1])] for ask in orderbook_data.get('a', [])[:10]],
                    "timestamp": datetime.now().isoformat()
                }
                
                # Вычисляем спред
                if self.market_data["orderbook"]["bids"] and self.market_data["orderbook"]["asks"]:
                    best_bid = self.market_data["orderbook"]["bids"][0][0]
                    best_ask = self.market_data["orderbook"]["asks"][0][0]
                    self.market_data["orderbook"]["spread"] = best_ask - best_bid
                
                self.logger.debug(f"📚 Orderbook обновлен")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки orderbook: {e}")
    
    def _handle_trades(self, message):
        """Обработка trade данных от pybit"""
        try:
            if message.get('data'):
                for trade_data in message['data']:
                    trade = {
                        "timestamp": trade_data.get('T', 0),
                        "price": float(trade_data.get('p', 0)),
                        "size": float(trade_data.get('v', 0)),
                        "side": trade_data.get('S', ''),
                        "datetime": datetime.fromtimestamp(int(trade_data.get('T', 0)) / 1000)
                    }
                    
                    self.market_data["trades"].append(trade)
                    
                    # Ограничиваем размер
                    if len(self.market_data["trades"]) > 1000:
                        self.market_data["trades"] = self.market_data["trades"][-1000:]
                
                self.logger.debug(f"💹 Trades обновлены: +{len(message['data'])}")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки trades: {e}")
    
    async def _process_strategy_signal(self, kline_data):
        """Обработка сигнала от стратегии"""
        try:
            signal = await self.strategy.analyze_kline(kline_data)
            if signal and self.on_signal_callback:
                await self.on_signal_callback(signal)
        except Exception as e:
            self.logger.error(f"❌ Ошибка обработки сигнала стратегии: {e}")
    
    def get_market_data(self, symbol: str = None) -> dict:
        """Получить рыночные данные (совместимость со старым API)"""
        if symbol and symbol != self.symbol:
            return {}
        
        ticker = self.market_data["ticker"]
        if not ticker:
            return {}
        
        return {
            "symbol": ticker.get("symbol", self.symbol),
            "price": f"{ticker.get('price', 0):.4f}",
            "change_24h": f"{ticker.get('change_24h', 0):+.2f}%",
            "volume_24h": f"{ticker.get('volume_24h', 0):,.0f}",
            "high_24h": f"{ticker.get('high_24h', 0):.4f}",
            "low_24h": f"{ticker.get('low_24h', 0):.4f}",
            "timestamp": ticker.get("timestamp"),
            "data_source": "pybit"
        }
    
    async def get_comprehensive_market_data(self, symbol: str = None) -> dict:
        """Получить полные рыночные данные для ИИ-анализа"""
        if symbol and symbol != self.symbol:
            return {}
        
        try:
            # Получаем свежие данные через HTTP API pybit
            fresh_ticker = self.http_client.get_tickers(category="linear", symbol=self.symbol)
            fresh_klines = self.http_client.get_kline(
                category="linear", 
                symbol=self.symbol, 
                interval="5", 
                limit=50
            )
            
            # Формируем comprehensive данные
            comprehensive_data = {
                "basic_market": self._format_basic_market_data(fresh_ticker),
                "technical_indicators": self._get_technical_indicators(),
                "recent_klines": self._format_recent_klines(fresh_klines),
                "orderbook": self.market_data["orderbook"],
                "recent_trades": self._format_recent_trades(),
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": symbol or self.symbol,
                    "data_source": "pybit",
                    "websocket_connected": self.is_connected
                }
            }
            
            return comprehensive_data
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения comprehensive данных: {e}")
            return {}
    
    def _format_basic_market_data(self, ticker_response):
        """Форматирование базовых рыночных данных"""
        if not ticker_response or ticker_response.get("retCode") != 0:
            return self.market_data["ticker"]
        
        ticker_list = ticker_response.get("result", {}).get("list", [])
        if not ticker_list:
            return self.market_data["ticker"]
        
        ticker = ticker_list[0]
        return {
            "symbol": ticker.get("symbol"),
            "price": float(ticker.get("lastPrice", 0)),
            "change_24h": float(ticker.get("price24hPcnt", 0)) * 100,
            "volume_24h": float(ticker.get("volume24h", 0)),
            "high_24h": float(ticker.get("highPrice24h", 0)),
            "low_24h": float(ticker.get("lowPrice24h", 0))
        }
    
    def _get_technical_indicators(self):
        """Получить технические индикаторы от стратегии"""
        if self.strategy and hasattr(self.strategy, 'current_indicators'):
            return self.strategy.current_indicators
        return {}
    
    def _format_recent_klines(self, klines_response):
        """Форматирование данных свечей"""
        if not klines_response or klines_response.get("retCode") != 0:
            return self.market_data["klines"][-20:]
        
        klines_list = klines_response.get("result", {}).get("list", [])
        formatted_klines = []
        
        for kline in klines_list:
            formatted_klines.append({
                "timestamp": int(kline[0]),
                "open": float(kline[1]),
                "high": float(kline[2]),
                "low": float(kline[3]),
                "close": float(kline[4]),
                "volume": float(kline[5])
            })
        
        return formatted_klines
    
    def _format_recent_trades(self):
        """Форматирование последних сделок"""
        recent_trades = self.market_data["trades"][-100:]
        
        if not recent_trades:
            return {"total_trades": 0, "buy_trades": 0, "sell_trades": 0}
        
        buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
        sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
        
        return {
            "total_trades": len(recent_trades),
            "buy_trades": len(buy_trades),
            "sell_trades": len(sell_trades),
            "latest_trades": recent_trades[-10:]
        }
    
    async def stop(self):
        """Остановка WebSocket соединения"""
        try:
            self.is_connected = False
            # pybit автоматически управляет соединениями
            self.logger.info("✅ PybitWebSocket остановлен")
        except Exception as e:
            self.logger.error(f"❌ Ошибка остановки PybitWebSocket: {e}")
    
    def get_connection_status(self) -> dict:
        """Получить статус подключения"""
        return {
            "is_connected": self.is_connected,
            "websocket_active": self.ws is not None,
            "data_available": bool(self.market_data["ticker"]),
            "klines_count": len(self.market_data["klines"]),
            "trades_count": len(self.market_data["trades"])
        }
