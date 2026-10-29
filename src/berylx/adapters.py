"""Root subscriptions and structural Cray result interoperability."""

from dataclasses import dataclass
from typing import Any

from .core import MISSING, BerylxError, Err, Ok, ResultOps


def attach_root(
    root, listener, *, select=lambda x: x, skip_snapshot=False, on_snapshot=None, on_commit=None
):
    from .nodes import invoke

    def receive(event):
        value = select(event["value"])
        if event["type"] == "snapshot":
            if skip_snapshot:
                return
            callback = on_snapshot
        else:
            callback = on_commit
        if callback:
            invoke(callback, value, event)
        invoke(listener, value, event)

    return root.subscribe(receive)


@dataclass(frozen=True)
class CraySuccess:
    value: object

    def is_success(self):
        return True

    def is_failure(self):
        return False


@dataclass(frozen=True)
class CrayFailure:
    error: object

    def is_success(self):
        return False

    def is_failure(self):
        return True


class Cray:
    success = CraySuccess
    failure = CrayFailure


def from_cray_result(result, focus=MISSING):
    get: Any = (
        result.get
        if isinstance(result, dict)
        else lambda key, default=None: getattr(result, key, default)
    )
    succeeded = False
    if callable(get("is_success")):
        succeeded = bool(get("is_success")())
    elif callable(get("is_failure")):
        succeeded = not get("is_failure")()
    else:
        for key in ("success", "ok", "tag"):
            flag = get(key, MISSING)
            if flag is not MISSING:
                succeeded = flag in ("success", "ok", "right") if key == "tag" else bool(flag)
                break
        else:
            succeeded = get("value", MISSING) is not MISSING and get("error", MISSING) is MISSING
    if succeeded:
        value = get("value", MISSING)
        return ResultOps.ok(({} if focus is MISSING else focus) if value is MISSING else value)
    focus = {} if focus is MISSING or focus is None else focus
    error = get("error")
    if isinstance(error, BerylxError):
        return Err(ResultOps.coerce_focus(focus), error)
    if isinstance(error, Exception):
        return ResultOps.err(
            focus, type(error).__name__, str(error), cause=error, metadata={"crayError": error}
        )
    if isinstance(error, str):
        return ResultOps.err(focus, error, metadata={"crayError": error})
    return ResultOps.err(focus, "cray_failure", "cray failure", metadata={"crayError": error})


def to_cray_result(result):
    return (
        CraySuccess(result.focus.to_object())
        if isinstance(result, Ok)
        else CrayFailure(result.error)
    )
