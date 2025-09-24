"""
In-memory хранилище рыночных данных
Управление жизненным циклом данных, лимиты памяти
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import deque
from threading import Lock


class MarketDataStore:
    """In-memory хранилище рыночных данных"""
    
    def __init__(self, max_klines: int = 200, max_trades: int = 1000, max_orderbook_history: int = 50):
        self.max_klines = max_klines
        self.max_trades = max_trades
        self.max_orderbook_history = max_orderbook_history
        
        # Thread-safe хранилища
        self._lock = Lock()
        
        # Основные данные
        self._klines = deque(maxlen=max_klines)
        self._ticker = None
        self._orderbook = None
        self._trades = deque(maxlen=max_trades)
        
        # История
        self._orderbook_history = deque(maxlen=max_orderbook_history)
        
        # Агрегированные данные
        self._market_stats = {}
        self._price_levels = {"support": [], "resistance": []}
        self._volume_profile = {}
        
        # Метаданные
        self._last_update = {}
        self._data_quality = {}
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("MarketDataStore инициализирован")
    
    def add_kline(self, kline: Dict) -> bool:
        """Добавление kline данных"""
        try:
            with self._lock:
                # Проверяем, не дубликат ли это
                if self._klines and self._klines[-1].get("timestamp") == kline.get("timestamp"):
                    # Обновляем последнюю свечу если она не подтверждена
                    if not kline.get("confirm", False):
                        self._klines[-1] = kline
                        self._last_update["klines"] = datetime.now()
                        return True
                    return False
                
                # Добавляем новую свечу только если она подтверждена
                if kline.get("confirm", False):
                    self._klines.append(kline)
                    self._last_update["klines"] = datetime.now()
                    self._update_price_levels(kline)
                    return True
                else:
                    # Обновляем последнюю неподтвержденную свечу
                    if self._klines:
                        self._klines[-1] = kline
                    else:
                        self._klines.append(kline)
                    self._last_update["klines"] = datetime.now()
                    return True
                    
        except Exception as e:
            self.logger.error(f"Ошибка добавления kline: {e}")
            return False
    
    def update_ticker(self, ticker: Dict) -> bool:
        """Обновление ticker данных"""
        try:
            with self._lock:
                self._ticker = ticker
                self._last_update["ticker"] = datetime.now()
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка обновления ticker: {e}")
            return False
    
    def update_orderbook(self, orderbook: Dict) -> bool:
        """Обновление orderbook данных"""
        try:
            with self._lock:
                # Сохраняем в историю если есть значительные изменения
                if self._should_save_orderbook_history(orderbook):
                    self._orderbook_history.append({
                        "timestamp": orderbook.get("timestamp"),
                        "spread": orderbook.get("spread", 0),
                        "best_bid": orderbook.get("best_bid", 0),
                        "best_ask": orderbook.get("best_ask", 0),
                        "total_bid_volume": orderbook.get("total_bid_volume", 0),
                        "total_ask_volume": orderbook.get("total_ask_volume", 0),
                        "order_imbalance": orderbook.get("order_imbalance", 0)
                    })
                
                self._orderbook = orderbook
                self._last_update["orderbook"] = datetime.now()
                self._update_volume_profile(orderbook)
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка обновления orderbook: {e}")
            return False
    
    def add_trades(self, trades: List[Dict]) -> bool:
        """Добавление trade данных"""
        try:
            with self._lock:
                for trade in trades:
                    self._trades.append(trade)
                
                self._last_update["trades"] = datetime.now()
                self._update_market_stats()
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка добавления trades: {e}")
            return False
    
    def get_klines(self, limit: Optional[int] = None, confirmed_only: bool = True) -> List[Dict]:
        """Получение kline данных"""
        try:
            with self._lock:
                klines = list(self._klines)
                
                if confirmed_only:
                    klines = [k for k in klines if k.get("confirm", False)]
                
                if limit:
                    klines = klines[-limit:]
                
                return klines
                
        except Exception as e:
            self.logger.error(f"Ошибка получения klines: {e}")
            return []
    
    def get_ticker(self) -> Optional[Dict]:
        """Получение ticker данных"""
        try:
            with self._lock:
                return self._ticker.copy() if self._ticker else None
                
        except Exception as e:
            self.logger.error(f"Ошибка получения ticker: {e}")
            return None
    
    def get_orderbook(self) -> Optional[Dict]:
        """Получение orderbook данных"""
        try:
            with self._lock:
                return self._orderbook.copy() if self._orderbook else None
                
        except Exception as e:
            self.logger.error(f"Ошибка получения orderbook: {e}")
            return None
    
    def get_trades(self, limit: Optional[int] = None) -> List[Dict]:
        """Получение trade данных"""
        try:
            with self._lock:
                trades = list(self._trades)
                
                if limit:
                    trades = trades[-limit:]
                
                return trades
                
        except Exception as e:
            self.logger.error(f"Ошибка получения trades: {e}")
            return []
    
    def get_market_summary(self) -> Dict:
        """Получение сводки рыночных данных"""
        try:
            with self._lock:
                summary = {
                    "basic_market": self._ticker.copy() if self._ticker else {},
                    "recent_klines": list(self._klines)[-20:] if self._klines else [],
                    "orderbook": self._orderbook.copy() if self._orderbook else {},
                    "recent_trades": list(self._trades)[-50:] if self._trades else [],
                    "market_stats": self._market_stats.copy(),
                    "price_levels": self._price_levels.copy(),
                    "volume_profile": dict(list(self._volume_profile.items())[:20]),  # Топ 20
                    "metadata": {
                        "last_updates": self._last_update.copy(),
                        "data_counts": {
                            "klines": len(self._klines),
                            "trades": len(self._trades),
                            "orderbook_history": len(self._orderbook_history)
                        },
                        "data_quality": self._data_quality.copy(),
                        "generated_at": datetime.now().isoformat()
                    }
                }
                
                return summary
                
        except Exception as e:
            self.logger.error(f"Ошибка получения market summary: {e}")
            return {}
    
    def get_data_quality_report(self) -> Dict:
        """Отчет о качестве данных"""
        try:
            with self._lock:
                now = datetime.now()
                
                quality_report = {
                    "data_freshness": {},
                    "data_counts": {
                        "klines": len(self._klines),
                        "confirmed_klines": len([k for k in self._klines if k.get("confirm", False)]),
                        "trades": len(self._trades),
                        "orderbook_history": len(self._orderbook_history)
                    },
                    "data_availability": {
                        "ticker": self._ticker is not None,
                        "orderbook": self._orderbook is not None,
                        "klines": len(self._klines) > 0,
                        "trades": len(self._trades) > 0
                    }
                }
                
                # Свежесть данных
                for data_type, last_update in self._last_update.items():
                    if last_update:
                        age_seconds = (now - last_update).total_seconds()
                        quality_report["data_freshness"][data_type] = {
                            "last_update": last_update.isoformat(),
                            "age_seconds": age_seconds,
                            "is_fresh": age_seconds < 60  # Свежие если < 1 минуты
                        }
                
                # Общая оценка качества
                fresh_count = sum(1 for info in quality_report["data_freshness"].values() if info["is_fresh"])
                available_count = sum(1 for available in quality_report["data_availability"].values() if available)
                
                quality_report["overall_score"] = {
                    "freshness_score": fresh_count / max(len(self._last_update), 1),
                    "availability_score": available_count / 4,  # 4 типа данных
                    "completeness_score": min(len(self._klines) / 50, 1.0)  # Полнота по klines
                }
                
                return quality_report
                
        except Exception as e:
            self.logger.error(f"Ошибка получения data quality report: {e}")
            return {}
    
    def _should_save_orderbook_history(self, new_orderbook: Dict) -> bool:
        """Определяет, стоит ли сохранять orderbook в историю"""
        if not self._orderbook_history:
            return True
        
        last_entry = self._orderbook_history[-1]
        
        # Сохраняем если изменился спред на > 5% или дисбаланс на > 10%
        try:
            spread_change = abs(new_orderbook.get("spread", 0) - last_entry["spread"]) / max(last_entry["spread"], 0.0001)
            imbalance_change = abs(new_orderbook.get("order_imbalance", 0) - last_entry["order_imbalance"])
            
            return spread_change > 0.05 or imbalance_change > 0.1
            
        except Exception:
            return True
    
    def _update_price_levels(self, kline: Dict):
        """Обновление уровней поддержки и сопротивления"""
        try:
            high_price = kline["high"]
            low_price = kline["low"]
            
            # Простое определение уровней по локальным экстремумам
            recent_klines = list(self._klines)[-5:] if len(self._klines) >= 5 else list(self._klines)
            
            if len(recent_klines) >= 3:
                recent_highs = [k["high"] for k in recent_klines]
                recent_lows = [k["low"] for k in recent_klines]
                
                # Локальный максимум
                if high_price == max(recent_highs):
                    self._price_levels["resistance"].append({
                        "price": high_price,
                        "timestamp": kline["timestamp"],
                        "strength": 1,
                        "touches": 1
                    })
                
                # Локальный минимум
                if low_price == min(recent_lows):
                    self._price_levels["support"].append({
                        "price": low_price,
                        "timestamp": kline["timestamp"],
                        "strength": 1,
                        "touches": 1
                    })
            
            # Ограничиваем количество уровней
            self._price_levels["resistance"] = self._price_levels["resistance"][-20:]
            self._price_levels["support"] = self._price_levels["support"][-20:]
            
        except Exception as e:
            self.logger.debug(f"Ошибка обновления price levels: {e}")
    
    def _update_volume_profile(self, orderbook: Dict):
        """Обновление профиля объема"""
        try:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            for bid in bids[:10]:
                price = round(float(bid[0]), 2)
                volume = float(bid[1])
                
                if price not in self._volume_profile:
                    self._volume_profile[price] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self._volume_profile[price]["bid_volume"] += volume
                self._volume_profile[price]["total_volume"] += volume
            
            for ask in asks[:10]:
                price = round(float(ask[0]), 2)
                volume = float(ask[1])
                
                if price not in self._volume_profile:
                    self._volume_profile[price] = {"bid_volume": 0, "ask_volume": 0, "total_volume": 0}
                
                self._volume_profile[price]["ask_volume"] += volume
                self._volume_profile[price]["total_volume"] += volume
            
            # Ограичиваем размер профиля объема
            if len(self._volume_profile) > 200:
                # Оставляем топ 100 по объему
                sorted_levels = sorted(self._volume_profile.items(), key=lambda x: x[1]["total_volume"], reverse=True)
                self._volume_profile = dict(sorted_levels[:100])
                
        except Exception as e:
            self.logger.debug(f"Ошибка обновления volume profile: {e}")
    
    def _update_market_stats(self):
        """Обновление рыночной статистики"""
        try:
            if not self._trades:
                return
            
            # Анализ последних сделок
            recent_trades = list(self._trades)[-100:]
            
            if recent_trades:
                buy_trades = [t for t in recent_trades if t["side"].upper() == "BUY"]
                sell_trades = [t for t in recent_trades if t["side"].upper() == "SELL"]
                
                total_volume = sum(t["size"] for t in recent_trades)
                buy_volume = sum(t["size"] for t in buy_trades)
                sell_volume = sum(t["size"] for t in sell_trades)
                
                self._market_stats = {
                    "total_trades": len(recent_trades),
                    "buy_trades": len(buy_trades),
                    "sell_trades": len(sell_trades),
                    "buy_sell_ratio": len(buy_trades) / max(len(sell_trades), 1),
                    "total_volume": total_volume,
                    "buy_volume": buy_volume,
                    "sell_volume": sell_volume,
                    "volume_imbalance": (buy_volume - sell_volume) / max(total_volume, 1),
                    "avg_trade_size": total_volume / len(recent_trades),
                    "last_trade_price": recent_trades[-1]["price"] if recent_trades else 0,
                    "updated_at": datetime.now().isoformat()
                }
                
        except Exception as e:
            self.logger.debug(f"Ошибка обновления market stats: {e}")
    
    def cleanup_old_data(self, max_age_hours: int = 24):
        """Очистка старых данных"""
        try:
            with self._lock:
                cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
                cutoff_timestamp = int(cutoff_time.timestamp() * 1000)
                
                # Очищаем старые klines
                self._klines = deque(
                    [k for k in self._klines if k.get("timestamp", 0) > cutoff_timestamp],
                    maxlen=self.max_klines
                )
                
                # Очищаем старые trades
                self._trades = deque(
                    [t for t in self._trades if t.get("timestamp", 0) > cutoff_timestamp],
                    maxlen=self.max_trades
                )
                
                # Очищаем старую историю orderbook
                self._orderbook_history = deque(
                    [o for o in self._orderbook_history if o.get("timestamp", 0) > cutoff_timestamp],
                    maxlen=self.max_orderbook_history
                )
                
                # Очищаем старые price levels
                for level_type in ["support", "resistance"]:
                    self._price_levels[level_type] = [
                        level for level in self._price_levels[level_type]
                        if level.get("timestamp", 0) > cutoff_timestamp
                    ]
                
                self.logger.info(f"Очистка старых данных завершена (старше {max_age_hours} часов)")
                
        except Exception as e:
            self.logger.error(f"Ошибка очистки старых данных: {e}")
    
    def get_memory_usage(self) -> Dict:
        """Получение информации об использовании памяти"""
        try:
            import sys
            
            return {
                "klines": {
                    "count": len(self._klines),
                    "memory_bytes": sys.getsizeof(self._klines)
                },
                "trades": {
                    "count": len(self._trades),
                    "memory_bytes": sys.getsizeof(self._trades)
                },
                "orderbook_history": {
                    "count": len(self._orderbook_history),
                    "memory_bytes": sys.getsizeof(self._orderbook_history)
                },
                "volume_profile": {
                    "levels": len(self._volume_profile),
                    "memory_bytes": sys.getsizeof(self._volume_profile)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка получения memory usage: {e}")
            return {}
