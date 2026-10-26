# Agent Transport 与 Sandbox 规格 v2

- 版本：`AGENT_TRANSPORT_SPEC_V2`
- 状态：`P2_VM_GATEWAY_LIVE`（完整 1.3 CLI/真实 DSH、旧事件 read-build ACCEPTED、retry/budget；carrier 文档与 AGENTS/CLAUDE 指令发现已解绑；返修/egress/能力包 carriers 待做）
- 日期：2026-10-26
- 基线：`eb01bc0`，70 模块 / 949 项门禁（P2 full-flow live + old-event controller）
- 配套方案：`Harness_Foundry_升级方案_v2_DeepSeek与无Codex.md`
- 取代：`AGENT_ADAPTER_CONTRACT.md` v1 的 M1/M2 适配器部分
- 保留：`ADR-0001` Scope 版本、`ADR-0003` agents 包；`ADR-0002` 的“Codex sandbox 依赖”被取代

---

## 0. 范围

本规格定义：

- Foundry 如何调用 DeepSeek 的四种形态：DSH Desktop、DSH 子进程、DeepSeek CLI、DeepSeek API；
- 如何在没有 Codex 的机器上完成“实现 → 独立检查 → 接受/返修/恢复”；
- 如何约束 agent 进程、任务命令、网络和工具调用；
- Plan/Scope 1.3 的数据形状；
- 可执行的 probe、失败码和验收矩阵。

本规格不定义：

- DSH 内部模型/插件实现；
- 任意 GUI 自动化；
- Codex 旧计划的迁移（只读兼容）；
- 设计 RSI 的 S0–S7 细节（见设计 RSI 文档）。

---

## 1. 术语与分层

| 层 | 职责 | 不负责 |
|---|---|---|
| `ExecutionHost` | Foundry 进程所在的宿主；决定 OS 沙箱是否可嵌套 | 不解释模型输出 |
| `FoundryController` | Plan/Scope、预算、事件、独立检查、接受 | 不信任模型报告 |
| `AgentTransport` | 如何启动/连接 agent、如何读事件、如何结束 | 不决定验收 |
| `AgentAdapter` | 某个 runtime 的 transport 实现 + 能力声明 | 不绕过 Scope |
| `SandboxProvider` | 把 argv/进程关进 OS 权限边界 | 不选模型 |
| `ToolExecutor` | API 模式下执行读/写/运行工具 | 不直接写未授权路径 |

### 1.1 两条网络

- **Agent egress**：agent 访问模型 API/本地 DSH 服务的网络；
- **Task network**：Workpack 的 LOCAL/验证命令可访问的网络。

两者必须分开声明、分开审批。Agent 能访问模型，不代表任务命令能访问任意网络。

### 1.2 A/B 两条工作流

| 工作流 | 执行宿主 | 目标 | 失败状态 |
|---|---|---|---|
| **A. Host-native** | Foundry 在 DSH 外层（Terminal/launchd），seatbelt/bwrap 包裹 agent 与检查命令 | 第一交付；无 Codex 完整构建 | `BLOCKED_SANDBOX`；不授权 `none`；B 继续 |
| **B. GUI/attach（关闭）** | 直接附着 GUI session | probe 结果：仅 `/api/file`，GUI `standard` 不可 headless | `NOT_SUPPORTED`；不阻塞 A |

A 与 B 不互相等待；B 的 probe 失败不改变 A 的验收，A 的 sandbox 失败也不证明 B 不可行。

### 1.3 自主修复与停止

默认不是“人工确认”，而是自动修复：

1. 复现并保留失败证据（命令、exit、stdout/stderr、哈希、最小输入）；
2. 做最小修复（配置、探针参数、代码、文档、测试，不扩大 Scope）；
3. 重跑受影响检查，再跑完整门禁；
4. 记 `repair` 记录；失败尝试保留；
5. 同一失败最多 3 次修复；仍失败 → `BLOCKED_*`，说明具体条件。

只有 user-owned 门才停：缺少用户决定/合同变更、凭据/权限/账号且环境与 DSH credentials service/钥匙串都无法提供、不可逆动作、外部付费/发布/远程写、需要扩大 Scope。

自动修复不得放宽门禁、跳过独立检查、使用生产 `none`、伪造凭据/审批、改写历史或扩大 Scope。修复若必须改合同，记 `CONTRACT_CHANGE` 并停。

失败分类：`AUTO_FIXED`、`AUTO_RETRY`、`BLOCKED_CREDENTIAL`、`BLOCKED_AUTHORITY`、`BLOCKED_EXTERNAL`、`NEEDS_USER_DECISION`。

---

## 2. 通用协议

```python
@dataclass(frozen=True)
class AgentCapabilities:
    transport: str                  # "dsh-desktop" | "dsh-headless" | "deepseek-cli" | "deepseek-api"
    adapter_version: str
    prompt_transport: str           # "stdin" | "argv" | "http"
    events: str                     # "ndjson" | "sse" | "text"
    usage: str                      # "REPORTED" | "UNKNOWN"
    session: str                    # "NEW_ONLY" | "HANDOFF" | "RESUME"
    tool_calls: str                 # "NATIVE" | "CONTROLLER" | "NONE"
    sandbox: str                    # "PROVIDER" | "NATIVE" | "NONE"
    desktop: str                    # "NONE" | "HANDOFF" | "ATTACH"

class AgentTransport(Protocol):
    transport_id: str
    def probe(self, scope) -> dict: ...
    def start(self, request: "AgentRequest", *, before_dispatch) -> "AgentRun": ...
    def events(self, run: "AgentRun") -> Iterator["AgentEvent"]: ...
    def finish(self, run: "AgentRun") -> "AgentResult": ...

class SandboxProvider(Protocol):
    provider_id: str
    def probe(self) -> dict: ...
    def wrap(self, argv: list[str], profile: dict) -> list[str]: ...
```

### 2.1 请求/结果

`AgentRequest` 至少包含：

- `workspace`、`prompt`、`model`、`model_mode`、`budget`；
- `scope`（read/write roots、task network、executables）；
- `session`（mode/id/home）；
- `transport_options`（仅该 transport 认识）；
- `observation_root`、`cancellation`。

`AgentResult` 至少包含：

- `status`（`PASS` / `FAIL` / `UNKNOWN_SIDE_EFFECT` / `VALIDATION_FAILED`）；
- `reason_code`、`exit_code`、`final_message`；
- `events`（归一化）与 `raw_refs`；
- `usage` / `usage_source`；
- `session_id`、`adapter_id`、`transport_id`；
- `workpack_accepted=false`（永远不由 transport 产生 acceptance）。

### 2.2 事件

```json
{"seq": 7, "type": "TURN_STARTED|MESSAGE|TOOL_CALL|TOOL_RESULT|USAGE|RETRY|TURN_COMPLETED|TURN_FAILED|UNKNOWN",
 "raw_type": "…", "raw_ref": "stdout.bin#7", "fields": {}}
```

- 原始字节必须保留；
- 未知事件 `UNKNOWN` 计数，不致命；连续超限/协议错乱 → `TRANSPORT_PROTOCOL_ERROR`；
- 事件顺序按 `seq`；
- 模型输出不是验收。

---

## 3. DSH Headless Transport

### 3.1 事实

DSH CLI 位于：

```text
/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh
```

`dsh headless --help` 的实际选项：

```text
dsh --profile headless [--json] [--session-id <id>] [task...]
  task: 多个词用空格连接；`-` 从 stdin 读取
  --json: 输出 NDJSON run events
  --session-id: 采用已持久化 Session；未知 id 报错
```

### 3.2 调用

```bash
export DSH_HOME="<scope.dsh_home>"
"<scope.executable>" --profile headless --json --session-id "<session>" "<prompt>"
# 或：printf '%s' "$PROMPT" | "$DSH" --profile headless --json -
```

约束：

- 必须显式传 `DSH_HOME`；不得静默使用 GUI 的隐式状态，除非 Scope 明确 handoff；
- `--profile desktop` 禁止（Electron 独占）；
- 不把 `DSH_HOME` 指向未授权目录；会话文件/锁需要写权限；
- 每次运行一个 `observation_root`，原始 stdout/stderr 落盘。

### 3.3 probe

`probe` 至少执行：

```bash
"$DSH" --version
"$DSH" --profile headless --help
```

返回 `status`、`version`、`headless_help_sha256`、`executable_sha256`、`dsh_home`、`profile_exists`。

- 不调用模型；
- 不把 `--help` 通过当成模型可用；
- 认证/模型可用性由首个真实运行验证，失败码 `DSH_AUTH_UNAVAILABLE` / `DSH_MODEL_UNAVAILABLE`。

**P0 实测**：headless 的 transport 可用，但真实运行返回 `MISSING_CREDENTIAL`：CLI 没有自动继承 Desktop Models 页保存的凭据，需要 `DEEPSEEK_API_KEY` 环境或 credentials service。Desktop handoff 前必须解决同一个凭据来源，否则 handoff 只能到 `BLOCKED_CREDENTIAL`。

### 3.4 NDJSON 解析（P0 已取到最小样本）

2026-10-26 用 `dsh --profile headless --json` 取到的真实事件类型：

```json
{"type":"session","sessionId":"session-…","cwd":"…"}
{"type":"status","phase":"turn_start","turn":1}
{"type":"status","phase":"step_start","turn":1,"step":1}
{"type":"status","phase":"step_end","turn":1,"step":1}
{"type":"status","phase":"turn_end","turn":1,
 "reason":{"kind":"error","error":{"message":"…","code":"MISSING_CREDENTIAL"}}}
{"type":"final","text":""}
```

- 这是当前最小 schema，不是永久契约；adapter 必须保留未知类型/字段；
- `session` 是会话 id 的权威来源；`status.turn_end.reason.kind=error` 是失败证据；
- `final.text` 可能是空串，不能把“有 final”当成功；
- 退出码、`turn_end`、`final` 三者不一致时 `DSH_TRANSPORT_INCONSISTENT`；
- 认证错误（`MISSING_CREDENTIAL`）是环境/凭据问题，不是模型失败，必须单独归类；
- 原始 NDJSON 落盘，不覆盖。

### 3.5 Session

- `NEW`：adapter 生成/记录 session id（若 CLI 不返回，使用 `--session-id` 预分配或由 DSH 输出事件读取）；
- `RESUME`：`--session-id` 必须指向同一 `DSH_HOME` 的持久化 session；
- `HANDOFF`：见 §4；
- 同一 session 的并发写由 `session.lock` 拒绝；adapter 必须先检查锁并返回 `DSH_SESSION_LOCKED`。

**P2 实测边界**：headless 创建的 session 可用 `--session-id` 接管（同 id）；**Desktop GUI 创建的 `standard` preset session 不能由 headless one-shot 接管**：

```text
session "session-…" runs under agent preset "standard",
which the one-shot runner does not compose
```

因此 GUI-created Desktop session 的 handoff 记为 `SESSION_PRESET_UNSUPPORTED`；它需要 Desktop attach 或 headless-compatible preset，而不是继续调用 headless。

---

## 4. DSH Desktop Transport

### 4.1 事实边界

- DSH Desktop app 版本（本机）`0.2.1-rc.3`；
- `dsh --profile desktop --help` 返回：
  `profile "desktop" is managed exclusively by the Electron application`；
- 不能从 CLI 启动 desktop profile；
- DSH session 持久化在 `$DSH_HOME/sessions/<workspace>/session-*`，含 `session.lock`；
- 桌面 app、headless、web 都使用 `DSH_HOME` 下的 session 存储。

### 4.2 支持的 Desktop 模式（A 的 handoff；B 的 attach）

#### A-1. `HANDOFF`（A 工作流 MVP，必须实现）

流程：

1. 人或桌面 app 在 DSH Desktop 中创建/继续一个 session；
2. Foundry 读取用户给出的 `session_id`（或 `session_projcache` 中的 id），校验：
   - 同一 `DSH_HOME`；
   - `session.lock` 未被 GUI 持有；
   - session 版本可读；
   - headless 可用的模型凭据（`DEEPSEEK_API_KEY` 或 credentials service；缺失则 `BLOCKED_CREDENTIAL`）；
3. Foundry 调用 `dsh --profile headless --session-id <id> --json` 继续任务；
4. Readback 显示 `desktop_session_id`、`dsh_home`、`app_version`、`handoff=true`；
5. 完成后桌面可打开该 session 供人工审阅；GUI 与 headless 不得同时写。

验收：桌面创建 session → Foundry handoff → 产物 → 独立检查 → 接受；全程无 Codex。

#### B-1. `WEB_API`（B 工作流 P2.1，probe 结果：仅 `/api/file`，无会话 attach）

```bash
dsh --profile web --host 127.0.0.1 --port 0 --no-open
```

- 启动本地 UI/API；`--host` 只接受具体本机地址，不接受 wildcard；
- `/api` 有 browser-trust fence；**具体会话/工作区 endpoint 未验证**；
- probe 必须记录实际 `/api` 路径、认证方式、请求/响应样例（脱敏）；
- 未通过 probe → `DSH_WEB_API_UNAVAILABLE`，不写 Attach 实现。

#### B-2. `ATTACH`（B 工作流 P4+，目标，未验证）

- 直接附着运行中的 Desktop app，不重启、不复制 session；
- 需要 DSH 官方/稳定的本地 API 或插件入口；
- 当前无证据，状态 `NOT_VERIFIED`；
- 不得把 `HANDOFF` 宣传成 `ATTACH`。

### 4.3 打开桌面

`open -a "DeepSeek Harness"` 或 `dsh://` URL 只用于人工审阅；不产生执行权限、不自动确认、不替代独立检查。

---

## 5. DeepSeek CLI Transport

### 5.1 合约

通用 CLI 必须支持：

- `--version`：版本字符串；
- prompt：stdin 或 argv；
- JSONL events（至少包含开始/消息/结束/错误；usage 可选）；
- exit code；
- 可选 `--session-id` / `--model` / `--workspace`。

### 5.2 现状

- 本机 PATH **没有 `deepseek` CLI**；
- 不假设存在；adapter probe 失败返回 `ADAPTER_PROBE_FAILED`；
- DSH headless 可注册为 `deepseek-cli` 的一个实现，但产品字段（`--profile`、`--session-id`）不得泄漏到通用 CLI 合约；
- 通用 CLI 由声明式 profile（M2.0 的 `DeclarativeProfile`）承载，profile 必须固定字段、占位符、事件映射。

---

## 6. DeepSeek API Transport

### 6.1 目标

API 模式必须能完成实现，而不只是“返回建议”。Foundry 负责工具循环：

```text
prompt + tools
  → model tool_calls
  → Foundry 校验路径/权限
  → SandboxProvider 执行工具
  → tool result 回传
  → … 直到 finish 或 max_turns
```

### 6.2 工具集（最小）

| 工具 | 输入 | 约束 |
|---|---|---|
| `read_file` | path | 只读 roots |
| `list_dir` | path | 只读 roots |
| `write_file` | path, content | 写 roots；先展示 diff/内容策略由 Scope 决定 |
| `run_command` | argv, cwd, timeout | 只经 SandboxProvider；不经 shell |
| `finish` | summary | 结束；不等于 acceptance |

禁止：任意 URL fetch、直接 SQLite、直接改 Scope/事件、读取凭据。

### 6.3 HTTP 合约

- `base_url` 可配置；默认值以 provider 文档为准，必须显式写入 Scope；
- `POST /chat/completions`（或 provider 声明的兼容路径）；
- `stream=true` 时解析 SSE；保留原始响应；
- `tools`/`tool_calls` 字段按 provider 实际 probe 校准；不假设字段永久稳定；
- 超时、重试（仅传输层）、`Retry-After`、rate limit；
- API key 只从环境/钥匙串引用读取，禁止写 Scope/日志/回执；
- `base_url` host allowlist；禁止重定向到内网/元数据地址。

### 6.4 失败码

`API_AUTH_FAILED`、`API_RATE_LIMITED`、`API_SCHEMA_UNSUPPORTED`、`API_TOOL_LOOP_LIMIT`、`API_USAGE_UNKNOWN`、`API_NETWORK_DENIED`、`API_RESPONSE_TRUNCATED`。

### 6.5 usage

- 有 usage 就记 `REPORTED`；
- 无 usage 记 `UNKNOWN`，预算降级为尝试次数 + 墙钟；
- 不得把 UNKNOWN 显示为 0。

---

## 7. SandboxProvider

### 7.1 Providers

| Provider | 平台 | 实现 | 状态 |
|---|---|---|---|
| `seatbelt` | macOS | `/usr/bin/sandbox-exec -f <profile>`；deny default，allow read/write roots、进程、必要 model egress | 必须；需在 DSH 外层验证 |
| `bwrap` | Linux | `bwrap` namespace、bind roots、network none/unshare | 必须 |
| `none` | 测试 | 仅 fixture；显式 `allow_unsandboxed_agent=true` + `FOUNDRY_TEST_ONLY=1` | 已有；非生产 |
| `codex-sandbox` | 旧 | 旧 1.2 计划 | 只读兼容 |

### 7.2 嵌套约束

- 实测：在 DSH 会话内执行 `sandbox-exec` 返回 `Operation not permitted`；
- **A**：Foundry 必须在 DSH 外层；seatbelt 不可用 → `BLOCKED_SANDBOX`，A 暂停；不得用 `none` 替代；
- **B**：在 DSH 内并行 probe 本地 API/工具桥；探不到 → `NOT_VERIFIED`，A 继续；
- 外部 sandbox broker 是 A 的后备方案之一，不是默认；
- `none` 永远不是生产降级项。

### 7.3 网络 profile

```json
{
  "agent_egress": "MODEL_ONLY | NONE",
  "task_network": "NONE | LOOPBACK | REMOTE_SERVICE",
  "remote_service": {"proxy": "host", "allowed_hosts": ["…"]}
}
```

- `MODEL_ONLY` 只放行 DSH/DeepSeek endpoint；
- `NONE` 不给任务命令网络；
- `REMOTE_SERVICE` 必须 host-owned proxy + allowlist；未实现前 fail-closed；
- 网络拒绝必须有 `SANDBOX_NETWORK_DENIED`，不能静默直连。

### 7.4 验收

- 每个 Workpack/验证命令都有 provider；
- provider probe 失败 → `SANDBOX_UNAVAILABLE`；
- `none` 出现在生产 Scope → 拒绝；
- 文件写域/读域/网络/超时都有负例测试。

---

## 8. Plan/Scope 1.3

P1 fixture implementation: `src/harness_foundry_factory/agents/scope13.py` (`validate_scope_13`, `run_agent_workpack`) and `tests/test_agent_scope13.py`. P2 transport: `agents/dsh.py`, `agents/api.py` (real tool loop), and `agents/agent_controller.py` (experimental `advance-build` 1.3 branch). Key from `DEEPSEEK_API_KEY` or `~/.dsh/foundry/deepseek.key` (0600). The controller `advance-build` integration is not yet wired; do not treat the fixture/transport path as a production authorization.

### 8.1 Plan 1.3

```json
{
  "schema_version": "1.3",
  "workpacks": [{
    "workpack_id": "IMPLEMENT",
    "executor": "AGENT",
    "agent": {
      "adapter": "dsh-headless",
      "adapter_version": "1",
      "session": {"mode": "HANDOFF", "session_id": "session-…"},
      "model": {"mode": "FIXED", "name": "deepseek-chat"}
    },
    "goal": "…",
    "depends_on": [],
    "atom_ids": [],
    "inputs": [], "artifacts": [], "verification": []
  }]
}
```

- `executor: AGENT | LOCAL`；`CODEX` 只在 1.0–1.2 只读；
- `agent.adapter` 必须在 Scope 声明并可 probe；
- 无默认 adapter；无 Codex 回退。

### 8.2 Scope 1.3

```json
{
  "scope_version": "1.3",
  "agents": {
    "dsh": {
      "adapter": "dsh-headless",
      "executable": "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh",
      "dsh_home": "/Users/…/.dsh",
      "session": {"mode": "HANDOFF", "id": "session-…"},
      "model": {"mode": "FIXED", "name": "deepseek-chat"}
    }
  },
  "sandbox": {"provider": "seatbelt",
              "network": {"agent_egress": "MODEL_ONLY", "task_network": "NONE"}},
  "usage_accounting": "ADAPTER_REPORTED",
  "workspace_root": "…", "source_read_roots": [], "verification_root": "…",
  "task_write_roots": {}, "executables": {}, "max_attempts": 3,
  "max_task_attempts": 2, "command_timeout_seconds": 1800, "expires_at": "…"
}
```

- 1.3 **不要求** `codex_executable`；
- `scope_version` 见 ADR-0001；Plan 1.3 必须显式 1.3；
- 旧 1.2 Scope 仍读 `codex_executable`/`model_policy`；
- 1.3 写回只写新形状，不改旧事件。

---

## 9. 无 Codex 验收

### 9.1 定义

“无 Codex 完整构建”指：

1. 新 Plan 无 `CODEX` executor；
2. 新 Scope 无 `codex_executable` 必填；
3. 运行路径不启动 `codex` 进程；
4. 新构建的文档确认、Scope、实现、独立检查、接受/返修/恢复全部完成；
5. Reviewer 非 Codex；
6. 目标 Harness 产物不默认 Codex；
7. 包清单/安装说明无 Codex 依赖。

### 9.2 检查

| 检查 | 方法 |
|---|---|
| 无 `codex` 进程 | 进程树/argv 断言；`which codex` 为空；运行后扫描 |
| 无 `CODEX` executor | Plan 1.3 编译 + `grep` |
| Scope 无 codex | 1.3 Scope 通过；删除 `codex_executable` 后仍 PASS |
| Reviewer | `rsi_review.py` 不再硬编码；DeepSeek/本地 |
| 目标 Harness | 规则/Skill/README/指令发现/capability carriers |
| 包 | `MODULES`/manifest 无 Codex-only 模块；文档无默认 Codex |
| 旧计划 | 1.0–1.2 只读；不自动迁移 |

### 9.3 允许保留的 Codex 名称

- `codex-sandbox` provider（旧计划兼容）；
- `CODEX_*` 原因码别名（旧记录读取）；
- 文档中的历史/示例；
- 不得作为新计划默认、回退或验收依赖。

---

## 10. 测试与 probe 义务

### M0 必做 probe

1. `dsh --version`、`dsh headless --help`、`dsh web --help`、`dsh --profile desktop --help`（记录独占错误）；
2. `dsh headless --json` 的最小真实样本（无敏感信息）；
3. `--session-id` 接管桌面/headless session 的真实样本；
4. `dsh web --no-open --port 0` + `/api` probe（路径/认证/响应）；
5. `sandbox-exec` 在 DSH 外层可用性；`bwrap` Linux；嵌套失败复现；
6. DeepSeek API 的 chat/tool/stream/usage 真实响应；
7. 目标 Harness 的指令发现/能力包/carrier 现状。

所有 probe 只读；不把 probe 当验收。

### 测试矩阵

- unit：transport/profile/sandbox/协议；
- fixture：无模型、无网络、无 Codex；
- real：DSH headless、desktop handoff、API 各一条；
- negative：缺 executable、auth 失败、session 锁、未知事件、网络拒绝、无 provider、`none` 生产；
- repair：探针/配置/代码失败自动修复并重跑；只允许 3 次；不把技术失败升级为人工确认；
- compat：1.2 旧计划只读、1.3 新计划；
- package：无 Codex 依赖、文档/ Skill/carrier 一致。

---

## 11. 未决/不假设

| 项 | 状态 | 处理 |
|---|---|---|
| DSH Desktop attach API（B） | `NOT_VERIFIED` | P0/P2.1 probe；不实现前标 NOT_VERIFIED；不影响 A |
| DSH headless NDJSON schema | 未冻结 | M0 真实样本后冻结 |
| DSH `--session-id` 并发/锁行为 | 部分（有 session.lock） | 必须实测；失败 `DSH_SESSION_LOCKED` |
| DSH headless 凭据来源 | **P0 实测 `MISSING_CREDENTIAL`** | 明确 env/credentials service；Desktop handoff 必须先解决 |
| `sandbox-exec` 在 DSH 外层 | 已证 PASS（danger-full-access 外层） | A 可用；workspace-write 嵌套仍 EPERM |
| `bwrap` macOS | 不存在 | 仅 Linux |
| DeepSeek API 工具 schema | 待 probe | 不假设永久稳定 |
| 无 Codex 的 REMOTE_SERVICE | 未实现 | 先 `NONE`/`LOOPBACK`，fail-closed |
| 目标 Harness carrier | 未实现 | P4/P5 |

---

## 12. 版本与兼容

- 本规格版本 `2`；transport/capability 字段新增 minor，删除/改义 major；
- Plan/Scope 1.3 只对新计划生效；
- 旧 1.0–1.2 不迁移、不写回；
- `CODEX_*` 仅别名；
- 任何“支持 DeepSeek”的声明必须有真实 transport probe + 一条无 Codex E2E 作为证据。
