"""Category index derived from the executable canonical source catalog."""
from .source_contracts import catalog

TOOLS_MAPPING = {}
for _tool in catalog()["tools"]:
    TOOLS_MAPPING.setdefault(_tool["category"], []).append(_tool["id"])
