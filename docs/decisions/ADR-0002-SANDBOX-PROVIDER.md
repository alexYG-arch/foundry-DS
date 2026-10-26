> **2026-10-26 更正**：本 ADR 的“生产仍需 codex-sandbox”只适用于旧 1.2 兼容路径。新路线（`Harness_Foundry_升级方案_v2_DeepSeek与无Codex.md`）要求真实 macOS seatbelt / Linux bwrap；`none` 仅测试；不能再用“Codex sandbox 仍是依赖”解释无 Codex 构建。
>
> 本 ADR 的 M2.1a `NoneSandboxProvider` 仍有效，但只作 fixture；不是生产替代。

# ADR-0002：沙箱提供者与“去 Codex”的边界

- 状态：`SUPERSEDED_BY_PLAN_V2`（本 ADR 允许 Codex sandbox 继续作为依赖；新方案要求无 Codex 的 seatbelt/bwrap）
- 日期：2026-10-26
- 关联：`docs/decisions/ADR-0001-SCOPE-VERSIONING.md`、`Harness_Foundry_升级方案_多智能体适配与RSI自升级.md`、`Harness_Foundry_升级方案_补充_载体解绑与设计RSI.md`
- 决策者：维护者（本轮调整）

## 背景

“去 Codex”当前只覆盖实现者：所有非 `CODEX` Workpack、LOCAL 命令和验证命令仍由 `CodexSandboxRunner` 启动，`codex_executable` 是所有 Scope 的必填项，网络策略走 Codex native proxy。即使接入 Claude Code 适配器，没有 Codex 的机器仍无法准备 Scope、跑 LOCAL/验证。

## 选项

| 选项 | 内容 | 代价 |
|---|---|---|
| A | 承认 Codex 二进制是运行时依赖，只做可插拔实现者 | 最小；但不能宣称“无 Codex 构建” |
| B | 立即实现第二个沙箱（macOS seatbelt / bwrap） | 大；需要网络策略、权限 profile、观测、跨平台测试 |
| C | M1 抽象 provider，保留 codex-sandbox；M2 增加仅测试用的 `none` provider，生产仍要求沙箱 | 中；能跑无模型 E2E，但不能跑“无 Codex 的生产构建” |

## 决策

采用 **C**，并把“去 Codex”的验收边界改清楚：

1. **M1**：抽出 `SandboxProvider` 协议与 `CodexSandboxProvider`；行为不变，`codex-sandbox` 仍是默认 provider。
2. **M2**：增加 `NoneSandboxProvider`，只允许同时满足以下条件时使用：
   - Scope 显式 `sandbox.provider="none"`；
   - 适配器 `agent.sandbox="NONE"`；
   - Scope 显式 `allow_unsandboxed_agent=true`；
   - 计划中至少有一个非 `CODEX` 的 fixture Workpack；
   - Readback 显示 `sandbox_enforcement: NONE`。
   否则 fail-closed，错误码 `BUILD_SANDBOX_UNAVAILABLE`。
3. **生产**：非 Codex agent 要么使用 `codex-sandbox`（此时 Codex 二进制仍是依赖），要么声明并实现原生沙箱（`agent.sandbox="NATIVE"`）；没有第三种生产路径。
4. **网络**：`none` provider 不提供网络隔离；使用 `none` 的 Scope 只能声明 `network.mode="NONE"`，否则拒绝。`codex-sandbox` 继续使用现有 native proxy 语义。
5. **验收**：
   - “无 Codex 的 fixture E2E”是 M2 退出证据，用 `none` provider，不冒充生产；
   - “无 Codex 的生产构建”不在 M2/M3 承诺内；需要第二个真实沙箱 provider，列入 M4 之后。
6. `SandboxProvider` 协议至少包含 `provider_id`、`probe()`、`wrap(argv, profile)`，并承载网络/权限 profile 的声明；具体字段在 M0 契约中冻结。

## 后果

- 载体解绑件 §1.6 第 2 条“没有安装 Codex 的机器跑公开门禁全绿”改为“跑 fixture E2E（`none` provider）全绿”，并明确它不等于生产可用。
- 计划 M2 的“第二个适配器”可以落地；但文档必须写“Codex 仍是可选沙箱依赖”，不能写“完全去 Codex”。
- 第二个真实沙箱 provider（seatbelt/bwrap）作为独立 WP，需重新评估网络、权限和跨平台证据，不在本阶段偷偷降级。

## M2.1a 结果（2026-10-26）

- `agents/sandbox_none.py` 已实现 `NoneSandboxProvider`，仅 `allow_unsandboxed_agent=true` + `network NONE` 时 probe PASS；
- `DeclarativeAdapter.run()` 必须显式传入 provider/executable，否则 `NotImplementedError`；
- fixture dispatch 已验证会写声明产物，且 provider 不声明 acceptance；
- controller `advance-build` E2E 仍是 M2.1b；生产 provider 未变。
