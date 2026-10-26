# 设计决定记录（DDR）模板

- 版本：`FOUNDRY_DDR_V1`
- 用途：把 S0–S7 的设计决定写成**可检查**的记录；不是审批门，也不替代构建文档。
- 适用：多模块 / 多 agent / 有子 harness 的构建必须填；单模块小任务可只填 S1/S2/S5/S6，其余标 `NOT_APPLICABLE`。

## 最小字段

```json
{
  "schema_version": "FOUNDRY_DDR_V1",
  "record_id": "DDR-2026-10-26-EXAMPLE",
  "plan_id": "PLAN-...",
  "owner": "maintainer",
  "created_at": "2026-10-26T00:00:00+08:00",
  "carrier": {
    "carrier_id": "codex",
    "limits": ["skills are convention, not enforcement"]
  },
  "stages": {
    "S0": {"status": "DECIDED", "decision": "交付一个可复用的构建 Harness，不做业务 App。", "evidence": ["build-doc#scope"]},
    "S1": {"status": "DECIDED", "decision": "行为与验收见 acceptance_cases；至少一个负例。", "evidence": ["plan#cases"]},
    "S2": {"status": "DECIDED", "decision": "载体 codex；宿主工具按能力名映射。", "evidence": ["env#carrier"]},
    "S3": {"status": "NOT_APPLICABLE", "decision": "单模块，无子 harness。", "evidence": []},
    "S4": {"status": "DECIDED", "decision": "规则见 rules；每条 Domain Rule 有执行点。", "evidence": ["rules"]},
    "S5": {"status": "DECIDED", "decision": "检查矩阵见 checks；预言机不在写域。", "evidence": ["checks"]},
    "S6": {"status": "DECIDED", "decision": "新会话只拿交付件可复现。", "evidence": ["handoff-test"]},
    "S7": {"status": "DEFERRED", "decision": "首版不启用自动迭代；案例留待下一轮。", "evidence": []}
  },
  "rules": [
    {"id": "RULE-1", "type": "DOMAIN_RULE", "text": "验收脚本必须在实现写域之外执行。", "enforcement": "checks[CHECK-1]"}
  ],
  "subharnesses": [],
  "checks": [
    {"case_id": "CASE-1", "verifier": "verifier://check.py", "oracle": "expected.json（独立来源）", "independence": "WRITE_DOMAIN_EXCLUDED", "negative": "CASE-1-NEG"}
  ],
  "gaps": []
}
```

## 字段纪律

- `status` 只能是 `DECIDED` / `DEFERRED` / `NOT_APPLICABLE`；`DECIDED` 必须有非空 `decision`。
- `carrier.limits` 必须写出换载体会损失什么；不能只写 `codex`。
- `rules` 的 `type` 只能是 `DOMAIN_RULE` / `GOVERNANCE_POLICY` / `HEURISTIC`；前两类必须有 `enforcement`，否则降级为 `HEURISTIC`。
- `subharnesses` 每项必须有 `reason` 与 `alternatives`；没有理由的新增子 harness 视为设计缺陷。
- `checks` 每项必须有 `case_id`、`verifier`、`oracle`、`independence`；`negative` 可空，但 UI/验收合同必须至少有一个负例（由 Plan/IR 检查）。
- `gaps` 必须写 `capability`、`owner`、`next`；不能静默缺失。

## 机器检查

`tools/check_design_record.py --record ... [--request ...] [--scope ...]` 做 D4a 的结构检查；它不判断语义对错，也不产生执行权限。
