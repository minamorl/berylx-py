"""Immutable focus snapshots, workflow result envelopes and committed roots."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence as ABCSequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, TypeVar

S = TypeVar("S")
MISSING = object()


class FrozenDict(Mapping):
    """Owned read-only mapping; unlike an external proxy, children are frozen."""

    __slots__ = ("_data",)
    _data: dict[Any, Any]

    def __init__(self):
        object.__setattr__(self, "_data", {})

    def __setattr__(self, name, value):
        raise TypeError("immutable mapping")

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return repr(self._data)


class FrozenList(ABCSequence):
    """Read-only list view with list-compatible equality and cycle support."""

    __slots__ = ("_items",)
    _items: list[Any]

    def __init__(self):
        object.__setattr__(self, "_items", [])

    def __setattr__(self, name, value):
        raise TypeError("immutable list")

    def __getitem__(self, key):
        return self._items[key]

    def __len__(self):
        return len(self._items)

    def __eq__(self, other):
        return isinstance(other, (list, tuple, FrozenList)) and list(self) == list(other)

    def __repr__(self):
        return repr(self._items)


def freeze(value, active=None):
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if not isinstance(value, (Mapping, list)):
        return value
    active = {} if active is None else active
    if id(value) in active:
        return active[id(value)]
    if isinstance(value, Mapping):
        frozen = FrozenDict()
        target = frozen._data
        active[id(value)] = frozen
        target.update((key, freeze(child, active)) for key, child in value.items())
    else:
        frozen_list = FrozenList()
        active[id(value)] = frozen_list
        frozen_list._items.extend(freeze(child, active) for child in value)
        del active[id(value)]
        return frozen_list
    del active[id(value)]
    return frozen


def plain(value, active=None):
    """Convert immutable JSON-shaped values for serialization (cycles retained)."""
    active = {} if active is None else active
    if id(value) in active:
        return active[id(value)]
    if isinstance(value, Mapping):
        out: dict[Any, Any] = {}
        active[id(value)] = out
        out.update((key, plain(child, active)) for key, child in value.items())
        return out
    if isinstance(value, (FrozenList, list, tuple)):
        items: list[Any] = []
        active[id(value)] = items
        items.extend(plain(child, active) for child in value)
        return items
    return value


def index(key):
    try:
        number = int(key)
        if isinstance(key, float) and number != key:
            raise ValueError
        if isinstance(key, str) and float(key) != number:
            raise ValueError
        if number < 0:
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise KeyError(key) from None


def dig(value, path):
    for key in path:
        if isinstance(value, Mapping):
            value = value[key]
        elif isinstance(value, (list, tuple, FrozenList)):
            try:
                value = value[index(key)]
            except IndexError:
                raise KeyError(key) from None
        elif value is not None and hasattr(value, "__dict__"):
            try:
                value = getattr(value, str(key))
            except AttributeError:
                raise KeyError(key) from None
        else:
            raise KeyError(key)
    return value


def assoc(value, path, next_value):
    if not path:
        return next_value
    key, *rest = path
    if value is None or isinstance(value, Mapping):
        base = dict(value or {})
        base[key] = assoc(base.get(key), rest, next_value)
        return base
    if isinstance(value, (list, tuple, FrozenList)):
        i = index(key)
        items = list(value)
        if i >= len(items):
            items.extend([None] * (i + 1 - len(items)))
        items[i] = assoc(items[i], rest, next_value)
        return items
    if callable(getattr(value, "with_patch", None)):
        return value.with_patch({key: assoc(getattr(value, str(key), None), rest, next_value)})
    raise TypeError(f"cannot update {type(value).__name__} at {key}")


@dataclass(frozen=True, init=False)
class Focus(Generic[S]):
    value: S
    path: tuple

    def __init__(self, value=MISSING, path=()):
        object.__setattr__(self, "value", freeze({} if value is MISSING else value))
        object.__setattr__(self, "path", tuple(path))

    @classmethod
    def of(cls, value=MISSING):
        return cls(value)

    def at(self, key):
        return Focus(self.value, (*self.path, key))

    def get(self, default=MISSING):
        try:
            return dig(self.value, self.path)
        except (KeyError, TypeError, IndexError):
            if default is MISSING:
                raise
            return default

    fetch = get

    def maybe(self):
        return self.get(None)

    def present(self):
        try:
            self.get()
            return True
        except (KeyError, TypeError, IndexError):
            return False

    def required(self, code="missing_focus", message=None):
        try:
            self.get()
            return Ok(self)
        except (KeyError, TypeError, IndexError) as cause:
            return self.reject(
                code,
                f"missing focus at {list(self.path)}" if message is None else message,
                cause=cause,
            )

    def set(self, value):
        return Focus(assoc(self.value, self.path, value))

    def update(self, block):
        return self.set(block(self.get()))

    def put(self, key, value):
        return self.at(key).set(value)

    def reject(self, code, message=None, **context):
        return ResultOps.err(self, code, message, **context)

    def to_object(self) -> S:
        return self.value


Lay = Focus


class ControlSignal(Exception):
    """Explicit interpreter escape; ordinary task errors become Err instead."""


class BerylxError(Exception):
    def __init__(
        self,
        code,
        message=None,
        *,
        cause=None,
        failed_node=None,
        trace=(),
        parallel_errors=(),
        metadata=None,
        fatal=False,
    ):
        self.code = str(code)
        self.message = self.code if message is None else message
        super().__init__(self.message)
        self.cause = cause
        self.failed_node = failed_node
        self.trace = tuple(x if isinstance(x, str) else x.name for x in trace if x is not None)
        self.parallel_errors = tuple(parallel_errors)
        self.metadata = MappingProxyType(dict(metadata or {}))
        self._fatal = fatal

    @classmethod
    def create(cls, code, message=None, **context):
        return cls(code, message, **context)

    @classmethod
    def from_exception(cls, error, **context):
        if isinstance(error, cls):
            return error.with_context(**context)
        cause = context.pop("cause", error if isinstance(error, Exception) else None)
        return cls(
            type(cause).__name__ if cause is not None else "error",
            str(cause) if cause is not None else "error",
            cause=cause,
            **context,
        )

    def fatal(self):
        return self._fatal

    def with_context(self, **context):
        values = dict(
            cause=self.cause,
            failed_node=self.failed_node,
            trace=self.trace,
            parallel_errors=self.parallel_errors,
            metadata=dict(self.metadata),
            fatal=self._fatal,
        )
        context = {
            key: value
            for key, value in context.items()
            if value is not None
            or key not in ("failed_node", "trace", "parallel_errors", "metadata")
        }
        if "metadata" in context:
            context["metadata"] = {**self.metadata, **context["metadata"]}
        values.update(context)
        return BerylxError(self.code, self.message, **values)

    def prepend_trace(self, node):
        name = node if isinstance(node, str) else node.name
        return self.with_context(
            failed_node=name if self.failed_node is None else self.failed_node,
            trace=(name, *self.trace),
        )

    def unwrap(self):
        return self if self.cause is None else self.cause

    to_exception = unwrap

    def to_object(self):
        return dict(
            code=self.code,
            message=self.message,
            failedNode=self.failed_node,
            trace=list(self.trace),
            fatal=self._fatal,
            parallelErrors=[e.to_object() for e in self.parallel_errors],
            metadata=dict(self.metadata),
        )


@dataclass(frozen=True)
class Ok(Generic[S]):
    focus: Focus[S]

    def is_ok(self):
        return True

    def is_err(self):
        return False

    def pipe(self, node):
        return ResultOps.bind(self, node.call)


@dataclass(frozen=True)
class Err(Generic[S]):
    focus: Focus[S]
    error: BerylxError

    def is_ok(self):
        return False

    def is_err(self):
        return True

    def pipe(self, node):
        return self

    def unwrap(self):
        raise self.error.unwrap()

    def to_exception(self):
        return self.error.unwrap()

    @property
    def code(self):
        return self.error.code

    @property
    def message(self):
        return self.error.message

    @property
    def cause(self):
        return self.error.cause

    @property
    def failed_node(self):
        return self.error.failed_node

    @property
    def trace(self):
        return self.error.trace

    @property
    def parallel_errors(self):
        return self.error.parallel_errors


Result = Ok[S] | Err[S]


class ResultOps:
    @staticmethod
    def coerce_focus(value):
        return value if isinstance(value, Focus) else Focus.of(value)

    @staticmethod
    def ok(value):
        return Ok(ResultOps.coerce_focus(value))

    @staticmethod
    def err(value, code, message=None, **context):
        error = (
            code.with_context(**context)
            if isinstance(code, BerylxError)
            else BerylxError(code, message, **context)
        )
        return Err(ResultOps.coerce_focus(value), error)

    @staticmethod
    def normalize(value):
        return value if isinstance(value, (Ok, Err)) else ResultOps.ok(value)

    @staticmethod
    def bind(result, block):
        return ResultOps.normalize(block(result.focus)) if isinstance(result, Ok) else result

    map = bind


class Flow(Generic[S]):
    def __init__(self, value):
        self.focus = ResultOps.coerce_focus(value)

    @classmethod
    def of(cls, value):
        return cls(value)

    def call(self, node, handlers=None):
        from .effect_tree import EffectTree

        return EffectTree.run(node, self.focus, handlers)

    then = call


class State(Generic[S]):
    def __init__(self, lay, node=None):
        self.lay = ResultOps.coerce_focus(lay)
        self.node = node

    @classmethod
    def of(cls, value=MISSING):
        return cls(Focus.of(value))

    def and_then(self, node):
        if not callable(getattr(node, "call", None)):
            raise TypeError("expected a Berylx task/workflow node")
        return State(self.lay, self.node.then(node) if self.node else node)

    def call(self, node=None, handlers=None):
        target = node if node is not None else self.node
        if target is None:
            raise ValueError("State has no task to run")
        return Flow.of(self.lay).call(target, handlers)

    pipe = call

    def to_lay(self):
        return self.lay


class Root(Generic[S]):
    def __init__(self, value=MISSING, *, history_limit=None):
        if history_limit is not None and (type(history_limit) is not int or history_limit < 0):
            raise ValueError("Root history_limit must be a non-negative integer")
        self._value = Focus.of(value) if value is MISSING else ResultOps.coerce_focus(value)
        self.history = []
        self._subscribers = []
        self.history_limit = history_limit

    @classmethod
    def of(cls, value=MISSING, **options):
        return cls(value, **options)

    def call(self, node, handlers=None):
        result = Flow(self._value).call(node, handlers)
        if isinstance(result, Ok):
            self.commit(result.focus)
        return result

    pipe = call

    def commit(self, value):
        from .merge import Merge

        if isinstance(value, Root):
            value = value.to_lay()
        if isinstance(value, (Ok, Err)):
            value = value.focus
        if isinstance(value, Focus):
            self._value = value
        elif isinstance(value, Mapping):
            self._value = Merge.deep()(self._value, Focus.of(value))
        else:
            self._value = Focus.of(value)
        event = {"type": "commit", "value": self.state()}
        if self.history_limit != 0:
            self.history.append(event)
            if self.history_limit is not None:
                del self.history[: -self.history_limit]
        for subscriber in tuple(self._subscribers):
            subscriber(event)
        return self

    def state(self):
        return self._value.to_object()

    to_object = state

    def to_lay(self):
        return self._value

    def to_state(self):
        return State(self._value)

    def at(self, key):
        return self._value.at(key)

    def subscribe(self, block):
        if not callable(block):
            raise TypeError("Root.subscribe requires a callback")
        self._subscribers.append(block)
        block({"type": "snapshot", "value": self.state()})

        def unsubscribe():
            self._subscribers[:] = [x for x in self._subscribers if x is not block]

        return unsubscribe
