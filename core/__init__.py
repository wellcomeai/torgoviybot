"""
Основные компоненты торгового бота
ИСПРАВЛЕНО: импорт из новой архитектуры
"""

# НОВЫЙ импорт с правильной архитектурой
from .market_manager import MarketManager as WebSocketManager

__all__ = ["WebSocketManager"]
