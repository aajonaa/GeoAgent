---
id: doc-1
title: 项目看板使用指南
type: guide
created_date: '2026-10-10 06:14'
updated_date: '2026-10-10 06:14'
---
# GeoAgent 项目看板

这里管理开发工作，不是 Agent 专业工具，不接入 LangGraph。任务卡是工作清单，版本文档记录实际交付。未经确认的建议不代表已排期或正在实施。

## 本机使用

在 GeoAgent 仓库目录执行：

~~~powershell
.\scripts\project-board.ps1
.\scripts\backlog.ps1 task list --plain
.\scripts\backlog.ps1 task create '简洁的任务标题' --ac '可观察的验收条件'
.\scripts\backlog.ps1 task edit GEO-2 -s 'In Progress'
~~~

浏览器地址：http://127.0.0.1:6420/ 。终端前台启动时，Ctrl+C 停止；本次试用由隐藏窗口启动，关闭浏览器不会停止服务。仅监听本机，不向局域网或公网暴露。

CLI 固定为 backlog.md 1.53.0，安装在 %LOCALAPPDATA%/GeoAgent/backlog-md/1.53.0，不放入 Python 运行时，也不更改全局 npm 配置。另一台 Windows 电脑需要 Node.js，然后安装：

~~~powershell
npm install --prefix "$env:LOCALAPPDATA\GeoAgent\backlog-md\1.53.0" --save-exact --ignore-scripts --no-audit --no-fund backlog.md@1.53.0
~~~

随后在该电脑的仓库目录执行启动脚本。本次仅本机试用，不提供多人登录服务，不设置开机启动。

## 看板状态

- To Do：待确认或尚未实施。
- In Progress：正在实施，或者实现后等待验收；等待原因写在备注中。
- Done：该任务承诺的范围已完成且有记录；不自动意味着已发布或已部署。
- proposed 标签：建议项，用户确认后再实施。

## 每项工作的最少记录

记录问题、任务编号、验收条件、实现摘要、测试范围和报告、提交或 PR 链接，以及发布/部署状态。没有运行的测试明确写“未运行”。

涉及版本时，用里程碑组织任务，并创建一份“发布与部署记录模板”的副本。至少区分：

| 字段 | 意义 |
| --- | --- |
| coded | 代码已实现，不代表测试通过 |
| verified | 指定范围的检查已通过，附证据 |
| released | tag / GitHub Release 已发布，附链接 |
| deployed | 具体环境已切换到记录的构建，附时间和构建身份 |

通过 CLI 或看板 UI 维护任务和文档，避免破坏元数据。开始较大的工作前先搜索已有任务。

## 安全和权限

采用文件模式：关闭远程 Git 操作、自动提交与跨分支扫描。backlog/ 内的 Markdown 和配置可以在用户允许后随代码提交，本次不自动 commit 或 push。

不存 API Token、密码、完整环境变量或敏感研究数据。任务状态变更不自动触发测试、部署或模型调用。
