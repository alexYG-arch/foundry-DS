# ADR-0004：Contract Independence 作为基线

- 状态：`ACCEPTED_FOR_V3`
- 日期：2026-10-26
- 关联：`Harness_Foundry_升级方案_v3_ContractIndependence.md`、`docs/AGENT_ADAPTER_CONTRACT.md`（v3）
- 取代：`ADR-0002` 的“sandbox 是硬前提”路线

## 背景

v2 把 seatbelt/bwrap/VM 当成无 Codex 完整构建的硬前提。  
实际推进发现：

- 2A macOS VM 需要 25.4GB 镜像/介质；
- 2B Linux VM 可以强制 API/检查 egress，但 DSH 是 macOS 专用 app，不能在 Linux VM 内运行；
- 从模块/负责人独立性看，sandbox 不是主要来源；独立性主要来自 contract、独立 verifier、CAS、controller-only acceptance、append-only 事件、预算/恢复。

## 决策

计划基线改为 **Contract Independence**：

1. contract 边界；
2. 独立 verifier 代码/expected；
3. staging → CAS；
4. controller 独占 acceptance；
5. append-only 事件；
6. 预算/重试/恢复；
7. timeout/资源限制。

OS sandbox、UID、VM、host gateway 作为**可选加固**，不是计划闭合条件。

## 后果

- 不再要求新构建必须有 seatbelt/bwrap/VM；
- `ASSURANCE_REDUCED_NO_SYSCALL_SANDBOX` 必须显式标注；
- 2B VM/nft/gateway 保留为可选加固证据；
- 2A macOS VM 不阻塞计划；
- 新增 P1：staging/CAS + verifier contract + acceptance 更新；
- 安全声明边界：不防同 UID 恶意 agent、syscall 越界、网络直连；需要时再加可选加固。

## 不改变

- 无 Codex 新构建目标；
- DSH/API transport；
- 旧 `BUILD_ATTEMPT_*` 事件和 `read-build`；
- carrier、D4a/D0；
- GUI attach/70 次实验仍是外部门。

## 替代方案

- 继续 2A macOS VM：高成本，且对“独立性”收益有限；
- 继续 2B Linux VM：覆盖 API/检查，不覆盖 DSH；
- 仅 contract independence：本 ADR 选择，成本最低，边界清晰。
