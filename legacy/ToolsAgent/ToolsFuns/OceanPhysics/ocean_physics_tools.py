"""Ocean physics tools added in the SciToolAgent tool-function style."""

from __future__ import annotations

from ToolsFuns.utils.workflow_tool_runtime import (
    WorkflowToolSpec,
    build_kg_rows,
    run_workflow_tool,
    tool_names,
)


OCEAN_PHYSICS_CATEGORY = "OceanPhysicsTools"
OCEAN_PHYSICS_SOURCE = (
    "PPT: 工具(1).pptx / 海洋物理学; "
    "ToolsAgent/ToolsFuns/OceanPhysics/ocean_physics_tools.py"
)


OCEAN_PHYSICS_SPECS: list[WorkflowToolSpec] = [
    {
        "name": "Argo浮标温盐剖面数据获取",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-数据获取",
        "function": "按时空条件检索并下载 Argo 浮标温盐剖面数据，读取 QC 标志并输出 xarray Dataset。",
        "workflow": "时空检索 -> 数据下载 -> QC标志读取 -> 输出温盐剖面数据",
        "common_tools": ["argopy", "xarray"],
        "import_modules": ["argopy", "xarray"],
        "input": "Argo检索条件,时间范围,空间范围,QC要求",
        "output": "温盐剖面数据,Argo剖面数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["Argo浮标剖面质控标记筛选", "温盐深数据异常值检测与剔除"],
    },
    {
        "name": "科考船CTD温盐深数据解析",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-数据获取",
        "function": "识别科考船 CTD 原始文件格式，解析传感器通道并输出结构化 DataFrame。",
        "workflow": "原始文件识别 -> 格式解析 -> 传感器通道提取 -> 输出温盐剖面数据",
        "common_tools": ["pySeabird", "pycnv", "pandas"],
        "import_modules": ["seabird|pycnv", "pandas"],
        "input": "CTD原始文件路径,传感器通道配置",
        "output": "温盐剖面数据,CTD温盐深数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["温盐深数据异常值检测与剔除"],
    },
    {
        "name": "卫星高度计海面高度数据获取",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-数据获取",
        "function": "选择卫星高度计或 CMEMS 再分析数据，按时空条件下载海面高度数据。",
        "workflow": "卫星任务选择 -> 时空检索 -> 数据下载 -> 输出海洋网格数据",
        "common_tools": ["Copernicus Marine Toolbox", "copernicusmarine", "xarray"],
        "import_modules": ["copernicusmarine", "xarray"],
        "input": "卫星任务,时间范围,空间范围,海面高度变量",
        "output": "卫星海面高度数据,海洋网格数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["HYCOM全球海洋模式数据获取"],
    },
    {
        "name": "卫星海表温度数据获取",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-数据获取",
        "function": "选择卫星温度传感器，按时空范围下载海表温度数据并进行云覆盖筛选。",
        "workflow": "传感器选择 -> 时空检索 -> 数据下载 -> 云覆盖筛选 -> 输出海洋网格数据",
        "common_tools": ["earthaccess", "xarray"],
        "import_modules": ["earthaccess", "xarray"],
        "input": "SST传感器,时间范围,空间范围,云覆盖阈值",
        "output": "卫星海表温度数据,海洋网格数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["HYCOM全球海洋模式数据获取"],
    },
    {
        "name": "HYCOM全球海洋模式数据获取",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-数据获取",
        "function": "获取 HYCOM 全球海洋模式预报或分析数据，解析 NetCDF/GRIB 坐标与变量。",
        "workflow": "预报时间选择 -> 变量选择 -> 空间范围定义 -> NetCDF下载 -> 数据解析",
        "common_tools": ["earthaccess", "xarray", "cfgrib", "fsspec", "s3fs", "cf-xarray"],
        "import_modules": ["earthaccess", "xarray", "cfgrib", "fsspec", "s3fs", "cf_xarray"],
        "input": "HYCOM时间,变量,空间范围,数据源地址",
        "output": "HYCOM模式数据,海洋网格数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": [],
    },
    {
        "name": "温盐深数据异常值检测与剔除",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-质量控制",
        "function": "对温盐深剖面进行气候态范围、突变、密度翻转和物理一致性检查，标记并剔除异常值。",
        "workflow": "数据读取 -> 气候态范围检查 -> 突变检测 -> 密度翻转检验 -> 异常标记 -> 质控输出",
        "common_tools": ["CoTeDe", "GSW-Python", "xarray", "pandas"],
        "import_modules": ["cotede", "gsw", "xarray", "pandas"],
        "input": "温盐剖面数据,质控规则,阈值参数",
        "output": "质控温盐剖面数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["重复海洋剖面数据检测与去重"],
    },
    {
        "name": "Argo浮标剖面质控标记筛选",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-质量控制",
        "function": "读取 Argo 数据内置 QC 标记，解读 0-9 级标志并筛选高质量剖面。",
        "workflow": "Argo数据加载 -> QC标记读取 -> 标记解读 -> 好数据筛选 -> 质控输出",
        "common_tools": ["argopy", "pySeabird", "pandas"],
        "import_modules": ["argopy", "seabird|pycnv", "pandas"],
        "input": "Argo剖面数据,QC标记筛选规则",
        "output": "质控Argo剖面数据,质控温盐剖面数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": ["重复海洋剖面数据检测与去重"],
    },
    {
        "name": "重复海洋剖面数据检测与去重",
        "category": OCEAN_PHYSICS_CATEGORY,
        "problem_type": "海洋物理学-质量控制",
        "function": "从多源海洋剖面中提取位置、时间和温盐特征，检测重复剖面并去重合并。",
        "workflow": "多源剖面读取 -> 特征提取 -> 重复检测 -> 去重合并 -> 唯一剖面输出",
        "common_tools": ["DC_OCEAN", "pandas", "xarray"],
        "import_modules": ["dc_ocean", "pandas", "xarray"],
        "input": "质控温盐剖面数据,重复判定阈值",
        "output": "唯一海洋剖面数据",
        "source": OCEAN_PHYSICS_SOURCE,
        "next_tools": [],
    },
]


_OCEAN_PHYSICS_SPEC_BY_NAME = {spec["name"]: spec for spec in OCEAN_PHYSICS_SPECS}


def _run_ocean_physics_tool(tool_name: str, input_text: str) -> str:
    return run_workflow_tool(_OCEAN_PHYSICS_SPEC_BY_NAME[tool_name], input_text)


def argo_float_profile_data_fetch(input_text: str) -> str:
    return _run_ocean_physics_tool("Argo浮标温盐剖面数据获取", input_text)


def ctd_temperature_salinity_depth_parse(input_text: str) -> str:
    return _run_ocean_physics_tool("科考船CTD温盐深数据解析", input_text)


def satellite_altimeter_sea_surface_height_fetch(input_text: str) -> str:
    return _run_ocean_physics_tool("卫星高度计海面高度数据获取", input_text)


def satellite_sea_surface_temperature_fetch(input_text: str) -> str:
    return _run_ocean_physics_tool("卫星海表温度数据获取", input_text)


def hycom_ocean_model_data_fetch(input_text: str) -> str:
    return _run_ocean_physics_tool("HYCOM全球海洋模式数据获取", input_text)


def temperature_salinity_depth_outlier_qc(input_text: str) -> str:
    return _run_ocean_physics_tool("温盐深数据异常值检测与剔除", input_text)


def argo_profile_qc_flag_filter(input_text: str) -> str:
    return _run_ocean_physics_tool("Argo浮标剖面质控标记筛选", input_text)


def duplicate_ocean_profile_detection(input_text: str) -> str:
    return _run_ocean_physics_tool("重复海洋剖面数据检测与去重", input_text)


OCEAN_PHYSICS_TOOL_NAMES = tool_names(OCEAN_PHYSICS_SPECS)
OCEAN_PHYSICS_KG_ROWS = build_kg_rows(OCEAN_PHYSICS_SPECS)
