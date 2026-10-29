"""Value monads and a tagged Freer effect substrate, independent of workflows."""

from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any, Callable, Generic, TypeVar

A = TypeVar("A")
B = TypeVar("B")
S = TypeVar("S")
PURE = "pure"


@dataclass(frozen=True)
class _Value(Generic[A]):
    value: A

    @classmethod
    def pure(cls, value):
        return cls(value)

    def bind(self, f):
        return f(self.value)

    def fmap(self, f):
        return self.bind(lambda x: type(self)(f(x)))

    map = fmap

    def ap(self, other):
        return self.bind(lambda f: other.fmap(f))

    def seq(self, other):
        return self.bind(lambda _: other)


class _Stop:
    def bind(self, f):
        return self

    def fmap(self, f):
        return self

    map = fmap

    def ap(self, other):
        return self

    def seq(self, other):
        return self


class Just(_Value[A]):
    def is_just(self):
        return True

    def is_nothing(self):
        return False


@dataclass(frozen=True)
class Nothing(_Stop):
    pure = staticmethod(Just)

    def is_just(self):
        return False

    def is_nothing(self):
        return True


class Maybe:
    pure = just = Just
    nothing = Nothing
    from_nil = staticmethod(lambda x: Nothing() if x is None else Just(x))


class Right(_Value[A]):
    def is_right(self):
        return True

    def is_left(self):
        return False


@dataclass(frozen=True)
class Left(_Stop, Generic[A]):
    value: A
    pure = staticmethod(Right)

    def is_left(self):
        return True

    def is_right(self):
        return False


class Either:
    pure = right = Right
    left = Left


class Ok(_Value[A]):
    def is_ok(self):
        return True

    def is_err(self):
        return False


@dataclass(frozen=True)
class Err(_Stop, Generic[A]):
    error: A
    pure = staticmethod(Ok)

    def is_err(self):
        return True

    def is_ok(self):
        return False


class Result:
    pure = ok = Ok
    err = Err

    @staticmethod
    def try_(block):
        try:
            return Ok(block())
        except Exception as e:
            return Err(str(e))


class Success(_Value[A]):
    def is_success(self):
        return True

    def is_failure(self):
        return False


@dataclass(frozen=True, init=False)
class Failure(_Stop):
    errors: tuple
    pure = staticmethod(Success)

    def __init__(self, errors):
        object.__setattr__(self, "errors", tuple(errors))

    def ap(self, other):
        return Failure(self.errors + other.errors) if isinstance(other, Failure) else self

    def is_success(self):
        return False

    def is_failure(self):
        return True


class Validation:
    pure = success = Success

    @staticmethod
    def failure(*errors):
        return Failure(
            e for group in errors for e in (group if isinstance(group, list) else [group])
        )


@dataclass(frozen=True)
class State(Generic[S, A]):
    run_fn: Callable[[S], tuple[A, S]]

    @staticmethod
    def pure(x):
        return State(lambda s: (x, s))

    of = pure

    def run(self, s):
        return self.run_fn(s)

    def bind(self, f):
        def run(s):
            a, next_state = self.run(s)
            return f(a).run(next_state)

        return State(run)

    def fmap(self, f):
        return self.bind(lambda x: State.pure(f(x)))

    map = fmap

    def ap(self, other):
        return self.bind(lambda f: other.fmap(f))

    def seq(self, other):
        return self.bind(lambda _: other)

    @staticmethod
    def get():
        return State(lambda s: (s, s))

    @staticmethod
    def put(s):
        return State(lambda _: (None, s))

    @staticmethod
    def modify(f):
        return State(lambda s: (None, f(s)))


@dataclass(frozen=True)
class EffectStep(Generic[A]):
    closed: bool
    value: Any = None
    tag: str = PURE
    payload: Any = None
    resume: Any = None


@dataclass(frozen=True)
class Effect(Generic[A]):
    """Shallow immutable operation/continuation tree; handlers own interpretation."""

    _step: EffectStep[A]

    @staticmethod
    def pure(x: B) -> Effect[B]:
        return Effect(EffectStep(True, value=x, payload=x))

    @staticmethod
    def op(tag: str, payload: Any, decode: Callable[[Any], B]) -> Effect[B]:
        if tag == PURE:
            raise ValueError("pure tag is reserved")
        return Effect(
            EffectStep(
                False,
                tag=tag,
                payload=payload,
                resume=lambda response: Effect.pure(decode(response)),
            )
        )

    @property
    def tag(self):
        return self._step.tag

    @property
    def payload(self):
        return self._step.payload

    @property
    def k(self):
        return self._step.resume

    def closed(self):
        return self._step.closed

    def step(self) -> EffectStep[A]:
        return self._step

    def bind(self, f: Callable[[A], Effect[B]]) -> Effect[B]:
        step = self._step
        if step.closed:
            return f(step.value)
        return Effect(
            EffectStep(
                False, tag=step.tag, payload=step.payload, resume=lambda x: step.resume(x).bind(f)
            )
        )

    def seq(self, other):
        return self.bind(lambda _: other)

    def fmap(self, f):
        return self.bind(lambda x: Effect.pure(f(x)))

    map = fmap

    def ap(self, other):
        return self.bind(lambda f: other.fmap(f))


def pure(value: B) -> Effect[B]:
    return Effect.pure(value)


def op(tag: str, payload: Any, decode: Callable[[Any], B]) -> Effect[B]:
    return Effect.op(tag, payload, decode)


perform = op


def fold(prog: Effect[A], on_return: Callable[[A], B], handlers: dict) -> B:
    while True:
        step = prog.step()
        if step.closed:
            return on_return(step.value)
        if step.tag not in handlers:
            raise KeyError(f"no handler for effect: {step.tag}")
        prog = step.resume(handlers[step.tag](step.payload))


def run(prog: Effect[A], handlers: dict) -> A:
    return fold(prog, lambda x: x, handlers)


async def await_maybe(value):
    return await value if isawaitable(value) else value


async def fold_async(prog: Effect[A], on_return: Callable, handlers: dict):
    while True:
        step = prog.step()
        if step.closed:
            return await await_maybe(on_return(step.value))
        if step.tag not in handlers:
            raise KeyError(f"no handler for effect: {step.tag}")
        prog = step.resume(await await_maybe(handlers[step.tag](step.payload)))


async def run_async(prog: Effect[A], handlers: dict) -> A:
    return await fold_async(prog, lambda x: x, handlers)


from .io import IOEffects, VirtualWorld, real_handlers  # noqa: E402,F401
