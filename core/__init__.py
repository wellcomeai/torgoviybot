"""
Основные компоненты торгового бота
WebSocket менеджеры и обработчики данных на базе pybit
"""

# НОВЫЙ импорт
from .pybit_websocket_manager import PybitWebSocketManager as WebSocketManager

__all__ = ["WebSocketManager"]
