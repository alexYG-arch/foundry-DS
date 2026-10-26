# Foundry 路线图 v3：Contract Independence

- 状态：`PROPOSED_FOR_REVIEW`
- 日期：2026-10-26
- 基线：`repo/` commit `eb01bc0`，公开门禁 **70 模块 / 949 项**
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

已完成：

- Carrier 文档/指令发现/CARRIERS.md；
- Controller 旧事件/read-build/retry/budget/recovery/repair/drift；
- D4a/D0；
- DSH/API live（宿主）；
- 2B Linux VM + bwrap + nft + host gateway（**可选加固证据**）；
- 2A macOS VM 未完成（介质 25.4GB，不阻塞）。

未完成：

- staging/CAS 实现；
- 独立 verifier contract；
- controller acceptance 更新；
- `TRUSTED_HOST` 正式路径；
- P3 无 Codex full build；
- 设计变异/70 次（外部门）；
- GUI attach（不可用）。

---

## 5. 下一步

1. P0 评审 v3 方案/spec；
2. P1 staging/CAS + verifier contract；
3. P2 DSH/API trusted-host 路径；
4. P3 无 Codex full build；
5. carrier/RSI。

> 不再以 sandbox/VM 作为计划闭合条件；可选加固保留。
