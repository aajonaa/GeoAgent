import importlib.util
from pathlib import Path

import pytest

from geological_agent.contracts import Message, ToolCall, ToolResult
from geological_agent.geology.validation import energy_claims, validate_energy_answer


spec = importlib.util.spec_from_file_location("table_format_oracles", Path(__file__).resolve().parents[1] / "scripts/local_agent_oracles.py")
oracles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracles)


def state(answer):
    return {"answer": answer, "messages": [
        Message("assistant", tool_calls=(ToolCall("e1", "GeoMagnitudeToEnergy", {"mw": 6.5}),)),
        ToolResult("e1", "GeoMagnitudeToEnergy", "ok", {"energy_j": 354813389233576.06}).message()]}


@pytest.mark.parametrize("row", [
    "| 354813389233576.06 | Joules |",
    "| 354,813,389,233,576.06 | joules |",
    "| 3.548e14 | J |",
    "| 3.548 x 10^14 | J |",
    "| 354.8 | TJ |",
    "| 3.548e14 | \u7126\u8033 |",
])
def test_adjacent_value_and_unit_cells_are_checked(row):
    answer = "| Energy | Unit |\n|---|---|\n" + row
    assert len(energy_claims(answer)) == 1
    assert not validate_energy_answer(state(answer))
    oracles.assert_energy_answer(answer)


@pytest.mark.parametrize("answer", [
    "| Energy | Unit |\n|---|---|\n| 3.548e17 | J |",
    "| 354.8 | GJ |",
    "| -3.548e14 | J |",
    "354813389233576.06 joules\n| 3.548e17 | J |",
    "| 354813389233576.06 | J |\n3.548e17 joules",
    "| 354813389233576.06 | J |\n| 3.548e17 | J |",
])
def test_wrong_scale_and_every_contradictory_table_claim_are_rejected(answer):
    assert validate_energy_answer(state(answer))
    with pytest.raises(AssertionError, match="contradicts"):
        oracles.assert_energy_answer(answer)


@pytest.mark.parametrize("answer", [
    "| 354813389233576.06 | unrelated column | J |",
    "354813389233576.06\n| J |",
    "| 354813389233576.06 |\n| J |",
])
def test_distant_column_or_next_row_cannot_supply_a_unit(answer):
    assert not energy_claims(answer)
    with pytest.raises(AssertionError, match="No explicit"):
        oracles.assert_energy_answer(answer)
