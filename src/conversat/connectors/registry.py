"""Connector registry.

Built-in connectors are imported lazily (via ``module:Class`` targets) so that
importing conversat never pulls in Playwright or websockets unless you use
them::

    from conversat.connectors import create_connector, register

    register("my-bot", lambda cfg: MyBot(cfg), override=True)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from conversat.engine.base import Connector
from conversat.errors import ConnectorError, RegistryError

if TYPE_CHECKING:  # pragma: no cover
    from conversat.models.suite import ConnectorConfig

BUILTINS: dict[str, str] = {
    "echo": "conversat.connectors.echo:EchoConnector",
    "scripted": "conversat.connectors.echo:ScriptedConnector",
    "http": "conversat.connectors.http:HttpConnector",
    "websocket": "conversat.connectors.websocket:WebSocketConnector",
    "web": "conversat.connectors.web:WebConnector",
}

ConnectorFactory = Callable[[Any], Connector]

_FACTORIES: dict[str, ConnectorFactory] = {}


def register(name: str, factory: ConnectorFactory, *, override: bool = False) -> None:
    if name in BUILTINS and not override and name not in _FACTORIES:
        return  # built-in wins; caller must pass override=True
    if name in _FACTORIES and not override:
        raise RegistryError(f"connector {name!r} is already registered")
    _FACTORIES[name] = factory


def unregister(name: str) -> None:
    _FACTORIES.pop(name, None)


def available() -> list[str]:
    return sorted(set(BUILTINS) | set(_FACTORIES))


def is_builtin(name: str) -> bool:
    return name in BUILTINS


def create_connector(config: ConnectorConfig) -> Connector:
    """Instantiate the connector described by ``config``.

    The connector's ``config_model`` validates the raw ``config`` mapping, so
    a bad setting fails fast with a pydantic error.
    """
    name = config.type
    factory = _FACTORIES.get(name)

    if factory is None:
        target = BUILTINS.get(name)
        if target is None:
            raise ConnectorError(
                f"unknown connector type {name!r}; available: {', '.join(available())}",
                connector=name,
            )
        connector_cls = _import_target(target)
        factory = _model_factory(connector_cls)
        register(name, factory, override=True)

    try:
        return factory(config.config)
    except ConnectorError:
        raise
    except Exception as exc:  # noqa: BLE001 - re-raised with connector context
        raise ConnectorError(f"cannot build connector: {exc}", connector=name, cause=exc) from exc


def _import_target(target: str) -> type[Connector]:
    module_name, _, attr = target.partition(":")
    import importlib

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConnectorError(
            f"connector dependency is missing ({exc}); install conversat with all extras",
            connector=target,
        ) from exc
    cls = getattr(module, attr)
    if not (isinstance(cls, type) and issubclass(cls, Connector)):
        raise ConnectorError(f"{target} is not a Connector subclass", connector=target)
    return cls


def _model_factory(connector_cls: type[Connector]) -> ConnectorFactory:
    model = getattr(connector_cls, "config_model", None)

    def factory(raw: Any) -> Connector:
        if model is None:
            return connector_cls(raw)
        if isinstance(raw, model):
            return connector_cls(raw)
        return connector_cls(model.model_validate(raw or {}))

    return factory


def describe_connector(name: str) -> str:
    """Short help text for the CLI (``conversat connectors``)."""
    if name in _FACTORIES:
        return "custom connector"
    target = BUILTINS.get(name)
    if not target:
        return "unknown"
    module_name = target.split(":")[0].rsplit(".", 1)[-1]
    return f"built-in ({module_name})"


def connector_defaults(name: str) -> dict[str, Any]:
    """Default configuration for a built-in connector (from its pydantic model)."""
    target = BUILTINS.get(name)
    if not target:
        return {}
    connector_cls = _import_target(target)
    model = getattr(connector_cls, "config_model", None)
    if model is None:
        return {}
    return {k: v for k, v in model.model_json_schema().get("properties", {}).items()}
