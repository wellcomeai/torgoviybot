"""
Главный координатор всех компонентов рыночных данных
Связывает WebSocket, обработку, хранилище и генерацию сигналов
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

from core.pybit_websocket import PybitWebSocket
from core.data_processor import DataProcessor
from core.market_data_store import MarketDataStore
from core.signal_processor import SignalProcessor


class MarketManager:
    """Главный координатор рыночных данных"""
    
    def __init__(self, symbol: str, on_signal_callback: Optional[Callable] = None):
        self.symbol = symbol
        self.on_signal_callback = on_signal_callback
        
        # Инициализация компонентов
        self.websocket = PybitWebSocket(symbol)
        self.data_processor = DataProcessor()
        self.data_store = MarketDataStore()
        self.signal_processor = SignalProcessor()
        
        # Состояние
        self.is_running = False
        self.last_analysis_time = None
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"MarketManager инициализирован для {symbol}")
        
        # Настройка связей между компонентами
        self._setup_component_connections()
    
    def _setup_component_connections(self):
        """Настройка связей между компонентами"""
        # Связываем WebSocket с обработкой данных
        self.websocket.set_callbacks(
            on_kline=self._handle_kline,
            on_ticker=self._handle_ticker,
            on_orderbook=self._handle_orderbook,
            on_trades=self._handle_trades
        )
        
        # Связываем SignalProcessor с callback
        if self.on_signal_callback:
            self.signal_processor.set_signal_callback(self._handle_generated_signal)
    
    def _handle_kline(self, raw_kline: Dict):
        """Обработка kline данных"""
        try:
            # Обрабатываем данные
            processed_kline = self.data_processor.process_kline(raw_kline)
            if not processed_kline:
                return
            
            # Сохраняем в хранилище
            success = self.data_store.add_kline(processed_kline)
            if success:
                self.logger.debug(f"Kline обработан: {processed_kline['close']:.4f} @ {processed_kline['datetime']}")
                
                # Анализируем сигналы только для подтвержденных свечей
                if processed_kline.get("confirm", False):
                    self._check_for_trading_signals()
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки kline: {e}")
    
    def _handle_ticker(self, raw_ticker: Dict):
        """Обработка ticker данных"""
        try:
            # Обрабатываем данные
            processed_ticker = self.data_processor.process_ticker(raw_ticker)
            if not processed_ticker:
                return
            
            # Сохраняем в хранилище
            success = self.data_store.update_ticker(processed_ticker)
            if success:
                self.logger.debug(f"Ticker обновлен: {processed_ticker['symbol']} @ ${processed_ticker['last_price']:.2f}")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки ticker: {e}")
    
    def _handle_orderbook(self, raw_orderbook: Dict):
        """Обработка orderbook данных"""
        try:
            # Обрабатываем данные
            processed_orderbook = self.data_processor.process_orderbook(raw_orderbook)
            if not processed_orderbook:
                return
            
            # Сохраняем в хранилище
            success = self.data_store.update_orderbook(processed_orderbook)
            if success:
                self.logger.debug("Orderbook обновлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки orderbook: {e}")
    
    def _handle_trades(self, raw_trades: List[Dict]):
        """Обработка trade данных"""
        try:
            # Обрабатываем данные
            processed_trades = self.data_processor.process_trades(raw_trades)
            if not processed_trades:
                return
            
            # Сохраняем в хранилище
            success = self.data_store.add_trades(processed_trades)
            if success:
                self.logger.debug(f"Trades обновлены: +{len(processed_trades)}")
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки trades: {e}")
    
    def _check_for_trading_signals(self):
        """Проверка условий для генерации торговых сигналов"""
        try:
            # Получаем полные рыночные данные
            market_data = self.data_store.get_market_summary()
            if not market_data:
                return
            
            # Валидируем условия для анализа
            validation = self.signal_processor.validate_signal_conditions(market_data)
            if not validation.get("can_generate_signals", False):
                self.logger.debug(f"Сигналы не могут быть сгенерированы: {validation.get('issues', [])}")
                return
            
            # Анализируем рыночные условия
            signal = self.signal_processor.analyze_market_data(market_data)
            if signal:
                self.logger.info(f"Сгенерирован торговый сигнал: {signal.signal_type} {signal.symbol}")
                self.last_analysis_time = datetime.now()
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки торговых сигналов: {e}")
    
    def _handle_generated_signal(self, signal):
        """Обработка сгенерированного сигнала"""
        try:
            # Преобразуем signal в dict для callback
            signal_dict = {
                "signal_id": signal.signal_id,
                "symbol": signal.symbol,
                "signal_type": signal.signal_type,
                "price": signal.price,
                "confidence": signal.confidence,
                "timestamp": signal.timestamp,
                "reason": signal.reason,
                "indicators": signal.indicators,
                "timeframe": signal.timeframe
            }
            
            # Вызываем внешний callback
            if self.on_signal_callback:
                asyncio.create_task(self.on_signal_callback(signal_dict))
            
        except Exception as e:
            self.logger.error(f"Ошибка обработки сгенерированного сигнала: {e}")
    
    async def start(self):
        """Запуск MarketManager"""
        try:
            if self.is_running:
                self.logger.warning("MarketManager уже запущен")
                return
            
            self.logger.info("Запуск MarketManager...")
            
            # Запускаем WebSocket
            await self.websocket.connect()
            
            self.is_running = True
            self.logger.info("MarketManager успешно запущен")
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска MarketManager: {e}")
            raise
    
    async def stop(self):
        """Остановка MarketManager"""
        try:
            if not self.is_running:
                return
            
            self.logger.info("Остановка MarketManager...")
            
            self.is_running = False
            
            # Останавливаем WebSocket
            await self.websocket.disconnect()
            
            # Очищаем старые данные
            self.data_store.cleanup_old_data()
            self.signal_processor.clear_old_signals()
            
            self.logger.info("MarketManager остановлен")
            
        except Exception as e:
            self.logger.error(f"Ошибка остановки MarketManager: {e}")
    
    # Публичные методы для получения данных
    
    def get_market_data(self, symbol: str = None) -> Dict:
        """Получить базовые рыночные данные (совместимость со старым API)"""
        if symbol and symbol != self.symbol:
            return {}
        
        ticker = self.data_store.get_ticker()
        if not ticker:
            return {}
        
        return {
            "symbol": ticker.get("symbol", self.symbol),
            "price": f"{ticker.get('last_price', 0):.4f}",
            "change_24h": f"{ticker.get('change_24h', 0):+.2f}%",
            "volume_24h": f"{ticker.get('volume_24h', 0):,.0f}",
            "high_24h": f"{ticker.get('high_24h', 0):.4f}",
            "low_24h": f"{ticker.get('low_24h', 0):.4f}",
            "timestamp": ticker.get("processed_at"),
            "data_source": "market_manager"
        }
    
    async def get_comprehensive_market_data(self, symbol: str = None) -> Dict:
        """Получить полные рыночные данные для ИИ-анализа"""
        if symbol and symbol != self.symbol:
            return {}
        
        try:
            # Получаем данные из хранилища
            market_summary = self.data_store.get_market_summary()
            
            # Добавляем технические индикаторы
            klines = self.data_store.get_klines(limit=50, confirmed_only=True)
            if klines:
                indicators = self.data_processor.calculate_technical_indicators(klines)
                market_summary["technical_indicators"] = indicators
            
            # Добавляем REST данные если нужно
            rest_ticker = self.websocket.get_rest_ticker()
            if rest_ticker:
                market_summary["rest_ticker"] = rest_ticker
            
            rest_klines = self.websocket.get_rest_klines(limit=20)
            if rest_klines:
                market_summary["rest_klines"] = rest_klines
            
            return market_summary
            
        except Exception as e:
            self.logger.error(f"Ошибка получения comprehensive market data: {e}")
            return {}
    
    def get_connection_status(self) -> Dict:
        """Получить статус подключения"""
        websocket_status = self.websocket.get_connection_status()
        data_quality = self.data_store.get_data_quality_report()
        signal_stats = self.signal_processor.get_signal_statistics()
        
        return {
            "is_running": self.is_running,
            "websocket": websocket_status,
            "data_quality": data_quality,
            "signal_processor": signal_stats,
            "last_analysis_time": self.last_analysis_time.isoformat() if self.last_analysis_time else None,
            "memory_usage": self.data_store.get_memory_usage()
        }
    
    def get_recent_signals(self, limit: int = 10) -> List[Dict]:
        """Получить последние сигналы"""
        return self.signal_processor.get_recent_signals(limit)
    
    def force_market_analysis(self) -> Optional[Dict]:
        """Принудительный анализ рынка (для тестирования)"""
        try:
            market_data = self.data_store.get_market_summary()
            if not market_data:
                return None
            
            signal = self.signal_processor.analyze_market_data(market_data)
            return signal._asdict() if signal else None
            
        except Exception as e:
            self.logger.error(f"Ошибка принудительного анализа: {e}")
            return None
    
    # Методы для интеграции с ИИ-анализатором
    
    def format_market_data_for_ai(self) -> Dict:
        """Форматирование данных для ИИ-анализатора"""
        try:
            market_summary = self.data_store.get_market_summary()
            
            # Добавляем технические индикаторы
            klines = self.data_store.get_klines(limit=50, confirmed_only=True)
            if klines:
                indicators = self.data_processor.calculate_technical_indicators(klines)
                market_summary["technical_indicators"] = indicators
            
            # Форматируем для ИИ-анализатора
            formatted_data = {
                "basic_market": market_summary.get("basic_market", {}),
                "technical_indicators": market_summary.get("technical_indicators", {}),
                "recent_klines": market_summary.get("recent_klines", []),
                "orderbook": market_summary.get("orderbook", {}),
                "recent_trades": market_summary.get("recent_trades", []),
                "market_stats": market_summary.get("market_stats", {}),
                "price_levels": market_summary.get("price_levels", {}),
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": self.symbol,
                    "data_source": "market_manager",
                    "data_quality": self.data_store.get_data_quality_report()
                }
            }
            
            return formatted_data
            
        except Exception as e:
            self.logger.error(f"Ошибка форматирования данных для ИИ: {e}")
            return {}
    
    def get_status_summary(self) -> str:
        """Получить краткую сводку статуса"""
        try:
            status = self.get_connection_status()
            ticker = self.data_store.get_ticker()
            
            if not ticker:
                return f"MarketManager [{self.symbol}]: Данные недоступны"
            
            running_status = "Работает" if self.is_running else "Остановлен"
            websocket_status = "Подключен" if status["websocket"]["is_connected"] else "Отключен"
            price = ticker.get("last_price", 0)
            
            return f"MarketManager [{self.symbol}]: {running_status} | WebSocket: {websocket_status} | Цена: ${price:.2f}"
            
        except Exception as e:
            return f"MarketManager [{self.symbol}]: Ошибка получения статуса - {e}"
