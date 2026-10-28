# 设计案例库（D0）

本目录是设计侧 RSI 的案例库，记录"哪一条设计决策导致了什么问题、用什么证据证明、后来怎么改"。它不是运行日志，也不是收益证明。

## 当前格式

`cases.jsonl`：一行一个 JSON 对象，字段：

| 字段 | 说明 |
|---|---|
| `case_id` / `title` | 稳定标识与一句话 |
| `stage` | S0–S7（见设计 RSI 方案） |
| `kind` | `REAL_BUILD` / `REVIEW_METHOD` |
| `status` | `FIXED` / `OPEN` / `CORRECTED` |
| `source` | 证据来源（文档、章节、commit） |
| `symptom` / `root_cause` | 现象与根因，分开写 |
| `design_decision` | 要改的设计决定，不是代码补丁 |
| `pattern` | 对应模式/检查（P1–P10 或设计词汇） |
| `evidence` | 可复核的文件/行/命令 |
| `verification` | 怎么证明改好了 |

## 与 `import_rsi_case.py` 的关系

D0.0 先用轻量 JSONL，便于人工评审与 diff；D0.1 再把每个案例映射成 `RSI_CASE_V1` manifest（`case_id`、`goal`、`sources`、`hypotheses`），交给 `tools/import_rsi_case.py`。不要在本目录直接伪造 `RSI_CASE_V1` 字段；映射器要单独写并测试。

## 当前案例

| ID | 阶段 | 状态 | 主题 |
|---|---|---|---|
| DESIGN-001 | S6 | FIXED | CLI 参数错误没有 JSON 输出 |
| DESIGN-002 | S6 | FIXED | 架构文档版本滞后 |
| DESIGN-003 | S5 | FIXED | 含空格路径下测试夹具失败 |
| DESIGN-004 | S5 | CORRECTED | 把诊断产物当发行包（测量对象错误） |
| DESIGN-005 | S5 | OPEN | 两个近似重复的验证 Oracle |
| DESIGN-006 | S4 | OPEN | 控制库权限未显式收紧 |

## 纪律

- 案例必须能指回真实文档/commit/行；示例和真实构建分开标注。
- `root_cause` 写到设计决定层，不能只写"修了某行代码"。
- `verification` 必须是可重跑的检查；不能写"看起来好了"。
- 未修复的案例保留 `OPEN`，不删除；否则复发率无法统计。
