# 首批 GitHub 工具使用案例

以下案例与当前 `catalog/registry.json` 和适配器的实际字段一致。示例只说明调用形态，
数值结果会随输入和版本变化；正式调用前应核对单位、CRS、数组长度和 Skill 暴露状态。

## 1. GeoVerdeGrid

```json
{"name":"GeoVerdeGrid","arguments":{"easting":[0,1,0,1],"northing":[0,0,1,1],"values":[0,1,1,2],"region":[0,1,0,1],"shape":[3,3]}}
```

预期：返回 3×3 的 `grid`、方法 `verde_spline` 和有限值范围。稀疏点或网格外推需要
调用方单独评估。

## 2. GeoRegionMask

当前 `region_set` 只支持离线 `srex`；之前两个 Natural Earth 容器名已撤下。

```json
{"name":"GeoRegionMask","arguments":{"longitude":[0,10,100],"latitude":[0,10,30],"region_set":"srex"}}
```

预期：返回三个与输入点按索引配对的区域数字 ID 或 `null`，以及命中数量；数字 ID
来自 SREX 上游定义。

## 3. HydroErrorMetrics

```json
{"name":"HydroErrorMetrics","arguments":{"observed":[1,2,3],"simulated":[1,2,4],"metrics":["rmse","mae","nse"]}}
```

预期：`sample_count=3`，`rmse≈0.57735`、`mae≈0.33333`、`nse=0.5`。

## 4. ScientificCurveFit

```json
{"name":"ScientificCurveFit","arguments":{"x":[0,1,2],"y":[1,3,5],"model":"linear","initial":{"slope":1,"intercept":0},"bounds":{"slope":{"min":0,"max":10}}}}
```

预期：`success=true`，参数约为 `slope=2`、`intercept=1`，RMSE 接近 0。

## 5. HydroInterpolationGrid

```json
{"name":"HydroInterpolationGrid","arguments":{"easting":[0,1,0,1],"northing":[0,0,1,1],"values":[0,1,1,2],"region":[0,1,0,1],"resolution":0.5,"method":"linear","crs":"EPSG:4326"}}
```

预期：`shape=[2,2]`，`x=[0,0.5]`、`y=[0,0.5]`，
`grid=[[0,0.5],[0.5,1]]`。整数输入保留小数插值结果。
这里显式给出了 CRS；缺少 CRS 时适配器拒绝执行。

## 6. MetPyWindComponents

```json
{"name":"MetPyWindComponents","arguments":{"speed":[10,20],"direction":[0,90],"speed_unit":"m/s"}}
```

预期：`u=[0,-20]`、`v=[-10,0]`（允许浮点误差），其中方向按气象学来向解释。

## 7. SeismicReflectivity

```json
{"name":"SeismicReflectivity","arguments":{"vp":[2000,2200,2200],"density":[2,2.2,2.2]}}
```

预期：`coefficients≈[0.09502,0]`，数量为输入样点数减一。

## 8. SeismicSegySummary

```json
{"name":"SeismicSegySummary","arguments":{"segy_path":"data/line.sgy","preview_traces":3}}
```

预期：返回 trace/sample 数、采样间隔和最多三道均值。文件必须存在于工作区，且不能
使用绝对路径。

## 9. HydroReferenceET0

```json
{"name":"HydroReferenceET0","arguments":{"tmin_c":10,"tmax_c":25,"rh_min":40,"rh_max":80,"wind_m_s":2,"solar_mj_m2":18,"latitude_deg":35,"day_of_year":180}}
```

预期：返回 `et0_mm_day`、`net_radiation_mj_m2_day` 和太阳几何计算的参考辐射。
实现使用标量日计算，并按 FAO-56 计算入射短波修正后的净辐射；正式研究仍应复核
辐射观测和独立参考实现。
若 `1 < Rs/Rso ≤ 1.05`，结果正常返回且 `rs_rso_limited` 为 `true`，回答中应说明这一点。
若输入极夜条件或 `Rs/Rso > 1.05`，应得到明确的不可原样重试错误；不要把错误当作 ET0=0。

## 10. SpatialMoranI

```json
{"name":"SpatialMoranI","arguments":{"x":[0,1,0,1],"y":[0,0,1,1],"values":[1,2,3,4],"k":2,"permutations":0}}
```

预期：返回 `moran_i=0`、`expected_i≈-0.3333`、`p_sim=null` 和默认
`random_seed=0`。增加置换次数会产生可复现的置换 p 值，报告时应记录次数、seed
和权重策略。

## 调用前检查

- 目录字段中的固定 commit、包版本和许可证必须可追溯；
- 文件工具使用任务相对路径，禁止路径穿越；
- CRS、单位、气象 convention 和数组对齐必须由调用方确认；
- 首批十个工具已挂接四个已有 Skill；先使用描述中的领域词检索并加载，再调用所需工具；
- 成功执行只证明适配器返回了结构化结果，不等于数据质量或科学结论验收。

