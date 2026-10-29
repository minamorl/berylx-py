"""Explicit real and deterministic virtual IO interpreters."""

import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import op


def decode(kind):
    def check(value):
        valid = value is None if kind is None else type(value) is kind
        if kind == "optional":
            valid = value is None or isinstance(value, str)
        if kind == "strings":
            valid = isinstance(value, list) and all(isinstance(x, str) for x in value)
        if kind == "number":
            valid = type(value) in (int, float)
        if not valid:
            raise TypeError(f"effect handler must return {kind}")
        return value

    return check


def pair(value):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(x, str) for x in value)
    ):
        raise TypeError("effect payload must be a [string, string] tuple")
    return value


class IOEffects:
    say = staticmethod(lambda msg: op("say", msg, decode(None)))
    warn = staticmethod(lambda msg: op("warn", msg, decode(None)))
    ask = staticmethod(lambda prompt=None: op("ask", prompt, decode("optional")))
    read = staticmethod(lambda path: op("read", path, decode(str)))
    write = staticmethod(lambda path, data: op("write", (path, data), decode(None)))
    append = staticmethod(lambda path, data: op("append", (path, data), decode(None)))
    delete = staticmethod(lambda path: op("delete", path, decode(None)))
    exists = staticmethod(lambda path: op("exists", path, decode(bool)))
    list_dir = staticmethod(lambda path: op("list_dir", path, decode("strings")))
    getenv = staticmethod(lambda key: op("getenv", key, decode("optional")))
    now = staticmethod(lambda: op("now", None, lambda x: x))
    rand = staticmethod(lambda n: op("rand", n, decode("number")))
    shell = staticmethod(lambda cmd: op("shell", cmd, decode(str)))


def real_handlers():
    def write(payload, mode):
        path, data = pair(payload)
        with open(path, mode, encoding="utf-8", newline="") as stream:
            stream.write(data)

    def read(path):
        with open(str(path), encoding="utf-8", newline="") as stream:
            return stream.read()

    def ask(prompt):
        if prompt is not None:
            print(prompt, end="", flush=True)
        return sys.stdin.readline().rstrip("\n")

    return {
        "say": lambda m: print(m),
        "warn": lambda m: print(m, file=sys.stderr),
        "ask": ask,
        "read": read,
        "write": lambda pd: write(pd, "w"),
        "append": lambda pd: write(pd, "a"),
        "delete": lambda p: Path(str(p)).unlink(missing_ok=True),
        "exists": lambda p: Path(str(p)).exists(),
        "list_dir": lambda p: os.listdir(str(p)),
        "getenv": lambda k: os.environ.get(str(k)),
        "now": lambda _: datetime.now(timezone.utc),
        "rand": lambda n: int(random.random() * n),
        "shell": lambda cmd: subprocess.check_output(str(cmd), shell=True, text=True),
    }


class VirtualWorld:
    def __init__(self, *, files=None, inputs=None, env=None, now=None, rand_seq=None, shell=None):
        self.fs = dict(files or {})
        self.inputs = list(inputs or [])
        self.env = dict(env or {})
        self.now_value = now
        self.rand_seq = list(rand_seq if rand_seq is not None else [0])
        self.shell_table = dict(shell or {})
        self.outputs = []
        self.warnings = []
        self.log = []
        self._rand_i = 0

    def handlers(self):
        def say(m):
            self.outputs.append(m)
            self.log.append(("say", m))

        def warn(m):
            self.warnings.append(m)
            self.log.append(("warn", m))

        def ask(p):
            self.log.append(("ask", p))
            return self.inputs.pop(0) if self.inputs else None

        def read(p):
            self.log.append(("read", p))
            if str(p) not in self.fs:
                raise FileNotFoundError(f"vfs: no such file {p}")
            return self.fs[str(p)]

        def write(pd, append=False):
            p, data = pair(pd)
            self.fs[p] = (self.fs.get(p, "") if append else "") + data
            self.log.append(("append" if append else "write", p))

        def delete(p):
            self.fs.pop(str(p), None)
            self.log.append(("delete", p))

        def rand(n):
            value = self.rand_seq[self._rand_i % len(self.rand_seq)]
            self._rand_i += 1
            return value % n

        def shell(cmd):
            self.log.append(("shell", cmd))
            return self.shell_table.get(str(cmd), "")

        return {
            "say": say,
            "warn": warn,
            "ask": ask,
            "read": read,
            "write": write,
            "append": lambda pd: write(pd, True),
            "delete": delete,
            "exists": lambda p: str(p) in self.fs,
            "list_dir": lambda p: [
                k[len(str(p)) + 1 :] for k in self.fs if k.startswith(str(p) + "/")
            ],
            "getenv": lambda k: self.env.get(str(k)),
            "now": lambda _: self.now_value,
            "rand": rand,
            "shell": shell,
        }
