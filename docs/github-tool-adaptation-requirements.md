
# GitHub 候选工具适配要求

本文规定如何把 catalog/incoming/github-tool-candidates.json 中的 GitHub 项目适配成 GeoAgent 运行时 Tool。候选登记只是来源清单，不表示已经安装、注册、验证或可由模型调用。以下要求按实际操作形态分类；同一个项目可能跨越多个类别。

## 1. 统一接入边界

Tool 是一个受限、可审计的操作，不是把整个第三方包、模型或命令行程序暴露给模型。标准链路是：

    固定 Git commit 或发布版本
      -> 选择一个有限操作
      -> 定义 input_schema、result_schema
      -> 编写 handler，处理单位/CRS/路径/NoData/错误
      -> 注册 catalog/registry.json 和 ToolRegistry
      -> 运行契约、单元、依赖和必要的工作流验证

现有执行契约继续使用 ToolDefinition 的 name、description、when_to_use、input_schema、result_schema，以及 Tool 的 handler、pure、input_paths、reference_paths。provider、license、asset_version、source_commit、运行环境和生命周期属于 catalog 的 registration_metadata，不加入模型调用参数。字段可以暂时为 null，但应列入 pending_fields。

每项接入都必须回答：

- 输入是否能用 JSON Schema 完整表达，是否需要文件或外部资源？
- 输出是 JSON 摘要、ArtifactRef 文件，还是模型/服务响应？
- 是否有 CRS、空间分辨率、时间、单位、NoData 或坐标轴要求？
- 是否会联网、读取凭证、下载模型权重或启动外部进程？
- 失败是否可安全重试，是否可能产生未知副作用？
- 现有 Skill 是否语义匹配；不匹配时如何保持 pending_skill_mapping？
- 在固定 commit 和固定运行环境下如何复现？

## 2. 所有工具的共同门槛

### 2.1 来源、版本、许可证和官方协议

运行时条目至少保留如下字段：

~~~json
{
  "provider": "组织或维护者",
  "license": "SPDX 标识或许可证名称",
  "asset_version": "发布版本或包版本",
  "source_commit": "实际使用的源码提交",
  "source_url": "GitHub 仓库",
  "official_protocol": {
    "applicability": "applicable | not_applicable | unknown",
    "name": "协议名称或 null",
    "version": "协议版本或 null"
  },
  "runtime": {
    "python": "3.12",
    "dependency_lock": "requirements-tool.lock",
    "environment_version": "geoagent-professional-2026.10"
  },
  "lifecycle": {
    "registration": "candidate | registered",
    "contract_validation": "not_run | passed | failed",
    "unit_validation": "not_run | passed | failed",
    "workflow_validation": "not_run | passed | failed",
    "platform_validation": "not_run | passed | failed",
    "release_status": "draft | usable | blocked"
  }
}
~~~

source_commit 是源码版本，asset_version 是发布/包版本，runtime.environment_version 是依赖环境版本，三者不能互相替代。模型权重、外部数据快照和容器镜像应另外记录版本和 sha256。

许可证审查要覆盖传递依赖、GPL/AGPL 或商业限制、数据集/底图/权重的独立许可、分发要求和归属信息。纯算法或本地文件工具通常将 official_protocol.applicability 设为 not_applicable；网络服务或 OGC/CF/SOS/REST 客户端应写明协议名称和版本；未确认时为 unknown 并列入 pending_fields。

### 2.2 参数、结果和错误

- 数组长度、数值范围、枚举、互斥项、字符串格式和必填项必须写入 input_schema。
- 所有距离、面积、角度、温度、流量、压力、降水、震级和时间字段都声明单位；handler 要显式转换。
- CRS 使用 EPSG/WKT；不得把经纬度默认为平面米坐标。
- 文件只能使用 workspace 相对路径，声明 input_paths/reference_paths。
- 输出文件以 ArtifactRef 返回；结果数据以 result_schema 返回。
- 对 NoData、空集合、重复记录、缺失列和非法几何定义稳定策略。
- 异常映射为 invalid_arguments、dependency_missing、external_service、model_unavailable、tool_timeout 等 ToolFailure code，不泄露令牌、完整环境变量或越界路径。
- 拒绝 NaN/Infinity 和过大的数组/文件；结果包含单位、CRS、算法参数、输入摘要和 provenance。

### 2.3 依赖和隔离

依赖写入 requirements/lock，记录 Python、操作系统和 GDAL/GEOS/PROJ/NetCDF 等 native 版本。安装成功后必须执行导入探针和最小 fixture，不能只以 pip 成功为证据。需要 C/C++/Fortran/Java/MPI/GPU/外部 CLI 的项目应先建立独立环境或标记 blocked。handler 不得在调用时在线安装依赖、写用户目录或读取未声明的全局文件。

## 3. 按操作形态分类

### 3.1 纯本地确定性数值计算

典型候选：HydroErr、LMFIT、Hydrointerp、MetPy 的公式、PyEto、Bruges、Verde、部分 PySal、HydroLM、Climate-indices。

适合暴露为单一操作：误差指标、曲线拟合、点到网格插值、气象公式、反射系数、参考蒸散发和空间统计量。

接入前需要：

- 选定有限 API 和算法版本；不暴露任意表达式、脚本或整个模块。
- 约定数组长度、排序、时间对齐、重复时间戳和缺失值。
- schema 明确 units、crs、time_axis、method、missing_policy、seed 等语义字段。
- 限制拟合最大迭代和收敛阈值；返回收敛状态、参数边界和诊断。
- 记录参考高度、作物系数、时区、时间步、物理适用范围和数值精度。
- pure=true 只用于真正无随机、无当前时间、无外部缓存的函数。
- 测试解析值、边界值、短/空数组、NaN/Inf、单位错误、非收敛和重复调用一致性。

特别注意：HydroErr 指标名称应枚举化；LMFIT 模型和参数表达式白名单化；Hydrointerp/Verde 记录网格边界、分辨率、搜索半径和外推策略；MetPy/PyEto 显式记录温度、风速、压力、辐射、纬度、海拔和日历；Bruges 记录密度/速度/角度单位。

### 3.2 矢量空间、几何和区域运算

典型候选：GeoPandas、Shapely、Fiona、PySal、Regionmask、Cartopy、Verde、Collocate、Pysheds 的向量操作。

接入前需要：

- 明确 GeoJSON/FeatureCollection、GeoPackage 图层或相对路径，几何类型、字段类型和 CRS。
- 规定空几何、无效环、自相交、多部件、Z/M 坐标和拓扑修复策略；修复必须可追踪。
- 面积、长度、距离和缓冲只能在合适的投影 CRS 或地理测地线上执行。
- 声明边界包含规则、容差、空间索引、排序稳定性、最大要素数和输出大小。
- 对编码、字段名、日期和空值进行格式校验；图形对象只能作为 artifact。
- 记录 GEOS/PROJ 版本，因为不同版本可能改变拓扑结果。

可考虑关联 spatial-kriging-interpolation、fractional-zonal-statistics、scientific-raster-analysis、remote-sensing-preprocessing；只做几何基础操作时可以 registered 但 pending_skill_mapping。

### 3.3 栅格、网格和时空数组

典型候选：Rasterio、Georasters、PyGeoprocessing、salem、Regionmask、xarray 生态、Datashader、OpenClimateGIS、xgcm、Pangaea、ESMPy。

接入前需要：

- 定义 GeoTIFF/COG/NetCDF/Zarr/GRIB 等格式、dtype、波段/变量、维度顺序和 NoData。
- 明确仿射变换、分辨率、范围、像元对齐、重采样和目标 CRS；禁止隐式重投影。
- xarray 输入定义 time/lat/lon/level 等维度、日历、chunk 和是否允许 dask。
- NetCDF/GRIB/HDF 要检查 CF conventions、压缩、坐标变量和编码。
- 大栅格使用窗口/分块，设置内存和输出大小；JSON 只返回摘要。
- artifact 摘要应含 bbox、shape、dtype、CRS、units、valid_count 和统计量。
- 验证 GDAL/PROJ/ESMF/NetCDF 动态库和不同经度范围、极区、旋转网格及 NoData 边界。

ToolExecutor 的 JSON 校验不能替代文件内容校验；需要 magic bytes、格式、CRS 和变量一致性检查。长任务必须支持取消、timeout 和 outcome_unknown。

可挂载 scientific-raster-analysis、remote-sensing-raster-statistics、remote-sensing-preprocessing；底层读写工具可 pending_skill_mapping。

### 3.4 水文、地下水和时间序列

典型候选：Wetterdienst、Ulmo、ERA5-tools、Ecohydrolib、HydroFunctions、hidrocomp、PyFlo、Flopy、Anaflow、WellTestPy、Pytesmo、Hydrostats、htimeseries、Hydrointerp、PyRecharge、PyGLUE、PySDI、EFlowCalc、Pastas、Shyft、HydPy 等。

接入前需要：

- 统一 ISO 8601、时区、夏令时、闰日、采样频率、聚合边界和缺测编码。
- 明确降水、流量、水位、蒸散发、温度、压力和土壤水分的单位。
- 将站点 ID、坐标、海拔、流域边界、时间和质量标志作为独立字段。
- 插值、重采样、缺测填补、异常筛选和校准必须分开记录方法和参数。
- 地下水/数值模型需网格、层、边界条件、初始状态、时间步、求解器、残差和收敛判据。
- 大型时序通过 Parquet/NetCDF/CSV artifact 返回摘要、时间范围和有效数。
- 网络数据记录站点覆盖、数据许可、请求时间、查询条件、版本和 checksum。

当前 Skill 对水文、地下水和时序覆盖不完整；geological-table-analysis 仅可用于表格清洗/统计。没有精确匹配时保持 pending_skill_mapping。

### 3.5 网络服务和数据获取 API

典型候选：geemap/GEE、HyRiver、Wetterdienst、Ulmo、ERA5-tools、HKVFEWSPY、PyHIS、BoM Water、StreamStats、pyOWM、Wetland、Hydroshare。

接入前需要：

- 记录 provider、服务基址、API 版本、数据许可、区域限制和 official_protocol。
- schema 只允许白名单 endpoint、时间/空间范围、变量、分页、排序和最大记录数，拒绝任意 URL 以防 SSRF。
- 凭证只从受控环境注入，不进入 schema、目录、日志或结果；无凭证时给出明确错误。
- 设置连接/读取/总超时、重试退避、速率限制和取消；区分网络失败、HTTP 错误、部分结果和解析失败。
- 缓存键包含 URL、参数、API 版本和时间；保存脱敏请求摘要、状态、数据版本、请求时间和 checksum。
- 结果标注 freshness、缓存命中和来源。网络工具默认 pure=false。
- 服务变更后重新做端到端验证，不复用旧响应或旧报告。

可与 earthquake-catalog-analysis、climate-scenario-analysis、semantic-geospatial-query 关联，但必须检查变量、时间和空间约束是否一致。网络工具未完成集成验证前保持 release_status=draft。

### 3.6 模型和科学框架

典型候选：PCRaster、PYWR、VIC、Xanthos、HydPy、RRMPG、pySTEPS、CMF、TopoFlow、EXP-HYDRO、SuperflexPy、TIMML、TTim、imod-python、Phydrus、Landlab、PyHSPF、SPHY、MetSim、climpred 等。

接入前需要：

- 把框架拆为构建输入、运行一次模拟、读取结果、校准或敏感性分析等有限操作。
- 定义配置 schema、边界/初始条件、网格、参数单位、时间步、输出变量和求解器。
- 记录二进制/编译器/MPI/Java/Fortran 版本和启动方式；禁止用户拼接 shell。
- 设置 CPU、内存、并行度、磁盘、deadline，支持取消并在超时后标记 outcome_unknown。
- 区分确定性/随机模拟、校准和同化；记录随机种子、样本数、收敛和数据版本。
- 输出通过 artifact 返回摘要；模型运行成功不能替代科学 workflow_validation。
- 参数搜索空间和目标函数白名单化，不执行任意 Python。

没有精确 Skill 时保留 pending_skill_mapping；不因框架已安装就加入 BASE_TOOLS。

### 3.7 机器学习、深度学习和模型权重

典型候选：NeuralHydrology、pySTEPS、rainymotion、统计降尺度/预报组件及其他带权重的模型。

接入前需要：

- 分别记录代码、模型和权重版本；保留权重 URL/registry、sha256、许可证、训练数据和发布日期。
- 固定推理框架、CUDA/cuDNN、CPU/GPU、精度和随机种子，记录硬件显存要求。
- 权重只从管理员白名单下载，写入受控缓存并校验 checksum；禁止任意 URL 和不可信 pickle。
- 明确归一化、缺测掩膜、窗口、时间步、网格、单位恢复等预/后处理。
- 训练、校准、推理分开；首批默认只提供受限推理。
- 结果含 model_id、model_version、weights_sha256、输入窗口、置信区间/集合成员和适用范围。
- 测试固定 fixture 数值回归、CPU/GPU 容差、缺权重、校验失败、显存不足和取消。

当前 Skill 不一定覆盖模型训练/推理，适合时才挂 climate-scenario-analysis，否则 pending_skill_mapping。

### 3.8 外部二进制、CLI 和编译型套件

典型候选：Madagascar、PCRaster、WhiteboxTools、SeismicZFP 转换、ESMF/ESMPy、Metview、WRF-Hydro 及含 Fortran/C++ 求解器的模型。

接入前需要：

- 固定可执行文件路径、版本、构建哈希和许可证；结构化参数映射到白名单 argv，禁止任意命令。
- 工作目录在 workspace，输入列入 input_paths/reference_paths，输出可列举和清理。
- subprocess 需要超时、取消、无交互环境、stdout/stderr 截断和 exit code。
- 验证动态库、编译器、MPI、Java/Fortran runtime、locale 以及 Windows/Linux 差异。
- 中间文件、临时目录、部分输出和崩溃恢复均有上限和状态。
- 输出做 magic bytes、格式、大小、checksum、CRS/变量校验；exit code=0 不代表科学有效。

### 3.9 地球物理文件和专用格式

典型候选：ObsPy、Pyrocko、Bruges、Segyio、SeismicZFP、IRIS、xsboringen、Madagascar。

接入前需要：

- 明确支持的格式和版本：SEG-Y rev、MiniSEED、SAC、StationXML、NetCDF/CF、ZGY/SGZ 等；不能只靠扩展名。
- 定义字节序、头字段、采样间隔、坐标单位、道数、缺失值和压缩方式；大文件采用窗口读取。
- 结果返回格式、记录数、时间/空间范围、采样率、坐标 CRS 和头字段摘要，完整波形通过 artifact。
- SEG-Y 要记录 textual/binary header、inline/crossline 和坐标缩放；波形要记录台站、通道和采样率。
- 测试随机读取边界、损坏文件、压缩精度和解压数值；输出 checksum。
- 数据文件许可和代码许可分开审查。

earthquake-catalog-analysis 只适合目录统计，不等同于波形、SEG-Y 或反演；语义不符时 pending_skill_mapping。

### 3.10 交互式可视化、Notebook 和 Web UI

典型候选：HoloViews、GeoViews、Datashader、Panel、hvPlot、geemap、Cartopy、geonotebook、EarthSim。

接入前需要：

- 将交互操作改成一次性、无状态的渲染/导出，如 PNG/SVG/HTML；不注册长期 notebook kernel 或 UI session。
- 参数只允许数据路径、字段、范围、色带、格式和尺寸等白名单值；禁止任意 JS/Python 回调。
- 固定无头后端、字体、DPI、色彩空间、时区和随机种子以保证可复现。
- HTML/JS artifact 做外链、脚本注入和凭证检查；在线底图按网络工具处理。
- UI 长连接、会话数、内存和运行时受控。已归档 geonotebook/EarthSim 默认不接入。

### 3.11 资源索引、无仓库和已归档项目

Awesome Earth Engine、Awesome-EarthObservation-Code 只能作为参考资料，不进入 ToolRegistry。xshape 当前没有 repository URL，在官方来源、许可证、版本和 API 核实前不能接入。

geonotebook、EarthSim、Openradar、wflow、Hydropy、Hydrobox 默认 blocked。只有找到维护者、确认许可证、锁定最后可复现 commit/依赖、完成安全和固定 fixture 验证后才可做隔离兼容层，release_status 仍保持 draft/limited。优先选择仍维护的替代库。

## 4. 对现有框架需补充的能力

### 4.1 ToolDefinition 和目录分工

现有五字段执行契约足够表达首批工具，不建议为 provider、license、asset_version 增加 ToolDefinition 字段。新增工具通常只需 native handler、schema、目录元数据、依赖锁和 bootstrap/source_registry 注册。generic source handler 的可信入口必须加入 source_registry 的 ENTRY_MODULES 白名单。

只有调度确实需要能力摘要时，才从目录读取非敏感 capability；凭证和内部路径不能暴露给模型。

### 4.2 文件、网络和长任务

文件格式、CRS、单位和大小校验应由 handler/共享适配层完成；网络策略应统一提供域名白名单、凭证引用名、超时、重试、缓存、脱敏日志和 offline 模式；长任务应支持取消、资源上限和 outcome_unknown。Skill 指令不能替代这些运行时控制。

### 4.3 权重和资源扩展

带权重工具可在 registration_metadata 增加：

~~~json
{
  "model_id": "模型标识",
  "model_version": "版本",
  "weights_uri": "管理员配置的来源",
  "weights_sha256": "校验和",
  "weights_license": "权重许可",
  "resource_requirements": {
    "cpu": 4,
    "memory_gb": 8,
    "gpu": "optional",
    "disk_gb": 10,
    "estimated_seconds": 60
  }
}
~~~

没有模型权重的工具不必伪造这些字段。

### 4.4 Skill 映射

新 Tool 可引用一个或多个已有 Skill，也可保持 pending_skill_mapping。判断依据是任务语义、输入前提、输出形式和科学约束一致，而不是项目名称相似。没有合适 Skill 时仍可登记 catalog，但在 workflow_validation 完成前不加入默认暴露集合或 BASE_TOOLS。

Skill 数量不会随工具数量线性增加；只有出现稳定、可复用、跨工具的用户任务流程时才新增 Skill。新增 Skill 需要同步 registry、SKILL.md、发现关键词、工具引用一致性和工作流测试，并单独评审。

## 5. 候选类型处置总表

| 类型/操作 | 默认处置 | 额外准备 | 可否直接进入运行时 |
|---|---|---|---|
| python_library，纯本地函数 | 选有限 API、锁版本、schema/handler/测试 | 单位、CRS、异常、性能 | 条件允许 |
| 读写空间/科学文件 | 格式、CRS、NoData、大小和 artifact | GDAL/NetCDF/格式 fixture | 条件允许 |
| service_client/网络 API | 服务版本、协议、凭证、SSRF、缓存、限流 | 脱敏网络集成测试 | 默认不直接 |
| model_or_framework | 拆固定操作，资源/配置/基准 | 求解器、长任务、校准 | 需适配 |
| ML/模型权重 | 权重版本、checksum、许可、资源 | CPU/GPU 回归、OOD | 需适配 |
| 外部 CLI/编译套件 | 固定二进制、argv 白名单、进程治理 | OS/动态库/取消 | 需适配 |
| 交互式 UI/Notebook | 改成无头一次性导出 | artifact 安全、前端资源 | 通常需适配 |
| archived_project | 默认阻断 | 维护来源、风险、可复现锁定 | 不直接 |
| resource_index | 参考资料 | 无 handler | 不作为 Tool |
| 无 repository URL | 补官方来源或阻断 | 许可证、版本、API 重核 | 不直接 |

## 6. 完成定义和接入顺序

1. 静态审查：source_url、provider、license、asset_version、source_commit、维护状态、协议、Skill 候选和外部资源。
2. 最小探针：锁定环境导入、固定 fixture、依赖/native 信息、异常和结果可序列化。
3. Tool 适配：固定 handler、schema、错误契约、artifact、provenance，并加入可信入口白名单。
4. 分层验证：contract_validation、unit_validation、workflow_validation、platform_validation 分别记录，不互相替代。
5. 发布：只有许可证、依赖复现、契约/单元测试和必要工作流均通过才设 release_status=usable；升级 commit、版本或环境后必须重跑测试，保留 Git 变更记录。

## 7. 首批十个工具的专项核对

Verde、Regionmask、HydroErr、LMFIT、Hydrointerp、MetPy、Bruges、Segyio、PyEto、PySal 在接入前要核实：

- PyPI 分发名、导入模块、稳定版本、许可证和实际 Git commit；
- Python 3.12 与现有 NumPy/SciPy 的兼容性；
- 是否能离线、无模型权重、有限内存执行单一操作；
- 输入单位、CRS、时间轴、缺失值、外部数据和输出文件；
- 现有 Skill 是否准确匹配；不匹配者标记 pending_skill_mapping；
- 每个工具至少一个成功 fixture 和一个失败 fixture；
- provenance 含工具名、asset_version、source_commit、runtime.environment_version、参数摘要和输入 checksum。

github-first-batch-usage.md 和 github-first-batch-examples.md 负责具体参数和 JSON 案例；本文件只规定适配审查要求。
