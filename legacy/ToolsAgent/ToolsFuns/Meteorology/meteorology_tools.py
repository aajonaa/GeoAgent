"""Meteorology tools added in the SciToolAgent tool-function style."""

from __future__ import annotations

from ToolsFuns.utils.workflow_tool_runtime import (
    WorkflowToolSpec,
    build_kg_rows,
    run_workflow_tool,
    tool_names,
)


METEOROLOGY_CATEGORY = "MeteorologyTools"
METEOROLOGY_SOURCE = (
    "PPT: 工具(1).pptx / 气象学; "
    "ToolsAgent/ToolsFuns/Meteorology/meteorology_tools.py"
)


METEOROLOGY_SPECS: list[WorkflowToolSpec] = [
    {
        "name": "气象数据读取与格式解码",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-数据读取",
        "function": "解析 GRIB2、NetCDF、BUFR 等专业气象数据并转换为结构化数据。",
        "workflow": "文件识别 -> 数据读取 -> 变量提取 -> 维度标准化 -> 格式输出",
        "common_tools": ["xarray", "cfgrib", "netCDF4", "MetPy", "pybufr-ecmwf"],
        "import_modules": ["xarray", "cfgrib", "netCDF4", "metpy", "pybufr_ecmwf|pybufrkit"],
        "input": "气象文件路径,变量名,目标格式",
        "output": "结构化气象数据,格点气象数据",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象数据质量控制", "气象要素空间制图", "风场分析与可视化", "气象垂直剖面分析"],
    },
    {
        "name": "气象数据质量控制",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-质量控制",
        "function": "剔除缺测和异常值，执行时空一致性检查，保证气象数据准确性。",
        "workflow": "数据读取 -> 缺测处理 -> 异常检测 -> 时空一致性检查 -> 清洗输出",
        "common_tools": ["pandas", "numpy", "xarray", "MetPy"],
        "import_modules": ["pandas", "numpy", "xarray", "metpy"],
        "input": "结构化气象数据,缺测规则,异常阈值",
        "output": "清洗气象数据",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素时空插值", "气象时间序列统计分析", "气象衍生量计算", "降水数据处理与极端事件识别"],
    },
    {
        "name": "气象要素时空插值",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-空间插值",
        "function": "完成站点到格点、格点到站点的气象要素插值和空间匹配。",
        "workflow": "源数据读取 -> 目标坐标 -> 插值计算 -> 结果输出",
        "common_tools": ["SciPy", "PyKrige", "xarray", "MetPy"],
        "import_modules": ["scipy", "pykrige", "xarray", "metpy"],
        "input": "清洗气象数据,目标坐标,插值方法",
        "output": "插值气象数据,格点气象数据",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素空间制图", "气象站点数据空间可视化", "风场分析与可视化"],
    },
    {
        "name": "气象时间序列统计分析",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-统计分析",
        "function": "计算气象日、月、年均值、极值、趋势和距平。",
        "workflow": "时序读取 -> 时间标准化 -> 分组统计 -> 趋势计算 -> 结果输出",
        "common_tools": ["xarray", "pandas", "Matplotlib", "SciPy"],
        "import_modules": ["xarray", "pandas", "matplotlib", "scipy"],
        "input": "清洗气象数据,统计周期,统计指标",
        "output": "气象统计表,趋势图",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素空间制图"],
    },
    {
        "name": "气象要素空间制图",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-空间制图",
        "function": "生成温度、气压、降水等气象要素填色图与等值线图。",
        "workflow": "格点数据 -> 投影转换 -> 绘图配置 -> 添加元素 -> 图片导出",
        "common_tools": ["Cartopy", "Matplotlib", "PyGMT", "MetPy"],
        "import_modules": ["cartopy", "matplotlib", "pygmt", "metpy"],
        "input": "格点气象数据,变量名,地图样式",
        "output": "气象要素空间图",
        "source": METEOROLOGY_SOURCE,
        "next_tools": [],
    },
    {
        "name": "风场分析与可视化",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-风场分析",
        "function": "根据 U/V 风分量计算风速风向，并绘制风矢量、流线或风玫瑰图。",
        "workflow": "U/V分量读取 -> 风速风向计算 -> 风场绘图 -> 结果输出",
        "common_tools": ["MetPy", "Windrose", "Cartopy", "Matplotlib"],
        "import_modules": ["metpy", "windrose", "cartopy", "matplotlib"],
        "input": "格点气象数据,U/V风分量,高度层,制图参数",
        "output": "风场分析结果,风场可视化图件",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素空间制图"],
    },
    {
        "name": "气象垂直剖面分析",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-垂直结构",
        "function": "生成高度-经度、时间-高度等剖面图，分析气象垂直结构。",
        "workflow": "多层数据读取 -> 剖面提取 -> 绘图 -> 标注 -> 导出",
        "common_tools": ["MetPy", "xarray", "Cartopy", "Matplotlib"],
        "import_modules": ["metpy", "xarray", "cartopy", "matplotlib"],
        "input": "格点气象数据,剖面线,变量名",
        "output": "气象垂直剖面图",
        "source": METEOROLOGY_SOURCE,
        "next_tools": [],
    },
    {
        "name": "数值模式数据后处理",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-模式后处理",
        "function": "解析 WRF/EC 模式结果，计算衍生量并输出标准化数据。",
        "workflow": "模式数据读取 -> 要素提取 -> 衍生量计算 -> 质控 -> 输出",
        "common_tools": ["WRF-Python", "xarray", "MetPy", "cfgrib"],
        "import_modules": ["wrf", "xarray", "metpy", "cfgrib"],
        "input": "模式输出路径,变量名,后处理规则",
        "output": "模式后处理标准化数据,格点气象数据",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象数据质量控制", "气象衍生量计算", "气象要素空间制图", "风场分析与可视化", "气象垂直剖面分析"],
    },
    {
        "name": "降水数据处理与极端事件识别",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-降水事件",
        "function": "计算累计降水和降水强度，按阈值识别极端降水事件。",
        "workflow": "降水数据 -> 清洗 -> 累计/强度计算 -> 阈值判定 -> 极端事件标记",
        "common_tools": ["pandas", "xarray", "numpy", "Matplotlib"],
        "import_modules": ["pandas", "xarray", "numpy", "matplotlib"],
        "input": "清洗气象数据,累计窗口,极端阈值",
        "output": "降水统计结果,极端事件清单",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素空间制图"],
    },
    {
        "name": "气象数据批量格式转换",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-格式转换",
        "function": "批量完成 GRIB、NetCDF、CSV 之间的格式转换和元数据标准化。",
        "workflow": "批量读取 -> 变量解析 -> 格式转换 -> 元数据标准化 -> 输出",
        "common_tools": ["xarray", "cfgrib", "netCDF4", "pandas"],
        "import_modules": ["xarray", "cfgrib", "netCDF4", "pandas"],
        "input": "气象文件目录,源格式,目标格式,变量清单",
        "output": "结构化气象数据,批量转换气象文件",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象数据读取与格式解码", "气象数据质量控制"],
    },
    {
        "name": "气象衍生量计算",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-物理量计算",
        "function": "由温度、气压、湿度等基础变量计算相对湿度、位温等常用气象物理量。",
        "workflow": "基础变量读取 -> 公式计算 -> 单位统一 -> 结果输出",
        "common_tools": ["MetPy", "xarray", "numpy"],
        "import_modules": ["metpy", "xarray", "numpy"],
        "input": "清洗气象数据,基础变量,目标衍生量,单位配置",
        "output": "气象衍生量数据,格点气象数据",
        "source": METEOROLOGY_SOURCE,
        "next_tools": ["气象要素空间制图", "风场分析与可视化", "气象垂直剖面分析"],
    },
    {
        "name": "气象站点数据空间可视化",
        "category": METEOROLOGY_CATEGORY,
        "problem_type": "气象学-站点可视化",
        "function": "对气象站点观测数据进行打点、分级着色和空间展示。",
        "workflow": "站点数据 -> 坐标匹配 -> 分级渲染 -> 地图叠加 -> 输出",
        "common_tools": ["GeoPandas", "Cartopy", "Folium", "Matplotlib"],
        "import_modules": ["geopandas", "cartopy", "folium", "matplotlib"],
        "input": "插值气象数据,站点观测数据,经纬度字段,分级规则",
        "output": "气象站点空间可视化地图",
        "source": METEOROLOGY_SOURCE,
        "next_tools": [],
    },
]


_METEOROLOGY_SPEC_BY_NAME = {spec["name"]: spec for spec in METEOROLOGY_SPECS}


def _run_meteorology_tool(tool_name: str, input_text: str) -> str:
    return run_workflow_tool(_METEOROLOGY_SPEC_BY_NAME[tool_name], input_text)


def meteorology_data_read_decode(input_text: str) -> str:
    return _run_meteorology_tool("气象数据读取与格式解码", input_text)


def meteorology_data_quality_control(input_text: str) -> str:
    return _run_meteorology_tool("气象数据质量控制", input_text)


def meteorological_spatiotemporal_interpolation(input_text: str) -> str:
    return _run_meteorology_tool("气象要素时空插值", input_text)


def meteorological_time_series_statistics(input_text: str) -> str:
    return _run_meteorology_tool("气象时间序列统计分析", input_text)


def meteorological_spatial_mapping(input_text: str) -> str:
    return _run_meteorology_tool("气象要素空间制图", input_text)


def wind_field_analysis_visualization(input_text: str) -> str:
    return _run_meteorology_tool("风场分析与可视化", input_text)


def meteorological_vertical_profile_analysis(input_text: str) -> str:
    return _run_meteorology_tool("气象垂直剖面分析", input_text)


def numerical_model_post_processing(input_text: str) -> str:
    return _run_meteorology_tool("数值模式数据后处理", input_text)


def precipitation_extreme_event_detection(input_text: str) -> str:
    return _run_meteorology_tool("降水数据处理与极端事件识别", input_text)


def meteorology_batch_format_conversion(input_text: str) -> str:
    return _run_meteorology_tool("气象数据批量格式转换", input_text)


def meteorological_derived_quantity_calculation(input_text: str) -> str:
    return _run_meteorology_tool("气象衍生量计算", input_text)


def meteorology_station_spatial_visualization(input_text: str) -> str:
    return _run_meteorology_tool("气象站点数据空间可视化", input_text)


METEOROLOGY_TOOL_NAMES = tool_names(METEOROLOGY_SPECS)
METEOROLOGY_KG_ROWS = build_kg_rows(METEOROLOGY_SPECS)
