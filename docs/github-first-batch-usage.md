# 首批 GitHub 工具使用说明

首批接入的是十个经过限定的运行时操作，而不是把第三方包的全部 API 暴露给模型。目录中的
`input_schema`、`output_schema` 是唯一调用契约；运行时用 `ToolExecutor` 返回
`status`、`data`、`artifacts` 和标准错误对象。所有数值数组必须等长且为有限数，
坐标系和物理单位由调用方明确提供，工具不会隐式转换。
目录的 `constraints` 还记录每个工具实际执行的数组对齐、单位、CRS 和可复现性要求。

## 通用调用形式

```json
{"name": "工具名", "arguments": {"参数": "值"}}
```

专业工具在目录中已注册，并已扩展到四个已有 Skill：栅格分析、地质表格分析、气候
情景分析和地震目录分析。这里是已有 Skill 的工具映射扩展，没有新增 Skill，也不代表
完整工作流已经验收；模型仍需先加载相关 Skill，再按其语义约束调用工具。

## 工具接口

### GeoVerdeGrid

用途：用 Verde 1.9.0 的 spline 将散点值估计到规则网格。

输入字段：

- `easting`、`northing`、`values`：等长数值数组；
- `region`：`[xmin, xmax, ymin, ymax]`；
- `shape`：`[nx, ny]`，每个维度至少为 2；
- `damping`：可选非负阻尼；
- 坐标和数值单位需要由调用方在任务语义中说明。

输出为 `method`、`shape`、`region`、二维 `grid`、`min` 和 `max`。这是
平滑估计，不自动判断外推是否具有科学意义。

### GeoRegionMask

用途：用 Regionmask 0.13.0 的预定义区域集合对经纬度点做区域编号判定。

输入是等长 `longitude`、`latitude` 数组，以及 `region_set`：
`srex`。此前列出的两个 Natural Earth 容器没有 `.mask` 接口，现已从合法枚举中撤下；
本工具当前仅提供随 regionmask 安装的离线 SREX 区域，不隐式下载或选择行政区图层。

输出 `region_ids` 与输入点一一对应（经度和纬度按同一索引配对），未命中为 `null`，并给出
`inside_count`。区域编号是上游区域集合的数字 ID，不是行政区名称；工具不修复
几何、不重投影。

### HydroErrorMetrics

用途：用 HydroErr 2.0.0 比较两条已经对齐的水文序列。

输入 `observed`、`simulated` 和可选 `metrics`。指标可选
`nse`、`rmse`、`mae`、`kge_2009`、`pearson_r`。输出为
`metrics` 字典和 `sample_count`。观测与模拟必须同长度，零分母或常量序列的
指标应按错误或 `null` 解释，不能当作 0。

### ScientificCurveFit

用途：用 LMFIT 1.3.4 拟合有限模型 `linear` 或 `exponential`。

输入 `x`、`y`、`model`，可选 `initial` 参数初值和每个参数的
`bounds: {"min": ..., "max": ...}`。不接受 Python 表达式。输出拟合参数、
`rmse`、`aic`、`success` 和 `sample_count`。

### HydroInterpolationGrid

用途：用 hydrointerp 1.2.13 将一个时间点的站点值插值到网格。

输入为等长 `easting`、`northing`、`values`，`region`、正数
`resolution`、显式 `crs`，可选 `method`（`linear`、`nearest`、
`cubic`）、`extrapolation`、`time`。由于上游库需要投影信息，`crs` 是必填
字段。输出为 `x`、`y`、二维 `grid`、`shape`、`method` 和 `crs`；
NoData 用 `null` 表示。整数形式的观测值也会按浮点数参与插值，保留小数结果。

### MetPyWindComponents

用途：用 MetPy 1.7.1 的单位感知 API 将气象风速和来向转换为 `u`、`v`。

输入等长 `speed`、`direction`（角度为气象学来向），可选
`speed_unit`，默认 `m/s`。输出 `u`、`v`（统一为 m/s）、
`coordinate_convention` 和 `count`。方向 0° 表示从北向来，故 v 分量为负。

### SeismicReflectivity

用途：用 Bruges 0.5.4 的 acoustic reflectivity 计算相邻样点的声阻抗反射系数。

输入等长正数数组 `vp` 和 `density`。Bruges 0.5.4 依赖真实的 `pkg_resources`，
由固定 `setuptools==80.9.0` 提供；已删除进程内的假模块注入。不要在该环境中单独执行
`pip install -U setuptools`：更新的版本（如本环境曾安装的 84.0.0）不再提供
`pkg_resources`，Bruges 会无法导入。输出为无量纲
`coefficients`、`count`、`input_count` 和方法名。当前接口是零偏移声学反射，
不接受角度，也不等价于完整 Zoeppritz 道集。

### SeismicSegySummary

用途：用 segyio 1.9.14 读取工作区内 SEG-Y 文件的有限摘要。

输入 `segy_path`（任务相对路径）和可选 `preview_traces`（1–20，默认由
实现使用 3）。输出 `trace_count`、`sample_count`、`sample_interval_us`
和有限道均值预览。文件只读，路径由运行时复制到隔离输入目录；工具不修改原文件，
也不重采样或修复 SEG-Y 几何。

### HydroReferenceET0

用途：用 PyETo 固定 commit 的 FAO-56 Penman–Monteith 公式计算一天的参考 ET0。

输入标量 `tmin_c`、`tmax_c`、`rh_min`、`rh_max`、`wind_m_s`、
`solar_mj_m2`、`latitude_deg`、`day_of_year`，可选 `altitude_m`。温度是
°C、相对湿度是百分比、辐射是 MJ/m²/day、风速是距地面 2 m 高度的 m/s。输出
`et0_mm_day`、`radiation_extra_terrestrial_mj_m2_day`、`net_radiation_mj_m2_day`、
`rs_rso_ratio`、`rs_rso_limited` 和方法名。适配器按 FAO-56 对输入入射短波做反照率修正，
并估算长波项后计算净辐射；正式研究仍需核对辐射观测和独立参考实现。
晴空辐射为零（如极夜）时返回 `unsupported_conditions`。实测 Rs 略高于估算的晴空辐射
Rso 在晴天很常见：`1 < Rs/Rso ≤ 1.05` 时按 FAO-56 式 39 在长波项中把比值限制为 1.0，
并返回 `rs_rso_limited: true`；`Rs/Rso > 1.05` 时返回 `invalid_arguments`，通常是单位或
观测错误。两种错误都不可原样重试，需要选择适用方法或先核对并修正输入。

### SpatialMoranI

用途：用 PySAL 26.7 的 libpysal KNN 权重和 esda Moran 计算全局空间自相关。

输入等长 `x`、`y`、`values`，可选 `k`、`permutations` 和 `random_seed`。输出
`moran_i`、`expected_i`、`p_sim`、`k`、`sample_count` 和 `random_seed`。坐标距离
单位和 CRS 必须由调用方确认；常数值序列的 `moran_i` 为 `null`，`permutations=0`
时 `p_sim` 为 `null`。置换检验使用每次调用独立的随机数生成器，并回显固定 seed
（0–4294967295），不修改 NumPy 进程全局状态。统计量采用 esda，置换尾部计数遵循
esda 2.10.0 的规则，已与该版本的参考结果和多线程调用对照。

## 查找与加载已有 Skill

`skill_find` 按完整词匹配并按命中词数排序，忽略单字母符号和常见连接词；空查询仍
列出完整目录。四个宿主 Skill 的描述、`when_to_use` 和操作前提已更新，数量仍为 34。
例如 `SEG-Y seismic trace summary` 命中 `earthquake_catalog_analysis`，
`reference evapotranspiration FAO-56 Penman-Monteith` 命中 `climate_scenario_analysis`。
模型先观察检索结果，再 `skill_load`。这些分支分别使用文件、观测数组或目录表，
不是要求每次任务同时提供 GeoTIFF、SSP 表和地震事件目录。

## 错误和版本

参数不符合 schema 返回 `invalid_arguments`；输入文件缺失返回 `missing_input`；
包未安装返回 `missing_dependency`；第三方计算错误返回
`professional_tool_error`。每个目录条目都保留 `provider`、`license`,
`asset_version`、`source_commit`、`official_protocol`、`runtime` 和
`lifecycle`，这些是目录元数据，不需要重复塞进调用参数。


