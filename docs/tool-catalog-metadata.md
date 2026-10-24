# 工具目录元数据规范

工具的执行契约和资产元数据分开管理。`ToolDefinition` 负责运行时调用；
`catalog/registry.json` 的 `registration_metadata` 负责来源、版本、环境和生命周期。

## 来源与协议

`provider`、`license`、`asset_version` 和 `source_commit` 已知时填写，未知时可以为
`null`，但应保留在 `pending_fields` 中。`asset_version` 是发布版本或包版本；
`source_commit` 是实际使用的源码提交，两者不表示运行时环境。

`official_protocol` 始终存在：

```json
{
  "applicability": "applicable | not_applicable | unknown",
  "name": "OGC API - Features",
  "version": "1.0"
}
```

`not_applicable` 表示工具不实现官方协议；`unknown` 表示适用性或版本尚未确认。
`applicable` 时应填写协议名称和版本。

## 运行环境

`runtime` 描述执行环境，不描述源码来源：

```json
{
  "python": "3.12",
  "dependency_lock": "requirements-tool.lock",
  "environment_version": "geoagent-professional-2026.10"
}
```

## 生命周期

`lifecycle` 将登记、工具验证、工作流验证、平台验证和发布状态分开：

```json
{
  "registration": "candidate",
  "contract_validation": "not_run",
  "unit_validation": "not_run",
  "workflow_validation": "not_run",
  "platform_validation": "not_run",
  "release_status": "draft"
}
```

`workflow_validation` 记录关联 Skill 的流程验证，不能替代单工具验证。
旧字段保留用于兼容；新工具应同时填写新版结构。
