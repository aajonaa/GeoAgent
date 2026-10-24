from .wflow43_fixture_source import prepare

def create(root):
    examples = prepare(root)
    return {"files": [str(root / "assets/earth-collection/wflow43/synthetic-si-example.json")], "examples": examples}
