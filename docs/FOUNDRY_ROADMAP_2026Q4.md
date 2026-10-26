# Foundry 调整路线图（2026-10-26 起）

本路线图把审查报告的建议落成可执行阶段。三个原计划（去 Codex、设计 RSI、移动端实验）不再各自独立排期，统一按下面的门推进。

## 0. 约束

- 基线：`7fa713e`（1.0.0 / 协议 2.9 / `GENERIC_REVIEWED_BUILD`），公开门禁 53 模块 / 868 项。
- 单人估算约 108–133 人日；两人并行可压到约 3 个月，但依赖不允许全并行。
- 每个阶段都有退出证据；没有证据不进入下一阶段。
- 设计 RSI 的阶段不是审批门；移动端实验的预注册冻结是实验门，不是产品门。

## 1. 阶段与门

### 第 0 阶段：冻结与决策（1 周）

| 工作 | 产物 | 门 |
|---|---|---|
| 移动端预注册修订 | 70 次、1 主评审×2 轮、10 个 canary、v0.3 26 项、D11、基线重叠说明 | 三处硬冲突清零；`preregistration.json` 与计划/README/runbook 一致 |
| Scope 版本决策 | `ADR-0001` | 旧/新版本交叉测试规则写清 |
| 沙箱边界决策 | `ADR-0002` | “无 Codex 构建”不再被承诺；fixture E2E 与生产边界写清 |
| 发布/导入白名单 | `ADR-0003` + `MODULES` 变更 | 新模块进白名单，分发测试覆盖 |
| 总路线图 | 本文 | 预算、依赖、门一致 |

### 第 1 阶段：结构解耦与设计基础（4–6 周）

| 工作 | 产物 | 门 |
|---|---|---|
| M0 契约 | `docs/AGENT_ADAPTER_CONTRACT.md`、能力矩阵空表 | 契约评审通过；M1 按契约实现 |
| M1.0 seam | `agent_contract.py`、`agent_codex.py`，`build_runtime` 改走 adapter/provider | 行为不变；868+ 门禁全绿 |
| D0 案例库 | `design-cases/cases.jsonl`、`design-cases/README.md` | 至少 5 个真实/审查案例，阶段标签与证据齐全 |
| D1 DDR | `docs/design/DESIGN_DECISION_RECORD.md`、`design_record.schema.json` | 两个真实需求能填满；简单任务可只填 S1/S2/S5/S6 |
| D4a 检查 | `tools/check_design_record.py` + 9 个负例测试 | 只在现有 Plan/Scope 数据上判；不依赖 1.4 |

**当前进度（2026-10-26）**：M0、M1.0/M1.1、D0/D1/D4a、**M2.0 declarative profile loader** 已落盘；公开门禁 **60 模块 / 905 项全过**；M2.0 + M2.1a 已落盘（profile、None provider、fixture dispatch）；下一步 M2.1b controller E2E。

### 第 2 阶段：第二个适配器与 Scope 1.3（5–7 周）

| 工作 | 产物 | 门 |
|---|---|---|
| M2 声明式适配器 + fixture agent | **M2.0/M2.1a 已完成**：profile、probe、argv 渲染、事件/exit 映射、`NoneSandboxProvider`、fixture dispatch；**M2.1b 待做**：controller `advance-build` E2E | 无模型 E2E：实现→独立检查→接受；进程树无 codex（除 codex-sandbox） |
| M2.5 载体 profile | carrier profile、host_tools 能力名映射、capability `carriers` | carrier=claude-code 的 fixture 构建；不支持组合 fail-closed |
| M3 Plan/Scope 1.3 | 版本校验、Readback、错误码、兼容测试 | 旧 1.0–1.2 双跑；1.3 端到端；`scope_version` 缺失/错配拒绝 |
| M1.1 包化 | `agents/` 包 + 发布器/import guard/分发测试 | **已完成**：发布包含 `agents/`，旧 shim 不变，57/888 全绿 |

### 第 3 阶段：设计检查与规则（4–5 周）

| 工作 | 产物 | 门 |
|---|---|---|
| D4b 编译器检查 | carrier/规则/子 harness/缺口检查，接 1.4 结构化 DDR | 每条检查一个反例；只对新计划启用 |
| D5 停止原因 | 复用 M3 reason code，设计门/运行门文档化 | 每种停止原因一个测试；不增加人工确认 |
| D6 验证器设计 | 检查矩阵、负例要求、变异测试 | 至少 3 次变异；预言机独立性有证据 |
| D7 规则库 | rule record、优先级、冲突类别 | 规则冲突反例；无执行点规则降级为 Heuristic |

### 第 4 阶段：移动端实验与效果测量（6–9 周）

| 工作 | 产物 | 门 |
|---|---|---|
| 环境门 | iOS/Android `flutter build` + 模拟器启动 | 两个平台至少一个冒烟通过；版本写入 env.json |
| 设计变异 | 22 份材料、两轮评审、交叉复核 | SDR≥0.8、FPR≤0.1、κ≥0.7 |
| C0/C1/C2 + 故障 | 70 次运行、完整性 100% | 完整性 FAIL 即停；误接受/安全违规即停 |
| 盲评/复算/采纳 | 报告 + 采用记录 | 主指标 + 护栏；不足写 NOT_PROVEN |

移动端实验何时开始：如果要用 Codex，等环境门通过即可；如果要覆盖新适配器，必须等 M2/M3。两种结论不能合并样本。

### 第 5 阶段：效果与递归（每季度一个实验）

- E0/E1 指标基线、E2 对照协议、E3 第一个效果实验；E4/E5 审计；E6 结构递归；E7 治理。
- 不在 D 线没有改动时先跑 E 线；E 线不能替代 S 线门禁。

## 2. 依赖图

```text
第0阶段（决策/预注册/白名单）
  → M0 契约
  → M1.0 seam（行为不变）
      → M1.1 包化
      → M2 第二适配器 + none provider
          → M2.5 载体 profile
      → M3 Scope 1.3
          → D4b
  → D0 案例 → D1 DDR → D4a（可并行于 M1）
  → D5/D6/D7（D4b 之后）
  → 移动端环境门 → 预注册冻结 → 70 次
  → E 线
```

## 3. 共享文件与冲突

以下文件会被多条线同时改，必须串行或先合并：

- `src/harness_foundry_factory/build_runtime.py`
- `src/harness_foundry_factory/build_plan.py`
- `src/harness_foundry_factory/build_entrypoint.py`
- `devtools/package_generic_release.py`
- `tests/test_generic_distribution.py`
- `docs/GENERIC_BUILD_PLAN.md` / `GENERIC_BUILD_CLI.md`
- `resources/generic_release/SKILL.md`

## 4. 当前状态与下一步

- 已完成：ADR-0001/0002/0003、M0 契约、M1.0 seam（两个模块 + 5 个测试）、D0 六案例、D1 模板/schema、D4a 工具 + 9 个测试、移动端预注册/检查表/README/runbook/材质修订。
- 已通过：完整 58 模块 / 897 项门禁（`build/source-checks-m2c.json`）。
- 已装：标准 Flutter 3.35.3、JDK 21、Android platform-tools/platform/build-tools、Codex CLI 0.164.0。待环境：Xcode license（需用户 sudo）、CocoaPods、Android AVD、首次 Gradle 构建。
- 下一步：M2.1 fixture agent + `none` provider + 无模型 E2E；移动端先做设计变异层，不急着冻结 70 次。
