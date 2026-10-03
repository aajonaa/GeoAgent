"""Independent acceptance oracles; not imported by the runtime validators."""
from decimal import Decimal
import hashlib
import json
import math
import re


def assert_executed_cases(observations, workspace, filename, function, cases):
    """Independent audit of agent executions, not the oracle's own test run.

    Require actual current-file calls with the specified scalar arguments and
    returns, linked to an assertion that completed without an exception. This
    is execution evidence, not a proof that an arbitrary assertion is adequate.
    The separate numerical oracle must still check the repaired implementation.
    """
    current = hashlib.sha256((workspace / filename).read_bytes()).hexdigest()
    matched = set()
    for observation in observations:
        data = observation.get("data", {})
        if observation.get("name") != "execute_python" or observation.get("status") != "ok" or not data.get("execution_record_complete"):
            continue
        relative = data.get("execution_trace_path")
        if not isinstance(relative, str):
            continue
        path = (workspace / relative).resolve()
        assert path.is_relative_to(workspace.resolve()), "Trace path escapes workspace"
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == data.get("execution_trace_sha256"), "Execution trace hash mismatch"
        events = [json.loads(line) for line in raw.splitlines()]
        checked = {call_id for event in events if event.get("event") == "assertion"
                   and event.get("status") == "completed_without_exception" for call_id in event["function_call_ids"]}
        calls = {event["sequence"]: event for event in events if event.get("event") == "function_call"
                 and event.get("path") == filename and event.get("sha256") == current and event.get("function") == function}
        for event in events:
            if event.get("event") != "function_return" or event.get("status") != "returned" or event.get("call_id") not in checked:
                continue
            call = calls.get(event["call_id"])
            if call is None:
                continue
            for index, (arguments, expected) in enumerate(cases):
                value = event.get("value")
                if call["arguments"] == arguments and type(value) in (int, float) and math.isclose(value, expected, rel_tol=1e-10, abs_tol=1e-12):
                    matched.add(index)
    assert matched == set(range(len(cases))), "Agent execution did not establish the requested current-file checked cases: " + str(sorted(set(range(len(cases))) - matched))


def assert_rounded_number(text, expected):
    observed = Decimal(text.replace(",", ""))
    reference = Decimal(str(expected))
    assert observed.is_finite() and reference.is_finite(), "Non-finite numerical claim"
    rounding = Decimal("0.5").scaleb(observed.as_tuple().exponent)
    assert abs(observed - reference) <= rounding + abs(reference) * Decimal("1e-12"), f"Inconsistent value: {text}; expected {reference}"


def assert_energy_answer(answer, mw=6.5):
    """Check EVERY explicit energy claim, not just one correct number nearby."""
    expected = Decimal(10) ** (Decimal("1.5") * Decimal(str(mw)) + Decimal("4.8"))
    clean = re.sub(r"\\(?:text|mathrm)\{([^}]*)\}", r"\1", answer)
    clean = clean.replace("\\times", "x").replace("\\cdot", "*")
    clean = re.sub(r"\\[()\[\],!]", "", clean).translate(str.maketrans("", "", "{}$"))
    pattern = re.compile(r"(?<![A-Za-z0-9_.,])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:[eE]([+-]?\d+)|\s*[xX*\u00d7\u00b7]\s*10\s*\^\s*([+-]?\d+))?(?:[ \t]*\|[ \t]*|\s*)([kMGT]?J(?![A-Za-z])|(?i:joules?)(?![A-Za-z])|\u7126\u8033)")
    found = list(pattern.finditer(clean))
    assert found, "No explicit numerical energy claim with a supported unit"
    for match in found:
        power = int(match[2] or match[3] or 0) + {"kJ": 3, "MJ": 6, "GJ": 9, "TJ": 12}.get(match[4], 0)
        mantissa = Decimal(match[1].replace(",", ""))
        observed = mantissa.scaleb(power)
        assert observed.is_finite(), "Non-finite energy claim"
        precision = Decimal("0.5").scaleb(mantissa.as_tuple().exponent + power)
        assert abs(observed - expected) <= precision + abs(expected) * Decimal("1e-12"), f"Energy answer contradicts calculation: {match.group()}"


def assert_table_answer(answer):
    """Independent golden-fixture check of all recognized answer claims."""
    expected = {"total_ore_tonnes": Decimal(380), "total_metal_tonnes": Decimal("4.4"),
                "weighted_grade_pct": Decimal("4.4") / Decimal(380) * Decimal(100)}
    number = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
    found = set()
    for block in re.finditer(r"```json\s*\n(.*?)```", answer, re.DOTALL | re.IGNORECASE):
        data = json.loads(block[1])
        if not isinstance(data, dict):
            continue
        for key, value in expected.items():
            if key in data:
                assert not isinstance(data[key], bool), "Boolean masquerading as a numeric result"
                assert_rounded_number(str(data[key]), value)
                found.add(key)
        if "valid_count" in data:
            assert data["valid_count"] == 3
        if "rejected_ids" in data:
            assert set(data["rejected_ids"]) == {"C", "D"}
    patterns = {
        "total_ore_tonnes": [r"Total ore(?:\s*\(t\))?\s*[:=|]\s*(?P<n>" + number + r")",
                             r"(?P<n>" + number + r")\s*(?:tonnes|tons|t)\s+of\s+ore\b"],
        "total_metal_tonnes": [r"Theoretical metal(?:\s*\(t\))?\s*[:=|]\s*(?P<n>" + number + r")",
                               r"(?P<n>" + number + r")\s*(?:tonnes|tons|t)\s+of\s+(?:theoretical\s+|contained\s+)?metal\b"],
        "weighted_grade_pct": [r"Weighted(?:\s+average)?\s+grade(?:\s*\(%\))?\s*(?::|=|\||of|is)\s*(?P<n>" + number + r")"],
    }
    clean = answer.replace("**", "").replace("`", "")
    for key, choices in patterns.items():
        for pattern in choices:
            for match in re.finditer(pattern, clean, re.IGNORECASE):
                assert_rounded_number(match["n"], expected[key])
                found.add(key)
    assert found == set(expected), "Final answer omits verifiable summary quantities: " + str(set(expected) - found)
    assert "summary.json" in answer and "report.md" in answer, "Missing actual output filenames"
