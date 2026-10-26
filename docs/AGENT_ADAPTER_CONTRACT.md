# Agent Adapter Contract（M0）

- 版本：`AGENT_ADAPTER_CONTRACT_V1`
- 状态：`M2_0_PROFILE_IMPLEMENTED`（M0 契约；M1.0/M1.1 包已落地；M2.0 declarative profile 已落地，dispatch 待 M2.1）
- 日期：2026-10-26
- 关联：`ADR-0001`（Scope 版本）、`ADR-0002`（沙箱边界）、`docs/CODING_COMMAND_PROTOCOL.md`
- 非目标：本契约不定义模型调用协议、不实现第二个真实沙箱、不改变 Plan 1.0–1.2 语义。

## 0. 不可违反的约束

1. 模型/agent 输出永远不是 `ACCEPTED`；验收只由独立检查产生。
2. 没有声明或探测失败的 adapter/provider 一律 fail-closed，不猜默认。
3. 原始字节永远保留；归一化事件是派生数据，不能覆盖原始 capture。
4. usage 拿不到就记 `UNKNOWN`，不能显示为 0。
5. 没有显式 `allow_unsandboxed_agent=true` 时，不允许 `sandbox.provider="none"`。
6. 旧计划（1.0–1.2）继续走旧映射；新能力只对 1.3 生效（见 ADR-0001）。

## 1. 两个接口

```python
@dataclass(frozen=True)
class AgentCapabilities:
    adapter_id: str          # "codex-cli" / "fixture-agent" / "claude-code" / "generic-cli"
    adapter_version: str     # 契约版本，不是 agent 版本
    prompt_transport: str    # "stdin" | "arg" | "file"
    events: str              # "jsonl" | "text"
    usage: str               # "REPORTED" | "UNKNOWN"
    defaults: str            # "READABLE" | "EXPLICIT_ONLY"
    handoff: bool            # 是否支持人工接手后一次性交回
    sandbox: str             # "PROVIDER" | "NATIVE" | "NONE"

class AgentAdapter(Protocol):
    capabilities: AgentCapabilities
    def probe(self, executable: Path) -> dict: ...
    def run(self, request: "AgentRequest", *, before_dispatch, observation=None,
            cancellation_reason=None) -> dict: ...

class SandboxProvider(Protocol):
    provider_id: str          # "codex-sandbox" | "none" | 未来 "macos-seatbelt"/"bwrap"
    def probe(self) -> dict: ...
    def run(self, command, *, before_dispatch, **hooks) -> dict: ...   # M1.0
    # M2 target: def wrap(self, argv: list[str], profile: dict) -> list[str]: ...
```

`AgentRequest` 至少携带：`command`、`prompt`、`model`、`reasoning_effort`、`model_policy`、`model_service`、`model_defaults_source`。M1.0 用现有 `CodingCommand` 作为 `command`，不重写参数语义；`observation`/`cancellation_reason` 通过 `**hooks` 透传。

> M1 实现说明：M1.0 用扁平 `agent_contract.py` / `agent_codex.py`；M1.1 已收拢为 `agents/` 包，扁平模块保留为兼容 shim。`wrap()` 仍是 M2 目标，M1 用 `run()` 保持行为不变。

## 2. probe 契约

`probe()` 必须真的执行一次受控探测，不能只判断路径存在：

- 返回 `{"status": "PASS"|"FAIL", "adapter_id", "adapter_version", "executable", "executable_sha256", "evidence"}`；
- 失败返回稳定原因码 `ADAPTER_PROBE_FAILED`，并带原始 stdout/stderr 摘要（不入敏感信息）；
- probe 不获得额外权限、不写项目文件、不调用模型；
- Codex CLI 的 probe 继续检查 `exec --help` 的必需 flag（`--ignore-user-config`、`--strict-config`、`--ephemeral`、`--json`、`--cd`、`stdin`），行为与现状一致。

## 3. 事件归一化

```json
{"seq": 7, "type": "TURN_STARTED|MESSAGE|TOOL_CALL|TOOL_RESULT|USAGE|RETRY|TURN_COMPLETED|TURN_FAILED|UNKNOWN",
 "raw_type": "item.completed", "raw_ref": "stdout.bin#7", "fields": {}}
```

规则：
- 未知事件 → `UNKNOWN` 计数并保留；连续超限或协议错乱 → `ADAPTER_PROTOCOL_ERROR`，失败闭合；
- 原始字节写入 observation，归一化事件只引用 `raw_ref`；
- 事件顺序按 `seq`，不按到达时间；
- 适配器不得把“进程退出 0”直接翻译成 `TURN_COMPLETED`；结束原因由 adapter 的 `classify` 输出，控制器仍以独立检查为准。

## 4. 失败码（稳定）

| 码 | 含义 |
|---|---|
| `ADAPTER_PROBE_FAILED` | 可执行文件/接口/必需 flag 不可用 |
| `ADAPTER_PROTOCOL_ERROR` | 事件流无法解析或连续未知超限 |
| `ADAPTER_USAGE_UNKNOWN` | 无 usage，预算降级为尝试次数 + 墙钟 |
| `ADAPTER_UNSUPPORTED_CAPABILITY` | 声明了宿主不支持的能力（如 handoff/defaults） |
| `SANDBOX_UNAVAILABLE` | provider 不可用或禁止的 `none` 组合 |
| `SANDBOX_NETWORK_UNSUPPORTED` | `none` 下声明了网络 |
| `AGENT_HANDOFF_INVALID` | handoff 字段/模式不合法 |

旧 `CODEX_*` 原因码保留别名，不要求历史记录改写。

## 5. 能力矩阵（M0 空表，M2 填满）

| 能力 | codex-cli | fixture-agent | claude-code | generic-cli |
|---|---|---|---|---|
| prompt_transport | stdin | stdin | 待 probe | 声明式 |
| events | jsonl | jsonl | 待 probe | 声明式 |
| usage | REPORTED | UNKNOWN（测试可固定） | 待 probe | 声明式 |
| defaults | READABLE | EXPLICIT_ONLY | 待 probe | EXPLICIT_ONLY |
| handoff | true | false | 待 probe | 声明式 |
| sandbox | PROVIDER | NONE（仅测试） | PROVIDER/NATIVE 待定 | 声明式 |
| 状态 | M1.1 包内实现 | M2 | 未实现 | M2 声明式 |

“待 probe”不是“支持”；没有 probe 证据的能力一律按不支持处理。

## 6. Scope/Plan 映射

- Plan 1.3：`executor ∈ {AGENT, LOCAL}`，`agent.adapter` 必须在 Scope `agents` 中声明并可 probe；
- Scope 1.3：`agents`、`sandbox`、`model_selection`、`usage_accounting`，版本规则见 ADR-0001；
- 旧 Plan 1.0–1.2：`CODEX` 映射到 `codex-cli`，`codex_executable` 同时作为 provider executable；不写回旧事件；
- `sandbox.provider="none"` 只在 ADR-0002 条件下允许。

## 7. 测试义务（M1/M2 退出证据）

1. golden fixture：当前 Codex 事件流（从现有测试导出）归一化后逐条一致；原始字节不变。
2. 负向：可执行缺失、probe 失败、未知事件超限、无 usage、协议错误、沙箱不可用、`none`+network 组合。
3. 行为不变：M1.1 下 1.2 计划端到端结果与改造前一致；901 门禁全绿。
4. 无模型 E2E：fixture agent 写出声明产物，`advance-build` 完成实现→独立检查→接受；进程树中无 `codex`（除显式 `codex-sandbox`）。
5. Readback 必须显示 `adapter_id`、`adapter_version`、`sandbox_provider`、`usage_source`；`UNKNOWN` 不能显示成 0。

## 8. 版本与兼容

- 本契约版本 `1`；字段新增走 minor，删除/改义走 major；
- 声明式 profile 的 `schema_version` 独立于本契约；
- adapter 版本是契约实现版本，不是 Codex/Claude 的产品版本；
- 任何“支持任意 agent”的声明，必须有至少一个非 Codex 的真实 probe + 一条无模型 E2E 作为证据。

## 9. M2.0 declarative profile（已实现）

`agents/profile.py` 提供 `DeclarativeProfile` / `DeclarativeAdapter`：

- 严格 JSON profile：固定字段、capabilities、probe argv/regex、invocation argv/stdin、event_map、exit_map、`unknown_event=RETAIN`；
- 只允许 `{executable}`、`{workspace}`、`{prompt_file}`、`{prompt}` 占位符，不经 shell；
- `probe()` 在受控子进程里执行 argv 并校验 regex；`render()` 只渲染 argv，不启动模型；
- `map_event()` / `classify_exit()` 做纯映射，未知事件为 `UNKNOWN`；
- `run()` 仍抛 `NotImplementedError`：dispatch、fixture agent、`none` provider 是 M2.1，不得把 M2.0 说成“第二个适配器已可用”。
