---
id: xiaoyu_spatial_crop_modeler
name: Spatial Crop Modeler
description: 结合 ag-cube-cm、aggeodata、气候数据立方体、SoilGrids 和 DSSAT 执行像元级空间作物模拟并生成产量图。
  来源：晓宇地学 Skill 收集；流程已接入，依赖环境和完整工作流尚未逐项验收。
when_to_use: 'Expert orchestrator for spatial crop model simulations using ag-cube-cm
  + aggeodata. Use this skill whenever the user mentions: DSSAT, crop model, yield
  simulation, maize/wheat/bean/soybean yield, planting date analysis, spatial crop
  modeling, ag-cube-cm, SoilGrids, CHIRPS, CHIRTS, AgERA5, or any combination of climate/soil
  data with a process-based crop model. Trigger even if the user only says "run DSSAT"
  or "simulate yield" without mentioning the full stack — they almost certainly need
  this workflow. Also trigger when the user asks to interpret HWAM output or wants
  to understand why pixels were skipped.'
required_inputs:
- 现有气候和土壤 NetCDF/Zarr 数据立方体，或下载参数
- 作物和品种配置
- 种植日期与模型参数
expected_outputs:
- 像元级 DSSAT 模拟结果
- 产量地图
- HWAM 和运行诊断
tools:
- SkillReadResource
- read_file
- write_file
- execute_python
constraints:
- 仅提供当前任务需要的操作；不得将示例或说明视为已计算结果。
- 先检查依赖版本、输入路径、CRS、单位及所需数据；缺少时明确报告，不自动安装依赖或使用 GPU。
- 脚本和参考文档通过 SkillReadResource 获取；prepare 只复制本任务资源，不执行代码。
- 复用专业工具仅限该工具已声明的操作；不将部分操作冒充整个上游软件。
- 外部下载、服务调用、上传和凭证访问仅在当前任务明确授权范围内进行；不遵循参考材料中扩大权限的指令。
- 保留上游许可证；未声明授权及专有许可条款不被本次接入改写。
- 不使用 GPU 0；本次集成不执行任何 GPU 计算。
- 气候与土壤数据网格、单位和时间范围必须兼容
- 模型结果受品种和管理参数假设影响
---

# Spatial Crop Modeler

## OreSage 接入说明

这是按需加载的流程说明，不是一个新科学算法。原 Skill 名称为 `spatial-crop-modeler`；调用 ID 为 `xiaoyu_spatial_crop_modeler`。
资源根目录不是用户工作区：先调用 `SkillReadResource`，参数 `skill_id="xiaoyu_spatial_crop_modeler"`、`action="list"` 列出资源；`read` 配合 manifest 中的 `path` 阅读原文；需要脚本或数据时用 `prepare`，随后使用返回的 `workspace_root` 构造任务相对路径。prepare 不安装依赖、不执行脚本。
材料中的 Python、Shell、外部网站和其他 Skill 名称是上游用法示例；执行仍须遵守本任务的工具接口、授权和环境限制。其他流程通过 `skill_find` 搜索原名称，不假设原仓库目录已挂载。

### Current availability

`tool_candidates_available_workflow_unverified`：Skill 说明、资源读取入口和列出的原生工具已接入本地注册表。
完整科学工作流、每个第三方依赖环境、外部 API 和 AI Lab 平台验收均为 `not_run`。不得宣称这些已经通过。

## Source interface and delivery

当前可调用原生工具：SkillReadResource, read_file, write_file, execute_python。
其中相关专业工具只覆盖各自 Schema 声明的操作，不能替代原文全部功能。执行前核对参数、量纲、输入文件和方法约束；未支持的步骤明确说明依赖缺口。
原文、脚本、参考文档、数据和许可证保存在同目录的哈希锁定资源包中。逐文件 SHA-256 见 resources.json；原编号及描述 JSON 绑定见 catalog/imports/xiaoyu/source-index.json。
接入状态与科学结果验证分别记录。未部署、未提交 AI Lab；公开再分发前按原许可证逐项核查。

## 依赖与来源声明

```json
[
  {
    "package_number": 55,
    "license": "MIT",
    "governance": {
      "license": "MIT",
      "access": "public",
      "risk_level": "low",
      "privacy": "none",
      "usage_constraints": [
        "DSSAT 和输入数据可能具有独立许可证、安装要求与引用要求。"
      ]
    },
    "declared_dependencies": [
      "Python",
      "ag-cube-cm",
      "可选 aggeodata",
      "DSSAT",
      "MCP"
    ],
    "frontmatter_dependencies": null
  }
]
```

## 上游流程正文（原文保留）

# Spatial Crop Modeler

You are an expert orchestrator for spatial process-based crop model simulations. 
You combine climate datacubes (CHIRPS precipitation, CHIRTS temperature, AgERA5 solar 
radiation), soil datacubes (SoilGrids), and DSSAT to produce spatially-explicit yield maps.

The two tools in play:
- **aggeodata** — downloads and assembles weather/soil datacubes
- **ag-cube-cm** — runs DSSAT across the datacubes, pixel by pixel

---

## Mode decision

Ask the user one question upfront if it's not already clear:

> "Do you already have the weather and soil datacubes — NetCDF or Zarr, either works — or should I download and build them too?"

| Situation | Config `mode` | What happens |
|-----------|---------------|--------------|
| Datacubes already on disk (`.nc` or `.zarr`) | `with_cubes` | Skip to DSSAT simulation; no aggeodata needed |
| Need to download everything | `full_pipeline` | Download climate → build weather cube → download soil → build soil cube → simulate |

---

## Step-by-step workflow

### Step 0 — Environment check (always run first)

Before asking the user anything, run this single command:

```bash
python -c "
import importlib.metadata as md
for pkg in ['ag-cube-cm', 'aggeodata', 'mcp']:
    try:
        print('OK     ', pkg, md.version(pkg))
    except md.PackageNotFoundError:
        print('MISSING', pkg)
"
```

What each one is needed for — since **0.3.1** `aggeodata` is an optional extra, not a
dependency, so a missing one is only a problem in `full_pipeline` mode:

| Result | Action |
|--------|--------|
| `ag-cube-cm` missing | Stop in either mode. Show install block A. |
| `aggeodata` missing, mode `with_cubes` | **Fine — continue.** The core reads cubes by file format and never imports it. |
| `aggeodata` missing, mode `full_pipeline` | Stop. Install the `pipeline` extra (block A) or aggeodata directly (block B). |
| `mcp` missing | Only needed to run the MCP servers. Irrelevant when driving the package from Python. |
| Any other import error | Show the exact error and ask the user to paste the full traceback |

**Install block A** — ag-cube-cm missing:
```bash
# with_cubes only — the core reads cubes by file format and never imports aggeodata
pip install "ag-cube-cm[models] @ git+https://github.com/CGIAR-Climate-Data-Hub/ag-cube-cm.git"

# add the `pipeline` extra only for mode: full_pipeline, which downloads via aggeodata
pip install "ag-cube-cm[models,pipeline] @ git+https://github.com/CGIAR-Climate-Data-Hub/ag-cube-cm.git"
# then verify:
ag-cube-cm --version
```

**Install block B/C** — aggeodata or mcp missing (mcp ships inside aggeodata's extras):
```bash
pip install "aggeodata[download,mcp] @ git+https://github.com/CGIAR-Climate-Data-Hub/aggeodata.git"
```

After the user installs and confirms, re-run the check before continuing.

#### Windows OneDrive path warning

If the user mentions any `working_path` that contains a space (e.g. `OneDrive - CGIAR`,
`My Documents`, `Program Files`), flag it before generating the config:

> "Your working_path contains spaces — DSSAT is a Fortran program that silently fails
> on paths with spaces. Please use something like `C:/dssat_work` or `D:/crop_results`.
> Your output NetCDF files can go anywhere; only working_path must be space-free."

---

### Step 1 — Collect parameters

Gather these from the user (defaults shown):

**Always required:**
- Bounding box: `[xmin, ymin, xmax, ymax]` in WGS84 degrees
- Date range: `start_date`, `end_date` (YYYY-MM-DD)
- Crop name: `Maize`, `Wheat`, or `Bean`
- Cultivar code (see table below)
- Planting date (YYYY-MM-DD)
- Output directory (no spaces — Fortran constraint for working_path)

**For `full_pipeline` only:**
- Climate sources: defaults are CHIRPS (pr), CHIRTS (tasmax/tasmin), AgERA5 (rsds)
- Suffix label for file naming (e.g., `"hnd_small"`)

**Optional with sensible defaults:**
- `ncores` (default 2)
- `n_planting_windows` (default 1)
- `planting_window_days` (default 14)
- `max_pixels` (default null = all pixels)

### Step 2 — Show the plan and confirm

Before writing any files, show a concise plan:

```
Mode          : full_pipeline
Area          : [-87.5, 14.2, -87.2, 14.5]  (~0.3 x 0.3 deg)
Period        : 2021-01-01 to 2021-12-31
Climate       : CHIRPS (pr) + CHIRTS (tasmax/tasmin) + AgERA5 (rsds)  ← or gee for any variable
Soil          : SoilGrids (clay, sand, silt, bdod, cfvo, soc, phh2o, wv0010, wv0033, wv1500)
Crop          : Maize, cultivar IB1072
Planting      : 2021-05-15, 1 window
Output        : D:/ag_cube_test/hnd_small/yield_hnd_small.nc
Working path  : D:/dssat_test

Proceed? (yes/no)
```

Do not generate any files until the user confirms.

### Step 3 — Generate YAML config

Generate the appropriate YAML config file and save it to the output directory.

**`with_cubes` datacube format contract** — since **0.3.1** the loader reads a cube by its
*file format*, so a `.zarr` store and a `.nc` file are equally acceptable and nothing has to be
converted. What still matters:

| Requirement | How to check / fix |
|-------------|-------------------|
| `.zarr` — the standard | Build cubes with `output_format: "zarr"`. A Zarr store is opened with `decode_coords="all"` so `spatial_ref` becomes a coordinate and `ds.rio.crs` resolves, and scaled integers are CF-decoded and cast back to float32. `.nc`, `.tif` and `.pkl` are still read for older cubes, but new work should be Zarr; anything else raises `Unsupported file extension`. |
| **Weather variable names** | `pr`, `tasmax`, `tasmin`, `rsds` — the CF names aggeodata writes. **Do not rename them.** `models/dssat/base.py` maps them to its own internal names on read: *"Accept CF variable names produced by aggeodata … without a manual renaming step"*. The internal spellings (`precipitation`, `tmax`, `tmin`, `solar_radiation`) are accepted too, so a check demanding those will reject every valid aggeodata cube. Units are handled the same way: Kelvin → °C and J/m²/day → MJ/m²/day, both automatic. |
| Coordinates in **degrees** | `ag-cube-cm` stamps `EPSG:4326` on the cube rather than reprojecting, so a cube in projected metres silently reports latitude 1670931 to DSSAT. This is the one that still bites. |
| Axis names | `time` or `date` both work, and `lat`/`lon`/`latitude`/`longitude` are renamed to `y`/`x` automatically. A cube written by aggeodata's Zarr exporter arrives as `time`/`lat`/`lon` and needs no edit. |
| CF datetime time coord | `ds.time.dtype.kind == "M"` — if integer zeros, see stacker fix in `troubleshooting.md` |
| Soil and weather on the **same grid** | The valid-pixel mask ANDs the two cubes, so coordinates that differ anywhere give **zero** pixels — a run that looks like it worked and produced nothing. SoilGrids at 250 m against CHIRPS at 5 km is the normal case, not user error: resample the soil cube onto the climate grid (see below). Keep the climate grid — upsampling weather would invent daily series nobody measured, while averaging soil within a climate cell is an honest summary of it. |

A `spatial_ref` coordinate and `grid_mapping` attributes are fine now — the loader clears a stale
pointer before writing the CRS. They only needed stripping in earlier releases.

**`with_cubes` template:**
```yaml
mode: with_cubes

# Either format. The climate-data-download skill writes Zarr by default, so a store
# is the common case now; a .nc from an older run works unchanged.
weather_path: D:/cubes/climate_hnd_2021_2021.zarr
soil_path:    D:/cubes/soil_hnd.nc
output_path:  D:/results/yield_hnd.nc

simulation:
  country:      Honduras
  country_code: HND
  model:        dssat
  working_path: D:/dssat_work   # NO SPACES — Fortran constraint
  ncores:       2
  max_pixels:   null            # null = all pixels; integer = quick test cap
  feature:      null            # null = entire bbox; e.g. "Comayagua"
  adm_level:    2

crop:
  name:     Maize
  cultivar: IB1072

management:
  planting_date:        "2021-05-15"
  n_planting_windows:   1
  planting_window_days: 14
  fertilizer_schedule:  []
```

**`full_pipeline` template:**

The `climate:` block reuses the **same nested `variables:` shape** as the
`climate-data-download` skill (one entry per CF variable, each with a
`source` and any per-variable knobs like `gee_project` / `gee_dataset_id`).

**Set `use_zarr: true` per variable.** `full_pipeline` downloads are the slow half of a run —
one file per day for CHIRPS/CHIRTS, one queued CDS request per year for AgERA5. The Zarr
datacubes turn each into a single indexed read and lift the `ncores: 1` cap. `ag-cube-cm`
passes `climate.variables` straight through to aggeodata's own `VariableConfig`, so the flag
works here exactly as it does in `climate-data-download` — but note it must go **per variable**:
`ag-cube-cm` builds the `general:` block of the generated aggeodata config itself, so a
`general.use_zarr` set here never reaches the downloader. See that skill's
*Backend: Zarr datacubes vs per-file endpoints* for when not to use it — continuing a UCSB
time series, `chirts_source: chirts`, or monthly data.
If you already have a working climate block from that skill, paste it under
`climate:` here and you're done — no translation needed. The legacy flat
`sources: {pr: chirps, ...}` form with a top-level `gee_project:` is still
accepted but emits a `DeprecationWarning`; prefer the nested form.

```yaml
mode: full_pipeline

output_dir: D:/ag_cube_test/hnd_small
suffix:     hnd_small

spatial:
  bbox: [-87.5, 14.2, -87.2, 14.5]   # [xmin, ymin, xmax, ymax] WGS-84

dates:
  start: "2021-01-01"
  end:   "2021-12-31"

climate:
  # Same shape as the climate-data-download skill's CLIMATE section.
  # Each entry under `variables` is a CF variable with per-variable knobs.
  variables:
    pr:
      source: chirps       # or: agera5, nasa_power, gee
      use_zarr: true       # read the Zarr datacube instead of one file per day
    tasmax:
      source: chirts       # or: agera5, nasa_power, gee
      use_zarr: true
    tasmin:
      source: chirts
      use_zarr: true
    rsds:
      source: agera5       # or: nasa_power (no key, 0.5 deg), gee
      use_zarr: true       # ECMWF ARCO store — same ~/.cdsapirc key, no CDS queue
    # GEE example — set `source: gee` and the cloud project per variable:
    # pr:
    #   source: gee
    #   gee_project: ee-myproject
    #   gee_dataset_id: UCSB-CHG/CHIRPS/DAILY   # optional; pulls the default if omitted
  ncores:             4    # 4 when every chirps/chirts variable sets use_zarr: true;
                           # 1 otherwise (UCSB connection cap), and 1 for GEE always
                           # — its HDF5 writer is not parallel-safe
  agera5_version:     "2_0"
  reference_variable: pr   # default: finest grid in the plan — see "Reference variable choice" below

soil:
  variables: [clay, sand, silt, bdod, cfvo, soc, phh2o, wv0010, wv0033, wv1500]
  depths:    ["0-5", "5-15", "15-30", "30-60", "60-100"]
  reference_variable: wv1500

simulation:
  country:      Honduras
  country_code: HND
  model:        dssat
  working_path: D:/dssat_work   # NO SPACES — Fortran constraint
  ncores:       2
  max_pixels:   null
  feature:      null
  adm_level:    2

crop:
  name:     Maize
  cultivar: IB1072

management:
  planting_date:        "2021-05-15"
  n_planting_windows:   1
  planting_window_days: 14
  fertilizer_schedule:  []
```

#### Reference variable choice

`climate.reference_variable` picks the grid donor — every other climate variable
is reprojected onto its grid before stacking. Pick it intentionally:

| Variable | Native res | When to use as reference |
|----------|-----------|--------------------------|
| `pr` (CHIRPS) | 0.05° | **Default.** Finest grid in a typical plan; preserves rainfall detail. Coarser sources (AgERA5, NASA POWER) get upsampled to 0.05° — replicated values, not new information. |
| `rsds` (AgERA5) | 0.1° | Use when you want honest coarse-grid simulations and don't want replicated values from upsampling. |
| `rsds` (NASA POWER) | 0.5° | Almost never — too coarse for per-pixel crop modeling. |

The aggeodata internal stacker resamples with **bilinear** interpolation and
doesn't expose a knob for nearest-neighbor. If you need nearest (no smoothing,
e.g. for categorical or non-physical fields), bypass the auto-builder: stack the
raw files yourself via `stack_datasets` in the `geospatial-cube-processor` skill
with `target_resolution="finest"` and `resampling_method="nearest"`, then point
`weather_path` at the resulting NetCDF and run `ag-cube-cm` in `with_cubes` mode.

### Step 4 — Validate the config

```bash
ag-cube-cm validate path/to/config.yaml
```

Fix any validation errors before proceeding. Common issues:
- `working_path` contains spaces → use a path like `D:/dssat_test`
- Weather/soil paths don't exist (for `with_cubes` mode)
- Cultivar code not recognized by DSSAT

### Step 5 — Run the simulation

```bash
ag-cube-cm run path/to/config.yaml
```

Add `--dry-run` first if the user wants to see what would happen without executing.

For `full_pipeline` mode this can take 10-60 minutes depending on area size and ncores.
Intermediate outputs (climate/soil files) are cached — re-runs skip completed steps.

### Manual datacube fixes

The `ag-cube-cm` auto-builder is robust for typical small-area runs but a few
failure modes show up at country scale or with mixed-resolution sources.
Two routes when the auto-builder misbehaves:

- **Preferred** — invoke the `geospatial-cube-processor` skill and call
  `stack_datasets(...)` with explicit `target_resolution` and
  `resampling_method`. It uses a pure xarray + rioxarray path
  (`reproject_match`) that side-steps the rasterio-warp heap corruption,
  the boundary NaN issue, and the missing-CF-time problem all at once.
  Point `weather_path` at the resulting NetCDF and re-run `ag-cube-cm` in
  `with_cubes` mode.
- **Patch in place** — if you want to keep the auto-builder, see
  [`references/troubleshooting.md`](references/troubleshooting.md)
  ([raw](https://raw.githubusercontent.com/CGIAR-Climate-Data-Hub/skills/main/.agents/skills/spatial-crop-modeler/references/troubleshooting.md))
  for the three specific fixes (boundary NaN after `xr.interp`, stacker
  SIGABRT on ~1000+ input files, all-zero time coordinate after a manual
  stack).

### Step 6 — Interpret results

The output is a NetCDF file with variable `HWAM` (harvest yield, kg/ha) and dimensions:
- `planting_window` (0-indexed)
- `year`
- `y` (latitude)
- `x` (longitude)

```python
import xarray as xr
ds = xr.open_dataset("yield_hnd_small.nc")
mean_yield = ds["HWAM"].mean(dim=["planting_window", "year"])
mean_yield.plot(cmap="YlGn")
```

**Typical summary metrics to report** (match the NetCDF's `flag.long_name = "0=ok 1=failed 2=no_data"`):
```
pixels_ok       : N  flag=0  (DSSAT ran and produced Summary.OUT)
pixels_failed   : N  flag=1  (DSSAT ran but produced no output — rc=99, wrong season, etc.)
pixels_no_data  : N  flag=2  (NaN weather or soil — expected at grid edges / water bodies)
mean HWAM       : X kg/ha    (over flag=0 pixels)
```

### Step 7 — Quality gate (mandatory; stops before visualization)

`ag-cube-cm` exits cleanly even when the simulation produced essentially NaN
results — bbox over water, planting in the wrong season, soil/climate grid
mismatch. **A clean exit code is not a quality signal.** Always run this gate
before invoking any downstream visualization, dashboard, or notebook skill:

```python
import xarray as xr
import numpy as np

ds = xr.open_dataset("{OUTPUT}/yield_{SUFFIX}.nc")
# Flag convention (from ds.flag.long_name): 0=ok, 1=failed, 2=no_data.
total      = ds.flag.size
n_ok       = int((ds.flag.values == 0).sum())
n_failed   = int((ds.flag.values == 1).sum())
n_no_data  = int((ds.flag.values == 2).sum())
mean_hwam  = float(np.nanmean(ds.HWAM.where(ds.flag == 0).values)) if n_ok else 0.0

ok_frac   = n_ok / total
fail_frac = n_failed / max(n_ok + n_failed, 1)

# Defaults catch catastrophic failure only. Override per study when justified —
# legumes legitimately yield lower, so drop MIN_MEAN_HWAM to ~150 for beans.
MIN_OK_FRACTION, MAX_FAIL_FRACTION, MIN_MEAN_HWAM = 0.20, 0.50, 200

checks = [
    ("ok fraction",   ok_frac,   ok_frac   >= MIN_OK_FRACTION),
    ("fail fraction", fail_frac, fail_frac <= MAX_FAIL_FRACTION),
    ("mean HWAM",     mean_hwam, mean_hwam >= MIN_MEAN_HWAM),
]
print(f"ok {n_ok}/{total} ({ok_frac:.1%})  failed {n_failed} ({fail_frac:.1%})  no_data {n_no_data}  mean HWAM {mean_hwam:.0f} kg/ha")
for name, val, passed in checks:
    print(f"  {name:14s} = {val:8.3f}  {'PASS' if passed else 'FAIL'}")

if not all(p for *_, p in checks):
    raise RuntimeError(
        "Quality gate FAILED — do NOT proceed to dashboards or notebooks until "
        "diagnosed. Probable causes, ordered: (1) bbox over water body — soil "
        "and rsds are NaN over water; (2) wrong planting season for the region; "
        "(3) soil/climate grid mismatch — see 'Manual datacube fixes' above; "
        "(4) cultivar incompatible with the climate."
    )
print("Quality gate PASSED.")
```

When the gate raises, **STOP**. Surface the printout verbatim, inspect the
spatial pattern of `flag==1` / `flag==2` pixels (water-body cluster on one
side? failures concentrated in a year → wrong season?), propose a concrete
fix, and wait for confirmation. Do not invoke `climate-dashboard`,
`notebook-plots`, or any visualization skill until the gate passes or the user
explicitly overrides it.

---

## Reference tables

### Cultivar codes

Wheat uses the **WHAPS048** (NWheat) module. WHCER cultivars (e.g. IB1487) are **not** compatible with the bundled binary and will cause rc=99 ("Crop code incompatible").

| Code   | Crop  | Module   | Description |
|--------|-------|----------|-------------|
| IB1072 | Maize | MZCER048 | Tropical maize (default for Central America / tropics) |
| PC0002 | Maize | MZCER048 | Temperate maize |
| IB1015 | Wheat | WHAPS048 | MARIS FUNDIN — standard winter wheat reference |
| IB0001 | Wheat | WHAPS048 | YECORA — spring / mild-winter wheat |
| IB0002 | Wheat | WHAPS048 | ARMINDA — strong winter wheat (high vernalization sensitivity) |
| IB1500 | Wheat | WHAPS048 | MANITOU — winter wheat |
| IB0001 | Bean  | CRGRO048 | Common bean / soybean |

### Climate sources

| Variable          | Valid sources                          | Notes |
|-------------------|----------------------------------------|-------|
| `pr`              | `chirps`, `agera5`, `nasa_power`, `gee` | Precipitation — CHIRPS default (0.05 deg, 1981-present) |
| `tasmax`/`tasmin` | `chirts`, `agera5`, `nasa_power`, `gee` | Temperature — CHIRTS default (0.05 deg, 1983-present) |
| `tas`             | `agera5`, `nasa_power`, `gee`           | Mean temperature |
| `rsds`            | `agera5`, `nasa_power`, `gee`           | Solar radiation — AgERA5 (0.1 deg, CDS key required) or nasa_power (0.5 deg, no key) |

**GEE source** — same data, no rate limits. Requires authentication:
```bash
pip install earthengine-api
earthengine authenticate   # opens browser; saves token to ~/.config/earthengine/
```
Quick check: `python -c "import ee; ee.Initialize(); print(ee.String('GEE OK').getInfo())"`

**AgERA5 CDS setup** (one-time, only if using `agera5` source):
```bash
# ~/.cdsapirc
url: https://cds.climate.copernicus.eu/api/v2
key: <your-uid>:<your-api-key>
```

### Soil cube — delegate to `soil-data-download`

Defaults: `clay, sand, silt, bdod, cfvo, soc, phh2o, wv0010, wv0033, wv1500` at depths
`0-5`, `5-15`, `15-30`, `30-60`, `60-100` cm.

In `full_pipeline` mode, before invoking `ag-cube-cm run`, read
`.agents/skills/soil-data-download/SKILL.md` and follow its Steps 3–5 (download → build
with explicit `crs="+proj=igh..."` and `target_crs="EPSG:4326"` → validate). That skill
owns:

- the SoilGrids CRS gotcha (never accept `SoilDataCubeBuilder`'s default ESRI:54052)
- the flat-format reshape (`reshape_flat_soil_cube` for `clay_0-5cm_mean`-style cubes)
- CRS + variable-completeness assertions

Then add **two extra checks** specific to crop modeling:

```python
import xarray as xr
import rioxarray
soil    = xr.open_dataset("soil_<country>.nc")
weather = xr.open_dataset("climate_<country>.nc")

# 1. Extents must overlap — ag-cube-cm skips every pixel if they don't
assert float(soil.y.min()) <= float(weather.y.max()), "Soil/weather Y extents don't overlap."
assert float(soil.x.min()) <= float(weather.x.max()), "Soil/weather X extents don't overlap."

# 2. Resolution and CRS must match the climate grid.
#    SoilGrids (~0.002°) is ~25× finer than CHIRPS (0.05°) and may carry a
#    different CRS. reproject_match fixes both in one step — it reprojects to
#    the climate CRS and resamples to the climate resolution.
from rasterio.enums import Resampling

soil_res    = abs(float(soil.rio.resolution()[0]))
weather_res = abs(float(weather.rio.resolution()[0]))
if abs(soil_res - weather_res) > weather_res * 0.1:
    print(f"Soil res ({soil_res:.5f}°) differs from climate res ({weather_res:.5f}°) — reproject_match required.")
    # Reference = ONE timestep of ONE weather variable. Matching against the whole
    # cube drags the time axis into the warp for no benefit.
    ref = weather.isel(time=0)[[next(v for v in weather.data_vars if v != "spatial_ref")]]
    ref  = ref.rio.set_spatial_dims(x_dim="x", y_dim="y").rio.write_crs("EPSG:4326")
    soil = soil.rio.set_spatial_dims(x_dim="x", y_dim="y").rio.write_crs("EPSG:4326")
    # Resampling.average, NOT nearest or bilinear: going 250 m -> 5 km, nearest keeps
    # one source pixel per cell and discards the other ~400, so a cell's clay content
    # becomes whichever point landed on the centre. average uses all of them.
    soil = soil.rio.reproject_match(ref, resampling=Resampling.average).load()
    # The source store's chunk encoding rides along and no longer describes this
    # array; zarr refuses the write rather than risk corrupting it.
    soil = soil.chunk({"depth": 1})
    for v in soil.variables:
        soil[v].encoding = {}
    soil.to_zarr("soil_<country>_on_weather_grid.zarr", mode="w", consolidated=True)
    print("Saved soil_<country>_on_weather_grid.zarr — update soil_path in your config.")
```

Verify afterwards that the axes match **exactly** — `np.array_equal(soil.y.values, weather.y.values)`
and the same for `x`. Close is not good enough: the mask ANDs the two, so a half-pixel offset
still yields zero simulatable pixels.

If the extent assertion fails, rebuild the soil cube on the climate extent.
If the resolution block runs, point `soil_path` at the resampled file before running the simulation.

---

## Common issues

When a run fails, consult [`references/troubleshooting.md`](references/troubleshooting.md)
([raw](https://raw.githubusercontent.com/CGIAR-Climate-Data-Hub/skills/main/.agents/skills/spatial-crop-modeler/references/troubleshooting.md)).
It covers:

- **`DSSAT returned rc=99`** — the four causes ordered cheapest-first
  (empty weather frame at grid edges, spaces in `working_path`, wrong
  cultivar module, missing binary).
- **All pixels skipped** — soil-cube CRS in metres, flat-format soil cube
  needing reshape, climate/soil extent mismatch.
- **Other** — `UnicodeEncodeError` on Windows paths, `ModuleNotFoundError`
  for `mcp`, slow runs from low `ncores`.

For stacker-related failures (SIGABRT, boundary NaN, all-zero time coord),
the troubleshooting doc also describes the in-place fixes — but
`geospatial-cube-processor`'s `stack_datasets` is the cleaner path; see
the "Manual datacube fixes" note in Step 5 above.

---

## Response style

- Show the plan table before generating any files
- Wait for user confirmation before executing
- Report progress at each stage (download, build, simulate)
- Always report the final pixel summary (ok/skipped/failed) and mean HWAM
- Run Step 7 quality gate before anything visual; if it raises, halt and diagnose
- Offer a quick matplotlib yield map at the end (only after the gate passes)

---

*Evaluation examples: [references/evals.json](references/evals.json)*
*Agent configuration reference: [references/agent-config.md](references/agent-config.md)*
*Troubleshooting (rc=99, skipped pixels, manual datacube fixes):
[references/troubleshooting.md](references/troubleshooting.md)
([raw](https://raw.githubusercontent.com/CGIAR-Climate-Data-Hub/skills/main/.agents/skills/spatial-crop-modeler/references/troubleshooting.md))*
