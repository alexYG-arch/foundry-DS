# Foundry 路线图 v2：DeepSeek 全形态 + 无 Codex 完整构建

- 状态：`PROPOSAL_FOR_REVIEW`
- 日期：2026-10-26
- 基线：`repo/` commit `eb01bc0`，公开门禁 **60 模块 / 905 项**
- 方案：`Harness_Foundry_升级方案_v2_DeepSeek与无Codex.md`（项目计划目录；本仓库 docs 不复制该文件）
- 规格：[AGENT_ADAPTER_CONTRACT.md](AGENT_ADAPTER_CONTRACT.md)（v2）

本路线图取代 v1 的 M0–M4 排序。v1 的 M1.0/M1.1 包化、D0/D1/D4a 保留为已完成前置；M2.0/M2.1a 保留为基础，但不再继续扩展通用适配器。

## 0. 意图门（P0 先冻结）

新构建必须满足：

1. 新 Plan/Scope 不使用 `CODEX` executor，不要求 `codex_executable`；
2. 运行路径不启动 `codex` 进程；
3. DeepSeek 四种形态全部支持：DSH Desktop、DSH 子进程、DeepSeek CLI、DeepSeek API；
4. Desktop 以 **handoff** 为 MVP；attach 需要 probe，未验证前标 `NOT_VERIFIED`；
5. 没有 Codex 也能完成文档确认 → Scope → 实现 → 独立检查 → 接受/返修/恢复；
6. Reviewer、目标 Harness carrier、发布包都不默认 Codex；
7. 设计 RSI 的 D0/D1/D4a 进入可运营状态，设计变异通过前不启动 70 次运行。

## 0.1 A/B 两条工作流

| 工作流 | 目标 | 失败时 |
|---|---|---|
| **A. Host-native** | 第一交付：Foundry 在 DSH 外层，seatbelt/bwrap 执行；无 Codex 完整构建 | `BLOCKED_SANDBOX`；不授权 `none`；B 继续 |
| **B. Desktop-native** | 并行 probe DSH 本地 API/工具桥，让 Foundry 在 DSH 内复用其沙箱 | `NOT_VERIFIED`；不阻塞 A |

## 1. 阶段

### P0 规格与宿主决策（2–3 人日）

- 评审本方案 + spec v2；
- 冻结 **A = Host-native 第一交付**；**B = Desktop-native 并行 probe**；
- 确认 DSH Desktop `HANDOFF` 为 A 的 MVP，`ATTACH` 为 B 的 `NOT_VERIFIED`；
- 确认 seatbelt/bwrap 是 A 的硬前提；A 失败只标 `BLOCKED_SANDBOX`，B 继续，不许降级 `none`。

**P0 probe 结果（2026-10-26）**

| 项 | 结果 |
|---|---|
| A seatbelt | **PASS**（danger-full-access 外层）；写域/网络限制通过；workspace-write 嵌套 EPERM |
| B `dsh web` | UI + auth cookie PASS；猜测 `/api/*` 404；attach `NOT_VERIFIED` |
| B `dsh headless` | transport PASS；`session/status/final` 已取到；**MISSING_CREDENTIAL** |
| Desktop profile | Electron 独占，CLI 不能 boot |

**退出**：A/B 边界签署；A sandbox 已证；**凭据来源仍是 P2 前置**；B attach `NOT_VERIFIED`。

### P1 A 的无 Codex 基础（5–7 人日；B probe 并行）

- Plan/Scope 1.3；新路径移除 `codex_executable`；
- `SeatbeltSandboxProvider`（macOS）+ `BubblewrapSandboxProvider`（Linux）；至少 macOS 真实可用；
- `AgentTransport`/`SandboxProvider` 协议；
- `rsi_review.py` 去 CODEX 硬编码；
- 旧 1.0–1.2 只读兼容测试。

**退出**：无 Codex fixture E2E；进程树无 `codex`；1.2 双跑。

### P2 A 的 DSH Desktop/Headless 垂直切片（5–7 人日；B probe 继续）

- `DshHeadlessTransport`：probe、NDJSON、session、usage、错误码；
- 解决 DSH headless 凭据来源（env/credentials service；禁止复制/内联 key）；
- `DshDesktopTransport(HANDOFF)`：桌面 session → `dsh headless --session-id`，锁检查，Readback；
- `dsh web --no-open --port 0` + `/api` probe（只记录，不猜）；
- 真实 DSH 任务：实现 → 独立检查 → 接受。

**退出**：Desktop handoff 证据；无 Codex 完整 E2E；session/DSH_HOME 记录。

### P3 DeepSeek API + CLI（5–8 人日）

- `DeepseekApiTransport` 工具循环：read/list/write/run/finish，经 sandbox；
- `DeepseekCliTransport` 通用 profile；
- API key/allowlist/usage/重试/负例。

**退出**：API 真实任务通过独立检查；CLI 不可用时 `ADAPTER_PROBE_FAILED`。

### P4 无 Codex 完整构建 + Carrier（5–7 人日）

- 隐藏/卸载 Codex 后跑完整流程；
- 目标 Harness 规则/Skill/README/指令发现/capability carriers 去 Codex 默认；
- 包清单/安装说明无 Codex 依赖；
- 旧计划只读兼容。

**退出**：无 Codex 完整矩阵；Reviewer 非 Codex；目标 Harness 可被 DSH/DeepSeek 使用。

### P5 设计 RSI 运营化（并行，3–5 人日 + 实验）

- D4a 接入 `compile-build-plan`；D0 映射到 `import_rsi_case.py`；
- D1 在真实无 Codex 构建上使用；
- 设计变异 22 份、两轮评审、10 canary；
- 通过后才冻结 70 次移动端运行；
- D2/D3/D4b/D5–D8 按设计 RSI 文档推进。

## 2. 依赖图

```text
P0 规格/宿主
  → P1 no-Codex 基础
      → P2 DSH Desktop/Headless
          → P3 API/CLI
              → P4 no-Codex 完整构建 + carrier
                  → P5 设计 RSI 运营化 / 70 次门
```

设计 RSI 的 D0/D1 可与 P1 并行；D4a 接入在 P1 后；设计变异不依赖模型，可在 P2 期间做；70 次运行必须在 P4 后。

## 3. 不可妥协的门

| 门 | 不通过时 |
|---|---|
| 新 Plan 无 CODEX | 不得发布 |
| 新 Scope 无 `codex_executable` 必填 | 不得发布 |
| 运行路径无 `codex` 进程 | 不得宣称“去 Codex 完成” |
| 真实 sandbox provider（A） | A `BLOCKED_SANDBOX`；不得用 `none`；B 继续 |
| Desktop handoff 真实证据 | 只能写 `NOT_VERIFIED` |
| Reviewer 非 Codex | 不得宣称完整无 Codex |
| 目标 Harness 无 Codex 默认 | 不得发布 |
| 设计变异通过 | 不得启动 70 次 |

## 4. 当前状态（2026-10-26）

- 已完成：v1 的 Phase 0、M0、M1.0/M1.1、D0/D1/D4a、M2.0/M2.1a、iOS/Android 环境；
- 未完成：DeepSeek transport、Plan/Scope 1.3、seatbelt/bwrap、无 Codex E2E、carrier、设计变异、70 次；
- 门禁：60 模块 / 905 项 PASS；
- 关键事实：A seatbelt 在外层 PASS；B `dsh web` UI 启动但 attach API 未找到；`dsh headless` transport PASS 但 **MISSING_CREDENTIAL**；`desktop` profile 由 Electron 独占；DSH session 带锁；
- 当前 `repo/` commit `b3ffbc7`；本方案/spec 尚未实现；P0 结果已入 `work/evidence/p0/`。

## 5. 下一步

1. 评审并冻结本方案 + spec v2；
2. 做 P0 probe（DSH headless JSON、session handoff、web API、sandbox 外层）；
3. 按 P1 开始 Plan/Scope 1.3 与 seatbelt provider；
4. 在 P2 完成后才继续设计 RSI 的运行层。

> 本路线图不授权执行；A 的 sandbox 失败只阻塞 A，B 的 `NOT_VERIFIED` 不阻塞 A。
