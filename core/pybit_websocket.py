"""
Чистый WebSocket менеджер на основе pybit
ТОЛЬКО получение данных, БЕЗ бизнес-логики
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

from pybit.unified_trading import WebSocket as PybitWebSocket, HTTP as PybitHTTP
from config.settings import get_settings


class PybitWebSocket:
    """Чистый WebSocket клиент - только получение данных"""
    
    def __init__(self, symbol: str):
        self.settings = get_settings()
        self.symbol = symbol
        
        # HTTP клиент для REST запросов
        self.http_client = PybitHTTP(testnet=self.settings.BYBIT_WS_TESTNET)
        
        # WebSocket клиент pybit
        self.ws = None
        self.is_connected = False
        
        # Callback функции для передачи данных
        self.on_kline = None
        self.on_ticker = None
        self.on_orderbook = None
        self.on_trades = None
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"PybitWebSocket инициализирован для {symbol}")
    
    def set_callbacks(self, 
                     on_kline: Optional[Callable] = None,
                     on_ticker: Optional[Callable] = None, 
                     on_orderbook: Optional[Callable] = None,
                     on_trades: Optional[Callable] = None):
        """Установка callback функций для обработки данных"""
        self.on_kline = on_kline
        self.on_ticker = on_ticker
        self.on_orderbook = on_orderbook
        self.on_trades = on_trades
    
    async def connect(self):
        """Подключение к WebSocket"""
        try:
            self.logger.info("Подключение к pybit WebSocket...")
            
            # Создаем WebSocket для публичных данных
            self.ws = PybitWebSocket(
                testnet=self.settings.BYBIT_WS_TESTNET,
                channel_type="linear"
            )
            
            # Подписываемся на потоки данных
            self._subscribe_to_streams()
            
            self.is_connected = True
            self.logger.info("WebSocket успешно подключен")
            
        except Exception as e:
            self.logger.error(f"Ошибка подключения WebSocket: {e}")
            raise
    
    def _subscribe_to_streams(self):
        """Подписка на потоки данных"""
        
        # Подписка на kline (свечи)
        self.ws.kline_stream(
            interval=5,  # 5 минут
            symbol=self.symbol,
            callback=self._handle_kline_raw
        )
        
        # Подписка на ticker
        self.ws.ticker_stream(
            symbol=self.symbol,
            callback=self._handle_ticker_raw
        )
        
        # Подписка на orderbook
        self.ws.orderbook_stream(
            depth=50,
            symbol=self.symbol,
            callback=self._handle_orderbook_raw
        )
        
        # Подписка на торги
        self.ws.trade_stream(
            symbol=self.symbol,
            callback=self._handle_trades_raw
        )
        
        self.logger.info(f"Подписки активированы для {self.symbol}")
    
    def _handle_kline_raw(self, message):
        """Обработка сырых kline данных"""
        try:
            # Извлекаем данные из pybit сообщения
            kline_data = self._extract_kline_data(message)
            if kline_data and self.on_kline:
                # Передаем ТОЛЬКО обработанные данные
                self.on_kline(kline_data)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки kline: {e}")
    
    def _handle_ticker_raw(self, message):
        """Обработка сырых ticker данных"""
        try:
            ticker_data = self._extract_ticker_data(message)
            if ticker_data and self.on_ticker:
                self.on_ticker(ticker_data)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки ticker: {e}")
    
    def _handle_orderbook_raw(self, message):
        """Обработка сырых orderbook данных"""
        try:
            orderbook_data = self._extract_orderbook_data(message)
            if orderbook_data and self.on_orderbook:
                self.on_orderbook(orderbook_data)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки orderbook: {e}")
    
    def _handle_trades_raw(self, message):
        """Обработка сырых trade данных"""
        try:
            trades_data = self._extract_trades_data(message)
            if trades_data and self.on_trades:
                self.on_trades(trades_data)
                
        except Exception as e:
            self.logger.error(f"Ошибка обработки trades: {e}")
    
    def _extract_kline_data(self, message) -> Optional[Dict]:
        """Извлечение kline данных из pybit сообщения"""
        try:
            # Безопасное извлечение данных
            if isinstance(message, dict) and 'data' in message:
                data_list = message['data']
                if isinstance(data_list, list) and len(data_list) > 0:
                    kline = data_list[0]
                    
                    return {
                        "symbol": self.symbol,
                        "timestamp": int(kline.get('start', 0)),
                        "open": float(kline.get('open', 0)),
                        "high": float(kline.get('high', 0)),
                        "low": float(kline.get('low', 0)),
                        "close": float(kline.get('close', 0)),
                        "volume": float(kline.get('volume', 0)),
                        "confirm": kline.get('confirm', False),
                        "interval": kline.get('interval', '5'),
                        "raw_timestamp": datetime.now()
                    }
        except Exception as e:
            self.logger.debug(f"Не удалось извлечь kline данные: {e}")
        
        return None
    
    def _extract_ticker_data(self, message) -> Optional[Dict]:
        """Извлечение ticker данных из pybit сообщения"""
        try:
            # Поддержка разных форматов pybit
            if isinstance(message, dict):
                if 'data' in message:
                    ticker = message['data']
                    if isinstance(ticker, list) and len(ticker) > 0:
                        ticker = ticker[0]
                else:
                    ticker = message
                
                return {
                    "symbol": ticker.get('symbol', self.symbol),
                    "last_price": float(ticker.get('lastPrice', 0)),
                    "price_24h_pcnt": float(ticker.get('price24hPcnt', 0)),
                    "volume_24h": float(ticker.get('volume24h', 0)),
                    "high_24h": float(ticker.get('highPrice24h', 0)),
                    "low_24h": float(ticker.get('lowPrice24h', 0)),
                    "bid1_price": float(ticker.get('bid1Price', 0)),
                    "ask1_price": float(ticker.get('ask1Price', 0)),
                    "raw_timestamp": datetime.now()
                }
        except Exception as e:
            self.logger.debug(f"Не удалось извлечь ticker данные: {e}")
        
        return None
    
    def _extract_orderbook_data(self, message) -> Optional[Dict]:
        """Извлечение orderbook данных из pybit сообщения"""
        try:
            if isinstance(message, dict) and 'data' in message:
                data = message['data']
                
                bids = data.get('b', [])
                asks = data.get('a', [])
                
                return {
                    "symbol": self.symbol,
                    "bids": [[float(bid[0]), float(bid[1])] for bid in bids[:10]],
                    "asks": [[float(ask[0]), float(ask[1])] for ask in asks[:10]],
                    "timestamp": data.get('u', int(datetime.now().timestamp() * 1000)),
                    "raw_timestamp": datetime.now()
                }
        except Exception as e:
            self.logger.debug(f"Не удалось извлечь orderbook данные: {e}")
        
        return None
    
    def _extract_trades_data(self, message) -> Optional[List[Dict]]:
        """Извлечение trade данных из pybit сообщения"""
        try:
            if isinstance(message, dict) and 'data' in message:
                trades_list = message['data']
                if not isinstance(trades_list, list):
                    trades_list = [trades_list]
                
                processed_trades = []
                for trade in trades_list:
                    processed_trades.append({
                        "symbol": self.symbol,
                        "timestamp": int(trade.get('T', 0)),
                        "price": float(trade.get('p', 0)),
                        "size": float(trade.get('v', 0)),
                        "side": trade.get('S', ''),
                        "trade_id": trade.get('i', ''),
                        "raw_timestamp": datetime.now()
                    })
                
                return processed_trades if processed_trades else None
        except Exception as e:
            self.logger.debug(f"Не удалось извлечь trades данные: {e}")
        
        return None
    
    def get_rest_ticker(self, symbol: str = None) -> Optional[Dict]:
        """Получение ticker через REST API"""
        try:
            target_symbol = symbol or self.symbol
            response = self.http_client.get_tickers(category="linear", symbol=target_symbol)
            
            if response.get("retCode") == 0:
                ticker_list = response.get("result", {}).get("list", [])
                if ticker_list:
                    return ticker_list[0]
        except Exception as e:
            self.logger.error(f"Ошибка получения REST ticker: {e}")
        
        return None
    
    def get_rest_klines(self, symbol: str = None, limit: int = 50) -> Optional[List]:
        """Получение klines через REST API"""
        try:
            target_symbol = symbol or self.symbol
            response = self.http_client.get_kline(
                category="linear", 
                symbol=target_symbol, 
                interval="5", 
                limit=limit
            )
            
            if response.get("retCode") == 0:
                return response.get("result", {}).get("list", [])
        except Exception as e:
            self.logger.error(f"Ошибка получения REST klines: {e}")
        
        return None
    
    async def disconnect(self):
        """Отключение от WebSocket"""
        try:
            self.is_connected = False
            # pybit автоматически управляет соединениями
            self.logger.info("WebSocket отключен")
        except Exception as e:
            self.logger.error(f"Ошибка отключения WebSocket: {e}")
    
    def get_connection_status(self) -> Dict:
        """Получение статуса подключения"""
        return {
            "is_connected": self.is_connected,
            "websocket_active": self.ws is not None,
            "symbol": self.symbol,
            "testnet": self.settings.BYBIT_WS_TESTNET,
            "callbacks_set": {
                "kline": self.on_kline is not None,
                "ticker": self.on_ticker is not None,
                "orderbook": self.on_orderbook is not None,
                "trades": self.on_trades is not None
            }
        }
