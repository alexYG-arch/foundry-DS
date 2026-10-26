# ADR-0003：M1.0 扁平模块 → M1.1 agents 包

- 状态：`IMPLEMENTED_M1_1`（M1.0 已落地；M1.1 包化已完成）
- 日期：2026-10-26
- 关联：`devtools/package_generic_release.py`、`docs/AGENT_ADAPTER_CONTRACT.md`

## 背景

去 Codex 方案 M1 原写“新增 `agents/` 包”。但当前通用发布器只支持扁平模块白名单：

- `MODULES` 每项映射到 `src/harness_foundry_factory/{name}.py`；
- import guard 只允许 `harness_foundry_factory.<module>`，相对导入只允许 `node.level == 1` 且 `node.module in MODULES`；
- 分发测试按 `MODULES` 逐个 import。

直接加包会同时改发布器、import guard、分发测试和包清单；在 M1 结构解耦尚未证明行为不变时，把两类风险混在一起不合适。

## 决策

1. **M1.0** 用三个扁平模块落地同一 seam：
   - `agent_contract.py`：`AgentCapabilities`、`AgentRequest`、`AgentAdapter`、`SandboxProvider` 协议与常量；
   - `agent_codex.py`：`CodexCliAdapter`、`CodexSandboxProvider`，委托现有 `coding_process` / `local_process`，行为逐字节不变；
   - 在 `build_runtime.py` 用它们替换直接 `CodexCodingRunner` / `CodexSandboxRunner` 调用。
2. 三个模块加入 `MODULES`，发布器与分发测试按现有机制覆盖；这样 M1.0 不会绕过发布检查。
3. **M1.1** 再把 `agent_*` 收拢为 `agents/` 包，并同步修改发布器（包目录复制、包内相对导入、import guard、分发测试）。M1.1 的退出证据是：发布包包含 `agents/`、旧扁平路径仍兼容、57 模块 / 888 项门禁全绿。
4. 本 ADR 不改变 ADR-0001/0002；Scope 版本与沙箱边界仍按那两份执行。

## 后果

- M1.0 的发布面风险最小；包化延迟一个 WP，但不会把发布器改造和适配器重构混在同一次变更。
- 计划文档里的 `agents/base.py` 路径在 M1.1 前不成立；评审时以本 ADR 为准。
- 新增模块必须通过 `check_release_source` 的分发测试；如果 `MODULES` 顺序或导入图检查失败，先修结构，不要放宽白名单。

## M1.1 结果（2026-10-26）

- 新增 `src/harness_foundry_factory/agents/{__init__,base,codex}.py`，包内导出与协议不变；
- `agent_contract.py` / `agent_codex.py` 保留为兼容 shim，旧导入仍有效；
- `build_runtime.py` 改为 `from .agents import ...` / `from .agents.base import AgentRequest`；
- `devtools/package_generic_release.py` 增加 `PACKAGE_MODULES`、包文件收集、包内相对导入与 `ALLOWED_TOP_LEVEL`；
- `portable.py` 的包自检已覆盖 `agents/`；跨包调用改用绝对导入，避免包内相对导入被解析成 `agents.coding_process`；
- 新增 `tests/test_agents_package.py`（3 项）并加入门禁；最终 **57 模块 / 888 项全过**。
