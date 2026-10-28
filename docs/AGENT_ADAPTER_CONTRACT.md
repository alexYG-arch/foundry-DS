# Agent Contract Independence 规格 v3

- 版本：`AGENT_CONTRACT_INDEPENDENCE_SPEC_V3`
- 状态：`P1_PARTIAL_IMPLEMENTED`（CAS/verifier identity/controller gate 已实现；CAS view/verifier runner/resource limits 待做）
- 日期：2026-10-26
- 基线：`eb01bc0`，75 模块 / 962 项门禁
- 配套方案：`Harness_Foundry_升级方案_v3_ContractIndependence.md`
- 取代：`AGENT_TRANSPORT_SPEC_V2` 的“sandbox 必选”语义
- 保留：DSH/API transport、旧事件、retry/budget/recovery、carrier、D4a/D0

---

## 0. 范围

本规格定义：

- controller / agent / verifier 的 contract 边界；
- 独立 verifier 的代码/expected 合同；
- staging → CAS；
- controller 独占 acceptance；
- append-only 事件；
- 预算/重试/恢复；
- timeout/资源限制；
- DSH/API/CLI transport 的接入；
- sandbox/VM 作为**可选加固**，不是基线。

非目标：

- 防恶意 agent 的 syscall/文件系统隔离；
- GUI Desktop `standard` session attach；
- 70 次人工实验；
- 把“独立”宣传成“安全”。

---

## 1. Assurance 模型

| 标签 | 含义 |
|---|---|
| `CONTRACT_INDEPENDENCE` | 默认；模块/负责人/证据/acceptance 独立 |
| `CONTRACT_PLUS_UID` | 额外独立 OS 用户 |
| `CONTRACT_PLUS_VM` | 额外 VM/容器 |
| `CONTRACT_PLUS_SANDBOX` | 额外 seatbelt/bwrap |
| `SECURITY_NOT_CLAIMED` | 不声称防恶意 agent |

结论中必须写实际模式；没有 sandbox 不能写 `sandbox_enforcement=PASS`。

---

## 2. 角色

| 角色 | 负责 | 禁止 |
|---|---|---|
| Controller | 授权、预算、事件、acceptance | 改 verifier expected |
| Agent | 生产 staging artifact | 写 verifier/controller/CAS/accepted |
| Verifier | 独立 code/expected、读 CAS、输出结果 | 写 workspace/controller |
| Host | key/网络/资源 | 替 agent 自批 |
| Human | 目标/范围/不可逆决定 | 把模型输出当验收 |

同一人可以在早期同时担任 owner，但必须记录；验收时至少 verifier 逻辑独立。

---

## 3. Contract 边界

每个模块必须有：

- `module_id`、`version`、`owner`；
- 输入/输出 schema；
- 允许读/写的资源；
- 错误码；
- 兼容策略。

不允许：

- 读其他模块内部文件/内存；
- 共享可变目录；
- 通过“约定”绕过版本；
- producer 生成 verifier expected。

验收只看公开 contract，不看内部实现。

---

## 4. AgentTransport

```python
class AgentTransport(Protocol):
    transport_id: str
    capabilities: AgentCapabilities
    def probe(self, scope) -> dict: ...
    def start(self, request: AgentRequest, *, before_dispatch) -> AgentRun: ...
    def events(self, run) -> Iterator[AgentEvent]: ...
    def finish(self, run) -> AgentResult: ...
```

`AgentCapabilities`：

```python
{
  "adapter_id": "...",
  "adapter_version": "1",
  "prompt_transport": "stdin|arg|file|http",
  "events": "jsonl|sse|text",
  "usage": "REPORTED|UNKNOWN",
  "handoff": bool,
  "execution": "TRUSTED_HOST|UID|VM|SANDBOX",
  "tool_calls": "NATIVE|CONTROLLER|NONE"
}
```

`AgentResult`：

```json
{
  "status": "PASS|FAIL|VALIDATION_FAILED|UNKNOWN_SIDE_EFFECT",
  "reason_code": "...",
  "final_text": "...",
  "session_id": "...",
  "usage": {"total_tokens": 0},
  "execution_mode": "TRUSTED_HOST",
  "workpack_accepted": false
}
```

`workpack_accepted` 永远为 false。

---

## 5. DSH transport

### 5.1 Headless

```bash
DSH_HOME=<scope.dsh_home>
dsh --profile headless --json [--session-id <id>] -
```

- prompt 通过 stdin；
- `--json` NDJSON；
- `session` 事件给 session id；
- `status.turn_end.reason.kind=error` 是失败；
- `final.text` 可为空；
- `MISSING_CREDENTIAL` → `BLOCKED_CREDENTIAL`；
- 未来未知事件保留，不丢；
- 不把 `--help` 当模型可用。

### 5.2 Credential

- `DEEPSEEK_API_KEY` 或 `~/.dsh/foundry/deepseek.key`（0600）；
- 不复制 key 到 Scope/日志；
- 可选 host gateway：agent 只拿 token。

### 5.3 Desktop

- headless-compatible session 可 `--session-id`；
- GUI `standard` session：`SESSION_PRESET_UNSUPPORTED`；
- attach API 不可用；
- 不把 handoff 当 attach。

---

## 6. DeepSeek API transport

- OpenAI-compatible `/chat/completions`；
- 工具循环由 controller 执行；
- 工具：`read_file` / `list_dir` / `write_file` / `run_command`；
- 所有路径限制在 staging/read roots；
- `run_command` 必须经 execution provider（可 TRUSTED_HOST/UID/VM）；
- key 不进入结果/日志；
- usage 有则记，无则 `UNKNOWN`；
- max turns / timeout。

---

## 7. Verifier contract

```json
{
  "verifier_id": "VERIFIER-...",
  "owner": "...",
  "code_ref": "cas://... or file://...",
  "code_sha256": "...",
  "expected_ref": "cas://...",
  "expected_sha256": "...",
  "input_policy": "CAS_ONLY",
  "output_schema": "FOUNDRY_VERIFIER_RESULT_V1"
}
```

要求：

- code/expected 由 verifier owner 维护；
- producer 不可写；
- 输入只读 CAS；
- 输出：

```json
{
  "status": "PASS|FAIL|BLOCKED",
  "case_id": "...",
  "checks": [],
  "failure_domain": "BUSINESS_ASSERTION|ENVIRONMENT|...",
  "automatic_retry_allowed": false
}
```

- verifier 结果不是 acceptance；controller 决定。

---

## 8. staging → CAS

```text
workspace/staging/<attempt-id>/...
  → declared artifacts
  → copy to CAS
  → manifest
  → verifier reads CAS
  → acceptance references sha256
```

CAS：

```json
{
  "artifact_id": "...",
  "path": "staging/...",
  "size": 0,
  "sha256": "...",
  "attempt_id": "...",
  "created_at": "..."
}
```

规则：

- CAS 不可覆盖；
- 以 hash 为身份；
- accepted 记录 hash；
- 旧版本保留；
- agent 不能写 CAS；
- GC 只由 controller 执行；
- 字节变化 → drift hold。

---

## 9. Controller acceptance

只有 controller 可以：

- 校验授权/Plan/Scope；
- 校验预算/attempt；
- 校验 staging artifact；
- 复制 CAS；
- 调用 verifier；
- 检查 verifier code/expected identity；
- 追加 `BUILD_ATTEMPT_FINISHED` ACCEPTED。

禁止：

- agent 自报 PASS；
- verifier 自报 ACCEPTED；
- 模型输出直接 acceptance；
- 改写旧事件。

---

## 10. Append-only 事件

事件：

```text
BUILD_AUTHORIZATION_PREPARED
BUILD_AUTHORIZATION_APPROVED
BUILD_ATTEMPT_STARTED
BUILD_AGENT_REPAIR_REQUESTED
BUILD_ATTEMPT_FINISHED
BUILD_ACCEPTANCE_INVALIDATED
BUILD_COMMAND_* (兼容)
```

规则：

- 只追加；
- controller DB 由 controller owner 写；
- agent/verifier 不可写；
- 失败/未知副作用保留；
- `read-build` 只读回读；
- 旧事件不迁移。

---

## 11. Plan/Scope 1.3

```json
{
  "schema_version": "1.3",
  "workpacks": [{
    "workpack_id": "IMPLEMENT",
    "executor": "AGENT",
    "agent": {"adapter": "dsh-headless", "adapter_version": "1"},
    "verifier": {
      "verifier_id": "V1",
      "code_sha256": "...",
      "expected_sha256": "...",
      "input_policy": "CAS_ONLY"
    },
    "artifacts": [],
    "verification": []
  }]
}
```

Scope：

```json
{
  "scope_version": "1.3",
  "agents": {
    "dsh": {
      "adapter": "dsh-headless",
      "executable": "...",
      "dsh_home": "...",
      "session": {"mode": "NEW"}
    }
  },
  "execution": {
    "mode": "TRUSTED_HOST|UID|VM|SANDBOX",
    "network": {"agent_egress": "NONE|MODEL_ONLY", "task": "NONE|LOOPBACK|REMOTE_SERVICE"}
  },
  "staging_root": "...",
  "cas_root": "...",
  "verifier_roots": "...",
  "max_attempts": 3,
  "max_task_attempts": 2,
  "command_timeout_seconds": 1800,
  "max_output_bytes": 65536,
  "max_staging_bytes": 0,
  "max_cpu_seconds": 0,
  "max_memory_bytes": 0
}
```

兼容：旧 `sandbox` 字段仍可读；新计划写 `execution`。

---

## 12. 预算/资源

- `max_attempts` / `max_task_attempts`；
- timeout；
- 进程组 kill；
- CPU/内存/文件句柄/磁盘/输出上限；
- staging 配额；
- 并发；
- API tool turns；
- 失败分类：

```text
AUTO_FIXED
AUTO_RETRY
BLOCKED_CREDENTIAL
BLOCKED_AUTHORITY
BLOCKED_SANDBOX
BLOCKED_BUDGET
BLOCKED_EXTERNAL
```

`BLOCKED_SANDBOX` 仅在可选 sandbox 模式使用；`TRUSTED_HOST` 不产生该码。

---

## 13. 可选加固

| 模式 | 作用 | 不改变 |
|---|---|---|
| 独立 UID | 防误写/故障隔离 | contract/CAS/acceptance |
| 独立 verifier 主机 | 更强独立性 | contract |
| seatbelt/bwrap | syscall/FS/网络约束 | 独立性设计 |
| VM | 环境/故障/网络隔离 | 独立性设计 |
| host gateway | key 不进 agent | acceptance |

没有 sandbox：

- `execution_mode=TRUSTED_HOST`；
- `sandbox_enforcement` 必须为空/`NONE`；
- 不得写 PASS。

---

## 14. 测试

- contract：模块接口/版本/owner；
- verifier：独立 code/expected、producer 不能改；
- CAS：staging→hash、不可覆盖、drift hold；
- acceptance：agent/verifier 无 DB 写；
- events：append-only/read-build；
- budget：retry/exhaustion/recovery；
- timeout/resources：CPU/mem/output/process group；
- transports：DSH/API/CLI；
- no Codex：Plan/Scope/进程；
- carrier：至少一个非 Codex。

---

## 15. 迁移

- v2 的 seatbelt/bwrap/VM 证据保留为可选；
- 2B Linux VM/nft/gateway 是 optional hardening；
- 2A macOS VM 不再阻塞计划；
- 旧 Plan 1.0–1.2 只读；
- 新 Plan 1.3 使用 `execution`，`sandbox` 兼容。

---

## 16. 未决

| 项 | 状态 |
|---|---|
| 同机 verifier UID vs 独立主机 | 待 P0 决定 |
| CAS GC 策略 | 待 P1 |
| resource limits 具体值 | 待 P1 |
| DSH Desktop attach | `NOT_SUPPORTED` |
| 70 次实验 | 外部门 |

---

**一句话：contract 独立性是基线；sandbox/VM 是可选加固，不是闭合条件。**
