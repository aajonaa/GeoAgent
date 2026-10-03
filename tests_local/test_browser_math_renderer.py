import pathlib,shutil,subprocess
import pytest
import geological_agent
def test_browser_math_renderer():
    node=shutil.which("node")
    if not node: pytest.skip("Node is not installed; renderer is tested on the browser host")
    app=pathlib.Path(geological_agent.__file__).parent/"team"/"web"/"app.js"
    script=pathlib.Path(__file__).with_name("math-rendering-regression.js")
    result=subprocess.run([node,str(script),str(app)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
