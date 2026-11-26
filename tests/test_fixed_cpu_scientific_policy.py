"""Fixed worker CPU policy cannot be supplied by operation arguments or caller env."""
import contextvars
import os
from types import SimpleNamespace

import pytest

from geological_agent.geology import isolated_cpu_worker_v2 as worker

BINDINGS = dict(worker._REMOTE_CPU_BINDINGS,
                **{name: (entrypoint, "geology") for name, entrypoint in worker._GEOLOGY_CPU_BINDINGS.items()})


def checked(condition, message, code=None):
    if not condition:
        raise ValueError(message)


def fixture(tool):
    entrypoint, family = BINDINGS[tool]
    profile = {
        "tool": tool,
        "module": "geological_agent.geology.expansion501_" + ("geology" if family == "geology" else "remote"),
        "callable": entrypoint,
        "projects": {"OTB": {"version": "9.1.1", "root": "/private/reviewed/otb"}},
    }
    bridge = SimpleNamespace(CHILD=contextvars.ContextVar("child"), need=checked)
    bridge.CHILD.set({"pid": os.getpid(), "profile": profile, "tool": tool})
    return bridge, profile, "expansion501-" + tool.lower() + "-cpu-v2", family


@pytest.mark.parametrize("tool", sorted(BINDINGS))
def test_fixed_cpu_environment_and_restoration(tool, monkeypatch):
    bridge, profile, identifier, family = fixture(tool)
    key, expected = {
        "mintpy": ("EXPANSION501_REMOTE_PROFILE", "mintpy-1.6.4-cpu"),
        "otb": ("EXPANSION501_OTB_ROOT", "/private/reviewed/otb"),
        "geology": ("GEOAGENT_EXPANSION501_GEOLOGY_CPU", "expansion501-geology-cpu-v1"),
    }[family]
    monkeypatch.setenv(key, "untrusted-caller-value")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    with pytest.raises(RuntimeError, match="operation failed"):
        with worker._scientific_cpu_policy(bridge, profile, identifier):
            assert os.environ[key] == expected
            assert os.environ["CUDA_VISIBLE_DEVICES"] == ""
            raise RuntimeError("operation failed")
    assert os.environ[key] == "untrusted-caller-value"
    monkeypatch.delenv(key)
    with worker._scientific_cpu_policy(bridge, profile, identifier):
        assert os.environ[key] == expected
    assert key not in os.environ


@pytest.mark.parametrize("tool", sorted(BINDINGS))
@pytest.mark.parametrize("field", ["profile_id", "module", "callable"])
def test_wrong_binding_rejected(tool, field):
    bridge, profile, identifier, _ = fixture(tool)
    if field == "profile_id":
        identifier = "another-profile"
    else:
        profile[field] = "another-entrypoint"
    with pytest.raises(ValueError, match="reviewed fixed CPU"):
        with worker._scientific_cpu_policy(bridge, profile, identifier):
            pytest.fail("wrong binding was accepted")


@pytest.mark.parametrize("change", ["absent", "pid", "tool", "profile"])
def test_untrusted_child_context_rejected(change):
    bridge, profile, identifier, _ = fixture("GeoInSARResidualDEM")
    context = dict(bridge.CHILD.get())
    if change == "absent":
        context = None
    elif change == "pid":
        context["pid"] = os.getpid() + 1
    elif change == "tool":
        context["tool"] = "AnotherTool"
    else:
        context["profile"] = dict(profile)
    bridge.CHILD.set(context)
    with pytest.raises(ValueError, match="trusted child context"):
        with worker._scientific_cpu_policy(bridge, profile, identifier):
            pytest.fail("untrusted context was accepted")


@pytest.mark.parametrize("native", [None, {}, {"version": "9.1.1", "root": "relative"},
                                    {"version": "0.0", "root": "/unreviewed"}])
def test_otb_policy_requires_verified_root(native):
    bridge, profile, identifier, _ = fixture("GeoRemoteTOAReflectance")
    profile["projects"] = {"OTB": native}
    with pytest.raises(ValueError, match="verified native project root"):
        with worker._scientific_cpu_policy(bridge, profile, identifier):
            pytest.fail("invalid project was accepted")
