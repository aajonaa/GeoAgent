from pathlib import Path
import runpy

def test_frozen_shared_fixture_and_real_native_executor():
    runpy.run_path(str(Path(__file__).parent / "shared-fixture-script.py"), run_name="__main__")
