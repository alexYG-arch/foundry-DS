> **2026-10-26 补充**：Scope 1.3 的字段以 `docs/AGENT_ADAPTER_CONTRACT.md` v2 为准；`codex_executable` 只保留给 1.0–1.2 只读兼容，新 1.3 不再要求。

# ADR-0001：Scope 版本化

- 状态：`ACCEPTED_FOR_M0`（决策已定，代码未实现）
- 日期：2026-10-26
- 关联：`docs/AGENT_ADAPTER_CONTRACT.md`、`Harness_Foundry_升级方案_多智能体适配与RSI自升级.md` §3.3
- 决策者：维护者（本轮调整）

## 背景

当前 Plan 有 `schema_version`（1.0/1.1/1.2），Scope 没有版本字段，但 `_validate_scope` 用精确字段集合校验，且 `codex_executable` 是所有 Scope 的必填项。去 Codex 方案引入 `agents`、`sandbox`、`model_selection` 后，必须区分旧 Scope（无字段）与新 Scope，否则旧控制库、恢复和 `read-build` 会出现两套语义。

## 决策

1. 新增 `scope_version` 字段，取值 `"1.0"`（旧）与 `"1.3"`（新，配合 Plan 1.3）。
2. 旧 Scope 没有 `scope_version` 时，仅在 Plan `schema_version <= 1.2` 下按 `"1.0"` 读取；Plan 1.3 必须显式 `scope_version="1.3"`，缺失即拒绝。
3. 校验分支以 **Plan 版本 + Scope 版本的一致性**为准：
   - Plan 1.0–1.2 → 只接受 Scope 1.0（或缺失）；
   - Plan 1.3 → 只接受 Scope 1.3；
   - 其他组合 fail-closed，错误码 `BUILD_SCOPE_VERSION_UNSUPPORTED`。
4. 旧持久化事件不改写、不迁移；`read-build` 对缺失字段显示 `1.0`，但只在读取时补默认值，不写回。
5. `scope_version` 进入 `prepare-build-authorization` 的校验与 Readback；`approve-build-authorization` 只接受已校验的 prepared Scope。

## 不做什么

- 不把 `scope_version` 加进 Plan 1.0–1.2 的必填字段。
- 不做自动迁移，不重写 SQLite。
- 不把 Scope 版本硬编码成“等于 Plan 版本”而省略字段；两者分开，便于未来独立演进。

## 后果

- 需要新增旧/新版本交叉测试：旧 Plan+旧 Scope、旧 Plan+新 Scope（拒绝）、新 Plan+旧 Scope（拒绝）、新 Plan+新 Scope（接受）。
- M1 只做结构解耦时，Plan 1.2 的 `CODEX` 仍映射到 codex 适配器；`scope_version` 的强制校验在 M3 打开，M1 可先写入但不改变旧路径。
- 兼容性证据必须来自真实旧库的只读副本，不能用合成库冒充。
