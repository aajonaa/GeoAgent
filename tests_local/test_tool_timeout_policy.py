"""No default execution deadline; explicit deadlines and cancellation still work."""
from dataclasses import replace
from threading import Event

import pytest

from geological_agent.contracts import ToolCall
from geological_agent.settings import Settings
from geological_agent.tools import (
    Tool, ToolDefinition, ToolExecutionContext, ToolExecutor, ToolOutput,
    ToolRegistry, object_schema,
)


def execute(work, settings, handler, *, cancel=None, deadline=float("inf")):
    registry = ToolRegistry()
    registry.register(Tool(ToolDefinition(
        "work", "Execution deadline fixture", "Exercise registered execution",
        object_schema({}), object_schema({"done": {"type": "boolean"}}, ["done"])),
        handler))
    context = ToolExecutionContext("fixture", work, registry.names(), settings,
                                   cancel if cancel is not None else Event(), deadline=deadline)
    return ToolExecutor(registry).execute(ToolCall("work-1", "work", {}), context)


def test_default_work_can_cross_the_former_sixty_second_limit(tmp_path, monkeypatch):
    from geological_agent import tools
    clock = [100.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])

    def handler(args, ctx):
        assert ctx.deadline == float("inf")
        clock[0] += 133.0
        ctx.check()
        return ToolOutput({"done": True})

    assert Settings().tool_timeout_seconds == 0
    result = execute(tmp_path, Settings(), handler)
    assert result.status == "ok"
    assert result.data == {"done": True}


def test_explicit_positive_timeout_remains_effective(tmp_path, monkeypatch):
    from geological_agent import tools
    clock = [100.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])

    def handler(args, ctx):
        assert ctx.deadline == 100.2
        clock[0] += 1.0
        ctx.check()
        pytest.fail("Expired tool must not return success")

    result = execute(tmp_path, replace(Settings(), tool_timeout_seconds=0.2), handler)
    assert result.status == "timeout"
    assert result.error.code == "tool_timeout"
    assert result.error.outcome_unknown


def test_explicit_parent_deadline_is_not_discarded(tmp_path, monkeypatch):
    from geological_agent import tools
    clock = [100.0]
    monkeypatch.setattr(tools.time, "monotonic", lambda: clock[0])

    def handler(args, ctx):
        assert ctx.deadline == 100.5
        clock[0] += 1.0
        ctx.check()
        pytest.fail("Explicit parent deadline must still apply")

    result = execute(tmp_path, Settings(), handler, deadline=100.5)
    assert result.status == "timeout"


def test_unlimited_tool_can_still_be_cancelled(tmp_path):
    cancel = Event()

    def handler(args, ctx):
        cancel.set()
        ctx.check()
        pytest.fail("Cancelled tool must not return success")

    result = execute(tmp_path, Settings(), handler, cancel=cancel)
    assert result.status == "cancelled"
    assert result.error.code == "cancelled"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), -float("inf"), True, "0", None])
def test_invalid_timeout_configuration_is_rejected(bad):
    with pytest.raises(ValueError, match="tool_timeout_seconds"):
        Settings(tool_timeout_seconds=bad)
