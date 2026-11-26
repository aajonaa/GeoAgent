"""Preserve nonempty code validation without the deployed decoder's newline bug."""
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from geological_agent.tools import register_file_tools


@pytest.fixture
def python_schema():
    registered = []
    register_file_tools(SimpleNamespace(register=registered.append))
    return next(tool.definition.input_schema for tool in registered
                if tool.definition.name == "execute_python")


@pytest.mark.parametrize("code", [
    "", " ", "\n", "\r\n", "\t", "x", "x\n", "\u2028", "\u4e2d",
    "def value():\n    return 55\n\nprint(value())\n",
    "def value():\r\n    return 55\r\n\r\nprint(value())\r\n",
    None, 0, [], {}, True,
])
def test_code_constraint_is_equivalent_to_nonempty_string(python_schema, code):
    original = Draft202012Validator({"type": "string", "minLength": 1})
    replacement = Draft202012Validator(python_schema["properties"]["code"])
    assert replacement.is_valid(code) == original.is_valid(code)


def test_model_facing_schema_uses_full_multiline_pattern(python_schema):
    code = python_schema["properties"]["code"]
    assert "minLength" not in code
    assert code["pattern"] == r"^[\s\S]+$"
    assert code["description"]
    validator = Draft202012Validator(python_schema)
    for arguments in ({}, {"code": ""}, {"code": "pass", "unexpected": True}):
        with pytest.raises(ValidationError):
            validator.validate(arguments)


def test_native_json_roundtrip_preserves_executable_multiline_code(python_schema):
    source = "def value():\n    return 55\n\nassert value() == 55\nresult = value()\n"
    arguments = json.loads(json.dumps({"code": source}))
    Draft202012Validator(python_schema).validate(arguments)
    assert arguments["code"] == source
    namespace = {}
    exec(compile(arguments["code"], "model_program.py", "exec"), namespace)
    assert namespace["result"] == 55
