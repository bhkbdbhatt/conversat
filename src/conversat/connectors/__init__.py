"""Pluggable bot connectors.

Built-ins: ``echo`` and ``scripted`` (offline), ``http`` (httpx),
``websocket`` (websockets) and ``web`` (Playwright). Register your own with
:func:`register`.
"""

from __future__ import annotations

from conversat.connectors.echo import EchoConfig, EchoConnector, ScriptedConfig, ScriptedConnector
from conversat.connectors.http import HttpConfig, HttpConnector
from conversat.connectors.registry import (
    BUILTINS,
    available,
    connector_defaults,
    create_connector,
    describe_connector,
    is_builtin,
    register,
    unregister,
)
from conversat.connectors.websocket import WebSocketConfig, WebSocketConnector
from conversat.connectors.web import WebConfig, WebConnector
from conversat.engine.base import Connector, ConnectorSequence, SyncFunctionConnector

__all__ = [
    "BUILTINS",
    "Connector",
    "ConnectorSequence",
    "EchoConfig",
    "EchoConnector",
    "HttpConfig",
    "HttpConnector",
    "ScriptedConfig",
    "ScriptedConnector",
    "SyncFunctionConnector",
    "WebConfig",
    "WebConnector",
    "WebSocketConfig",
    "WebSocketConnector",
    "available",
    "connector_defaults",
    "create_connector",
    "describe_connector",
    "is_builtin",
    "register",
    "unregister",
]
