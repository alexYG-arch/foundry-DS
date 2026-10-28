# 文档索引：现行规范与历史记录

`docs/` 中同时存放现行规范和大量 epoch/repair/review 历史记录。本索引说明哪些文件是
**现行权威**，哪些是**历史记录**；状态与门禁数字只在 [`STATUS.json`](STATUS.json) 维护，
其他文档引用它而不重复书写。

## 现行规范（新建 Harness 与源码工程以这些为准）

| 文档 | 作用 |
| --- | --- |
| [`GENERIC_BUILD_PLAN.md`](GENERIC_BUILD_PLAN.md) | 搭建文档与人工 Review 政策；所有新建的入口 |
| [`GENERIC_BUILD_CLI.md`](GENERIC_BUILD_CLI.md) | 公开 Build 命令、request 形状、Readback、`read-build --control-view`、返修/纠正入口 |
| [`GENERIC_BUILD_RUNTIME.md`](GENERIC_BUILD_RUNTIME.md) | 控制器运行合同：授权、attempt、独立验收、恢复、TRUSTED_HOST 下的实际保证 |
| [`GENERIC_SOURCE_INTAKE.md`](GENERIC_SOURCE_INTAKE.md) | 完整来源读取与绑定 |
| [`ACCEPTANCE_CONTRACT_ALIGNMENT.md`](ACCEPTANCE_CONTRACT_ALIGNMENT.md) | 公开验收合同与检查器对齐、失败路由 |
| [`HARNESS_DESIGN_GUIDE.md`](HARNESS_DESIGN_GUIDE.md) | 从需求设计可交付 Harness 的六个问题 |
| [`AGENT_ADAPTER_CONTRACT.md`](AGENT_ADAPTER_CONTRACT.md) | Plan/Scope 1.3、agent transport、verifier contract、assurance 标签 |
| [`decisions/ADR-0004-CONTRACT-INDEPENDENCE.md`](decisions/ADR-0004-CONTRACT-INDEPENDENCE.md) | 独立性基线决策：sandbox 是可选加固 |
| [`FOUNDRY_ROADMAP_2026Q4.md`](FOUNDRY_ROADMAP_2026Q4.md) | 路线图 v3；状态字段引用 `STATUS.json` |
| [`A3_A4_CLOSURE.md`](A3_A4_CLOSURE.md) | 控制库读路径、ControlViewV2、A3/A4 闭合边界 |
| [`A3_SOURCE_DEDUP.md`](A3_SOURCE_DEDUP.md) | 来源去重格式、源复用的 CAS 语义、离线迁移 |
| [`A4_CURRENT_VIEW.md`](A4_CURRENT_VIEW.md) | RSI 当前视图与历史交接 |
| [`CLEAR_COMMUNICATION.md`](CLEAR_COMMUNICATION.md) | 面向人的表达规范 |
| [`CAPABILITY_REFERENCE.md`](CAPABILITY_REFERENCE.md) | 能力包接口 |
| [`RSI_ADOPTION.md`](RSI_ADOPTION.md)、[`RSI_CASE_INTAKE.md`](RSI_CASE_INTAKE.md)、[`RSI_REVIEW_AND_TDD.md`](RSI_REVIEW_AND_TDD.md)、[`RSI_WIKI.md`](RSI_WIKI.md)、[`RSI_DELIVERY.md`](RSI_DELIVERY.md) | 持续改进工具链 |
| [`DEVELOPMENT_SPECIFICATION.md`](DEVELOPMENT_SPECIFICATION.md) | 源码维护依赖与完整回归步骤 |
| [`USER_GUIDE.md`](USER_GUIDE.md)、[`CHAT_USAGE.md`](CHAT_USAGE.md) | 使用说明 |

现行决策记录：`decisions/ADR-0001`（Scope 版本化）、`ADR-0003`（agents 包化）、`ADR-0004`（独立性基线）。
`ADR-0002`（sandbox 硬前提）已被 `ADR-0004` 取代，保留为历史。

## 历史记录（只读背景，不是现行规则）

以下文件记录已完成或已退役的工作，阅读时以日期和“状态”字段为准，不要据此推断当前路由或权限：

- Start Package / Candidate 路线（已于 2026-09-20 退役）：`ARCHITECTURE.md` 的历史章节、
  `START_PACKAGE_*.md`、`HARNESS_FOUNDRY_V2_9_*`、`HARNESS_FOUNDRY_V3_0_*`、`V2_9_*`、`v2_9_epoch9/`、
  `v2_9_release_closure/`、`archive/`。
- 修复与评审记录：`FOUNDRY_EPOCH*`、`FOUNDRY_*_REPAIR_*`、`FOUNDRY_RSI_WP*`、`FOUNDRY_UPDATE_*`、
  `FOUNDRY_UPGRADE_*`、`BUILD_QUALITY_*`、`reviews/`、`releases/`、`GITHUB_SKILL_VIDEO_EXPLAINER_*`。
- 规划文稿：`FOUNDRY_GENERIC_CODEX_HARNESS_*`、`FOUNDRY_RUNTIME_RELIABILITY_*`、`EXECUTION_STARTUP_REPAIR_PLAN.md`、
  `RELEASE_ACCEPTANCE_BUILD_DOCUMENT_v0_1.md`、`FOUNDRY_GITHUB_RELEASE_ACCEPTANCE_ADDENDUM_v0_1.md`。

这些文件暂不移动目录：打包白名单（`portable.py`、`devtools/package_generic_release.py`）、README 与测试
按当前路径引用它们，移动属于单独的工程变更。新增历史记录应放入 `archive/` 或 `reviews/`。

## 状态的单一来源

[`STATUS.json`](STATUS.json) 保存路线图状态、规格状态、门禁语义与最近一次本地门禁结果。
`python3 tools/update_status.py <gate-report.json>` 把 `tools/check_release_source.py --report`
的输出写入其中；路线图/规格的状态字段是人工决定，不由工具改写。
