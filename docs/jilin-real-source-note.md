# 夹皮沟真实数据核验记录 / Jiapigou source record

本记录由 2026-10-04 实际下载的 USGS MRDS 原始 GeoJSON、Sentinel-2 STAC item、产品 XML 和 sources.json 确定性整理；是数据来源说明，不是论文、独立野外测量或新矿床发现。原件与 SHA-256 清单保留在 A100 的 geoagent-data/jilin-real-20261004 中。

## 矿点 / Mineral record

夹皮沟（Jiapigou Gold Operations）的 USGS MRDS 历史矿点编号 dep_id 为 10206853。原始经纬度为 127.48668999982105、42.87101999967178。AU 编码解读为 Gold；China 是由地理位置补充，不是接口原始字段。dev_stat 为 Unknown；grade 字段 D 不应解释为矿石品位。该记录只有一个矿点，并不是吉林省全部金矿清单。原始数据文件为 usgs-jiapigou-original.geojson。

## 卫星日期与范围 / Acquisition date and coverage

夹皮沟（Jiapigou）真实 Sentinel-2 Level-2A 影像的获取时间为 2021-09-02T02:25:51.024000Z，场景 ID 为 S2A_MSIL2A_20210902T022551_R046_T52TCN_20210902T170736。The acquisition date is 2 September 2021. The crop covers only 512 by 512 pixels at 10 m resolution, a 5.12 km square near the historical database point, not all Jilin gold mines or an official mine concession.

夹皮沟 Sentinel-2 数据只覆盖历史矿点附近约 5.12 km 的正方形区域，不覆盖吉林全省矿点。It is a local Jiapigou crop, not a provincial inventory. Its CRS is EPSG:32652. The crop is not a legally surveyed mine boundary. 不能用它推断未发现的金矿的位置、矿石品位、储量或扰动成因。

## 反射率定标 / Reflectance calibration

夹皮沟（Jiapigou）这景 Sentinel-2 的处理基线为 03.00，产品 XML 的 BOA_QUANTIFICATION_VALUE 为 10000。地表反射率为 DN × 0.0001，offset 为 0，单位为无量纲。For this Jiapigou Sentinel-2 scene, the reflectance scale is 0.0001 and the offset is 0.0, as recorded in the actual product metadata XML. 不得混用 Landsat 的缩放参数或其他 Sentinel-2 基线的偏移量。

## 波段、质量与解释限制 / Bands and limitations

jiapigou-sentinel-rgbnir.tif 的波段顺序是 B04 red、B03 green、B02 blue、B08 NIR。jiapigou-clear-mask.tif 仅保留 SCL 的 4、5、6 类，20 m 分类以 nearest 方法对齐到 10 m 网格。有效像元为 256952，排除 5192；质量掩膜并不保证所有像元绝对无云。NDVI 和 NDWI 描述地表光学响应，不能单凭这些指数证明金矿成矿、品位或储量。

## 可追溯原件 / Source artifacts

USGS 官方接口为 https://energy.usgs.gov/arcgis/rest/services/Hosted/Mineral_Resource_Data_System/FeatureServer/0/query 。卫星元数据来自 https://planetarycomputer.microsoft.com/api/stac/v1 的 sentinel-2-l2a 集合。原始 sentinel-item.json、product-metadata.xml、GeoJSON、GeoTIFF、SCL 与 sources.json 都保留；读取该说明不等于当前 Agent 已重新联网验证来源。接收方仍需核对实际文件、版本、哈希及使用条件。
