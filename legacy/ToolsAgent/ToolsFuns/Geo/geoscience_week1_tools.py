"""
Week 1 地学软件占位工具（来源：2-Week1.docx）。

每个工具在本地尝试 import 对应 Python 包；未安装时返回 pip 安装说明与文档链接。
已安装时返回简短确认与使用提示（不在此实现完整反演/可视化流水线）。
"""

from __future__ import annotations

import importlib
import textwrap
from typing import Callable, Dict, List, Optional

# (工具显示名, pip 包名或逗号分隔候选, 一句话说明, 文档 URL)
_WEEK1_SPECS: List[tuple] = [
    ("ObsPy数据获取", "obspy", "从数据中心或本地读取地震波形/元数据（Retrieving / Reading）", "https://docs.obspy.org/"),
    ("ObsPy波形可视化", "obspy", "波形绘图教程（Waveform Plotting）", "https://docs.obspy.org/tutorial/code_snippets/waveform_plotting_tutorial.html"),
    ("ObsPy数据预处理", "obspy", "滤波、下采样、合并、包络、仪器仿真等预处理", "https://docs.obspy.org/tutorial/code_snippets/filtering_seismograms.html"),
    ("ObsPy震相拾取", "obspy", "Trigger / Picker 教程", "https://docs.obspy.org/tutorial/code_snippets/trigger_tutorial.html"),
    ("Pyrocko地震定位", "pyrocko", "地震定位相关工作流", "https://pyrocko.org/"),
    ("ObsPy震级计算", "obspy", "震级计算相关处理", "https://docs.obspy.org/"),
    ("SKHASH震源机制反演", "skhash", "震源机制（沙滩球）反演工具 SKHASH", "https://github.com/michaelcee/skhash"),
    ("PyGMT地震成果制图", "pygmt", "PyGMT 地震成果可视化", "https://www.pygmt.org/"),
    ("surfQuake集成地震处理", "surfquake", "可替代 ObsPy 多步的集成工具 surfQuake（若已安装）", "https://pypi.org/project/surfquake/"),
    ("SeisBench深度学习震相", "seisbench", "深度学习震相拾取 SeisBench", "https://github.com/seisbench/seisbench"),
    ("EQTransformer深度学习震相", "eqtransformer", "EQTransformer 震相拾取（生态包名可能变化，以实际为准）", "https://github.com/smousavi/DeepLearningPhases"),
    ("QuakeMigrate地震成像", "quakemigrate", "QuakeMigrate 连续地震成像", "https://github.com/QuakeMigrate/QuakeMigrate"),
    ("Qseek地震成像", "qseek", "Qseek 相关成像/检测工作流", "https://pypi.org/search/?q=qseek"),
    ("SAIPy震相与震级", "saipy", "SAIPy：震相拾取 + 震级（以项目文档为准）", "https://pypi.org/search/?q=saipy"),
    ("ObsPy地震数据格式转换", "obspy", "导出 MATLAB/ASCII、转 MiniSEED 等", "https://docs.obspy.org/tutorial/code_snippets/exporting_seismograms.html"),
    ("Pooch与Verde数据网格化", "pooch,verde", "Pooch 获取数据 + Verde 网格化（Fatiando 生态）", "https://www.fatiando.org/verde/latest/"),
    ("Boule标准重力与正常位", "boule", "标准地球重力位 / 正常重力（Fatiando）", "https://www.fatiando.org/boule/latest/"),
    ("Harmonica布格与区域改正", "harmonica", "布格校正、区域改正等（Harmonica）", "https://www.fatiando.org/harmonica/latest/"),
    ("Harmonica重磁正演", "harmonica", "重磁正演得到理论异常", "https://www.fatiando.org/harmonica/latest/"),
    ("pyGIMLi地球物理反演", "pygimli", "pyGIMLi 反演地下物性", "https://www.pygimli.org/"),
    ("SimPEG地球物理反演", "simpeg", "SimPEG 反演框架", "https://simpeg.xyz/"),
    ("pyGMI重磁集成处理", "pygmi", "pyGMI 集成重磁处理（可替代多步）", "https://github.com/geomodels/pygmi"),
    ("PyGMT重磁成果制图", "pygmt", "PyGMT 重磁成果可视化", "https://www.pygmt.org/"),
    ("Pymaginverse卫星磁反演", "pymaginverse", "深度学习/卫星磁反演相关（以实际发行包为准）", "https://pypi.org/search/?q=pymaginverse"),
    ("MasconCubes卫星磁反演", "masconcubes", "MasconCubes 相关反演（以实际发行包为准）", "https://pypi.org/search/?q=masconcubes"),
    ("PyGMI大地电磁一维反演", "pygmi", "PyGMI 用于 MT 一维反演（文档说明）", "https://github.com/geomodels/pygmi"),
    ("PyGMT专业地学制图", "pygmt", "专业地图、图例、剖面、等值线、3D、沙滩球等", "https://www.pygmt.org/"),
    ("CIGVis地震测井可视化", "cigvis", "CIGVis：地震、测井等数据可视化", "https://pypi.org/search/?q=cigvis"),
    ("GemPy三维地质建模", "gempy", "GemPy 三维地质结构建模", "https://www.gempy.org/"),
    (
        "GSTool模型不确定性分析",
        "gstools",
        "Week1 文档中的 GSTool（量化不确定性与模型补全）。若与 Python 包 `gstools` 不同，请按课题/厂商提供的安装方式配置。",
        "https://geostat-framework.readthedocs.io/projects/gstools/en/stable/",
    ),
]


def _try_import(module_candidates: str) -> Optional[str]:
    for raw in module_candidates.split(","):
        mod = raw.strip()
        if not mod:
            continue
        try:
            importlib.import_module(mod)
            return mod
        except ImportError:
            continue
    return None


def _stub_for_spec(name: str, pip: str, summary: str, doc_url: str) -> Callable[[str], str]:
    def _fn(input_text: str) -> str:
        installed = _try_import(pip) if (pip or "").strip() else None
        pip_hint = pip.replace(",", " ").strip()
        body = textwrap.dedent(
            f"""
            ## {name}

            **Week1 文档定位**：固体地球物理 / 地震-重磁-电法-建模与可视化流程中的软件节点。

            **能力摘要**：{summary}

            **参考文档**：{doc_url}

            **用户输入**：`{(input_text or '').strip() or '(empty)'}`

            **说明**：本条目在 GeoToolAgent 中为「可编排占位工具」。完整反演/绘图流水线请在独立 Python 环境或 Jupyter 中按官方教程执行。
            """
        ).strip()

        if installed:
            return body + f"\n\n**环境**：已检测到可 import 的模块 `{installed}`。\n"
        if not pip_hint:
            return body + "\n\n**环境**：请在本地按软件官方说明安装后再调用本工具。\n"
        return (
            body
            + f"\n\n**环境**：未检测到 `{pip_hint}` 对应模块，可先尝试：\n\n```bash\npip install {pip_hint.split()[0]}\n```\n"
        )

    _fn.__name__ = name
    return _fn


def _build_week1_tools() -> Dict[str, Callable[[str], str]]:
    out: Dict[str, Callable[[str], str]] = {}
    for name, pip, summary, doc in _WEEK1_SPECS:
        out[name] = _stub_for_spec(name, pip, summary, doc)
    return out


GEO_WEEK1_TOOLS = _build_week1_tools()

# 供 scripts/build_geo_week1_kg_xlsx.py 生成 KG Excel（与 create_triplets 列一致）
WEEK1_KG_ROWS: List[dict] = [
    {
        "Name": name,
        "Category": "GeoTools",
        "Function": f"Week1 文档节点：{summary}。参考：{doc}",
        "Input": f"{name}输入参数",
        "Output": f"{name}输出结果",
        "Source": "ToolsAgent/ToolsFuns/Geo/geoscience_week1_tools.py",
        "Safety": "Yes",
    }
    for name, _pip, summary, doc in _WEEK1_SPECS
]
