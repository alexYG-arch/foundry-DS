# Foundry 路线图 v3：Contract Independence

- 状态：见 [`STATUS.json`](STATUS.json) `roadmap.status`（2026-10-28：`P1_CONTRACT_BASELINE_IMPLEMENTED_P3_FIXTURE_ONLY`）。本文不再手写状态或门禁数字。
- 日期：2026-10-26（状态字段 2026-10-28 修订）
- 基线：`repo/` commit `eb01bc0`；门禁数字见 `STATUS.json` `gate`
- 方案：`Harness_Foundry_升级方案_v3_ContractIndependence.md`（项目计划目录）
- 规格：[AGENT_ADAPTER_CONTRACT.md](AGENT_ADAPTER_CONTRACT.md)（v3）
- 决策：[ADR-0004-CONTRACT-INDEPENDENCE.md](decisions/ADR-0004-CONTRACT-INDEPENDENCE.md)

本路线图取代 v2 的“sandbox 硬前提”路线。  
**计划闭合 = 7 项 contract 基线 + 无 Codex 新构建 + carrier 解绑；不是 sandbox 闭合。**

---

## 0. 意图门

1. 新 Plan/Scope 不使用 `CODEX` executor，不要求 `codex_executable`；
2. Agent 只写 `staging/<attempt>`，不写 verifier/controller/CAS/accepted；
3. Verifier 代码/expected 独立，不由 producer 生成；
4. 只有 controller 写 acceptance；
5. 事件 append-only；
6. 预算/重试/恢复/超时/资源限制有效；
7. 目标 Harness carrier 不默认 Codex；
8. OS sandbox/VM 是可选加固，不是门。

---

## 1. 阶段

### P0 Contract freeze（2–3 人日）

- 评审 v3 方案 + spec；
- 冻结角色、contract、CAS、acceptance、assurance 标签；
- 选择 verifier 部署：同机 UID / 独立主机；
- 明确 sandbox 可选。

**退出**：角色/接口/CAS/acceptance 无未决；sandbox 不再阻塞。

### P1 Contract baseline（5–7 人日）

- staging → CAS；
- verifier contract + code/expected identity；
- controller acceptance 更新；
- append-only/预算/恢复；
- timeout/资源限制；
- `read-build` 回读。

**退出**：CAS/acceptance/timeout/恢复 fixture 全过。

### P2 Agent transport（3–5 人日）

- DSH headless / API；
- `TRUSTED_HOST` 直接运行路径；
- 无 sandbox 时明确 `execution_mode`；
- probe/负例。

**退出**：DSH/API 真实运行；不标 sandbox PASS。

### P3 无 Codex full build（5–7 人日）

- 真实 DSH/API；
- 独立 verifier；
- staging/CAS；
- 无 codex 进程；
- 失败恢复；
- 包/文档。

**退出**：无 Codex 完整矩阵；acceptance 只由 controller。

### P4 Carrier（2–3 人日）

- 目标 Harness 文档/SKILL/CARRIERS；
- 至少一个非 Codex carrier E2E。

### P5 设计 RSI（并行）

- D4a/D0 已实现；
- 设计变异/70 次是外部门，另行。

### O1 可选加固

- 独立 UID / 独立 verifier 主机 / seatbelt / bwrap / VM / host gateway；
- 先有威胁模型需求才做；
- 不阻塞 P3。

---

## 2. 依赖

```text
P0 contract
  → P1 CAS/verifier/acceptance
      → P2 transport
          → P3 no-Codex full
              → P4 carrier
                  → P5 RSI
O1 optional hardening 可并行，不设门
```

---

## 3. 门禁

| 门 | 不通过时 |
|---|---|
| contract 边界 | 不得发布 |
| verifier 独立 | 不得宣称独立验收 |
| staging/CAS | 不得接受 artifact |
| controller-only acceptance | 不得发布 |
| append-only | 不得发布 |
| 预算/恢复 | 不得自动重试 |
| timeout/资源 | 不得生产运行 |
| 无 Codex 新路径 | 不得宣称完成 |
| carrier 非默认 Codex | 不得发布目标 Harness |
| sandbox | **不是门**；只有声称安全隔离时才要求 |

---

## 4. 当前状态

权威字段在 [`STATUS.json`](STATUS.json)（`roadmap.implemented` / `roadmap.not_verified`）；下面是 2026-10-28 的摘要。

已实现：

- Carrier 文档/指令发现/CARRIERS.md；
- Controller 旧事件/read-build/retry/budget/recovery/repair/drift；
- D4a/D0；
- DSH/API live（宿主）；
- staging → CAS（`agents/artifacts.py`）、独立 verifier contract 与 runner、1.3 controller-only acceptance；
- `TRUSTED_HOST` 作为显式标注的无沙箱基线（`execution.mode` 与 `sandbox.provider` 必须一致；结果记录 `fs_enforcement`）；
- 1.2 与 1.3 共用 attempt/acceptance/budget 投影；verifier 目录级绑定；
- 2B Linux VM + bwrap + nft + host gateway（**可选加固证据**）。

未验证 / 未完成：

- P3 无 Codex full build 只有夹具 adapter 的 e2e，没有真实 agent transport 的完整构建；
- 设计变异/70 次（外部门）；
- GUI attach（不可用）；
- 2A macOS VM（介质 25.4GB，可选加固，不阻塞）。

---

## 5. 下一步

1. P3：用真实 DSH/API transport 跑一次无 Codex 完整构建，记录实际 `fs_enforcement` 与 `owner_independence`；
2. 1.3 成为默认路线前完成 `read-build`/恢复路径在 1.3 上的实测；
3. carrier/RSI；
4. 可选加固（独立 UID / seatbelt / bwrap）只在声称隔离时启用。

> 不再以 sandbox/VM 作为计划闭合条件；可选加固保留。
