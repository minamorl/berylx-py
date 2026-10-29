"""Upstream strict three-way join and explicit two-way reducers."""

from collections.abc import Mapping

from .core import MISSING, BerylxError, Focus, FrozenList


def equal(a, b):
    if a is b:
        return True
    if a is MISSING or b is MISSING:
        return False
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple, FrozenList)) and isinstance(b, (list, tuple, FrozenList)):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def as_object(x):
    return x if isinstance(x, Mapping) else {}


def deep_merge(left, right):
    out = dict(left)
    for key, value in right.items():
        out[key] = (
            deep_merge(left[key], value)
            if key in left and isinstance(left[key], Mapping) and isinstance(value, Mapping)
            else value
        )
    return out


def strict_merge(left, right, base=None, path=()):
    base = {} if base is None else base
    out = {}
    for key in dict.fromkeys([*left, *right, *base]):
        a, b, c = left.get(key, MISSING), right.get(key, MISSING), base.get(key, MISSING)
        where = (*path, key)
        if b is MISSING:
            out[key] = a
        elif a is MISSING:
            out[key] = b
        elif (
            isinstance(a, Mapping)
            and isinstance(b, Mapping)
            and (isinstance(c, Mapping) or c is MISSING)
        ):
            out[key] = strict_merge(a, b, {} if c is MISSING else c, where)
        elif equal(b, c):
            out[key] = a
        elif equal(a, c):
            out[key] = b
        elif equal(a, b):
            out[key] = a
        else:
            raise BerylxError(
                "merge_conflict",
                f"merge conflict at {'.'.join(map(str, where))}",
                metadata={
                    "path": list(where),
                    "left": a,
                    "right": b,
                    "base": None if c is MISSING else c,
                },
            )
    return out


class Merge:
    deep_merge = staticmethod(deep_merge)
    strict_merge = staticmethod(strict_merge)

    @staticmethod
    def keep_left():
        return lambda left, right: left

    @staticmethod
    def keep_right():
        return lambda left, right: right

    @staticmethod
    def deep():
        return lambda left, right: Focus.of(
            deep_merge(as_object(left.to_object()), as_object(right.to_object()))
        )

    @staticmethod
    def strict():
        return lambda left, right, base: Focus.of(
            strict_merge(
                as_object(left.to_object()),
                as_object(right.to_object()),
                as_object(base.to_object()),
            )
        )
