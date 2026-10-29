"""Berylx immutable workflows. Darkcore monads live in a separate namespace."""

from . import darkcore
from .adapters import Cray, CrayFailure, CraySuccess, attach_root, from_cray_result, to_cray_result
from .core import (
    BerylxError,
    ControlSignal,
    Err,
    Flow,
    Focus,
    Lay,
    Ok,
    Result,
    ResultOps,
    Root,
    State,
)
from .effect_tree import EffectTree, Perform
from .graph import Graph
from .merge import Merge
from .nodes import (
    AsyncTask,
    Branch,
    Catch,
    Else,
    Node,
    Parallel,
    Rescue,
    RescueBlock,
    Sequence,
    Task,
    When,
    Workflow,
)
from .timeline import (
    ExecutablePlan,
    KeyframeTrack,
    Observation,
    TaskRef,
    Timeline,
    TimelineError,
    TimelineEvent,
)
from .timeline import predicates as timeline_predicates
from .timeline_berylx import (
    BERYLX_HUMAN_LOGIN,
    BerylxTimeline,
    BerylxTimelinePlan,
    wait_for_human_login,
)

VERSION = __version__ = "0.1.0"
Darkcore = darkcore
run = EffectTree.run
task = Task.of


class Berylx:
    task = staticmethod(Task.of)
    async_task = staticmethod(AsyncTask.of)
    when = staticmethod(When.of)
    catch = staticmethod(Catch.of)
    focus = lay = staticmethod(Focus.of)
    flow = staticmethod(Flow.of)
    root = staticmethod(Root.of)
    state = staticmethod(State.of)


def berylx():
    return Berylx()


__all__ = [
    "Focus",
    "Lay",
    "Root",
    "Flow",
    "State",
    "Ok",
    "Err",
    "Result",
    "ResultOps",
    "BerylxError",
    "ControlSignal",
    "Node",
    "Task",
    "AsyncTask",
    "Sequence",
    "Parallel",
    "When",
    "Else",
    "Branch",
    "Catch",
    "Rescue",
    "RescueBlock",
    "Workflow",
    "Merge",
    "EffectTree",
    "Perform",
    "darkcore",
    "Darkcore",
    "Graph",
    "attach_root",
    "Cray",
    "CraySuccess",
    "CrayFailure",
    "from_cray_result",
    "to_cray_result",
    "berylx",
    "Berylx",
    "VERSION",
    "run",
    "task",
]

__all__ += [
    "Timeline",
    "ExecutablePlan",
    "KeyframeTrack",
    "TimelineError",
    "TaskRef",
    "TimelineEvent",
    "Observation",
    "timeline_predicates",
    "BerylxTimeline",
    "BerylxTimelinePlan",
    "BERYLX_HUMAN_LOGIN",
    "wait_for_human_login",
]
