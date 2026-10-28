# foundry-DS `a3-read-v2` 审查报告与修复/升级计划

- 仓库：`alexYG-arch/foundry-DS`
- 审查对象：分支 `a3-read-v2` @ `98a1ffb`（相对 `main` @ `a535be6`，即 merge-base）
- 审查日期：2026-10-28（UTC+8）
- 方法：通读分支 diff 及其依赖模块（`revision_store*`、`build_state`、`build_rebind`、`build_correction`、`agents/*`）、架构 / ADR / 路线图 / 运行合同文档；在 Python 3.12.3 + Linux 上运行 A3/A4 相关测试与完整公开门禁 `tools/check_release_source.py`；编写探针脚本复现 4 项缺陷；经 GitHub API 核对 CI 历史。未修改目标仓库任何内容。

---

## 0. 摘要

| 指标 | 数值 |
| --- | --- |
| 已用探针复现的缺陷 | 4（B1、B2、B3、S1） |
| 分支 diff | +136 / −2，5 个文件，2 个提交 |
| 本地 Linux 公开门禁 | 963 项：950 通过、6 skip、7 失败 → `SOURCE_CHECKS_FAIL` |
| GitHub Actions 连续失败 | 17 次（main 最近 15 次 + 分支 2 次），同一步骤 |

**结论一：分支以当前形态不宜合入。** 改动很小（一个只读旁路视图），但三项命名承诺——revision-preserving、lightweight、for cancellation——都没有兑现；没有生产调用方；两处语义缺陷（B1 TOCTOU、B2 派生授权）会让监控/取消界面做出错误判断。

**结论二：生成与校验的“相对独立性”只能分层回答。** 过程级 / 字节级独立——在实施方合作（非对抗）且开启可选沙箱时可以保证；v3 默认的 TRUSTED_HOST 基线把它退化为“事后可检测的、声明文件的独立”；作者级 / 模型级独立系统不保证、也不打算保证。

**结论三：两件事比分支本身更紧急。** main 上的 `DedupRevisionControlEventStore` 在同实例并发写入时会提交悬空内容引用，导致 Program 永久不可读（S1）；CI 门禁在 Linux 结构性红灯，仓库当前没有任何自动化信号（Q1）。

---

## 1. 分支改动审查（`a3-read-v2` 相对 `main`）

分支内容：新增 `src/harness_foundry_factory/control_view.py`（54 行，`build_control_view` → `CONTROL_VIEW_V2`）、`BuildController.control_view()`（+4 行）、`tests/test_control_view.py`（1 个用例）、`docs/A3_A4_CLOSURE.md`、`devtools/package_generic_release.py` 白名单加入 `control_view` 与 `A3_A4_CLOSURE`。

| # | 严重度 | 问题 | 位置 | 证据 | 修法 |
| --- | --- | --- | --- | --- | --- |
| B1 | 严重 | “revision-preserving” 不成立（TOCTOU） | `control_view.py:33-49` | 依次开 4 个独立 SQLite 连接（`get_event` → AUTH 类型读 → ATTEMPT 类型读 → `event_count`），`stream_revision` 最后才读。探针：在两次读之间追加 REVOKED，视图返回 `state=APPROVED, stream_revision=3`，而 revision 3 正是那条 REVOKED。`control_snapshot`（v1）同样顺序，v2 原样复制。 | 先 `event_count` 取 N，再只读 `stream_revision <= N` 的事件（给 `list_events_by_types` 加上界参数），或单事务读取。 |
| B2 | 高 | `state` 与派发边界 `_current` 语义不一致 | `control_view.py:40-45` vs `build_correction.py:45` | 不调用 `validate_authority_chain`。派生授权（`derived_authority`）的源审批被撤销后，子 prepared 的视图仍 APPROVED，而 `_current` 拒绝 “source approval was revoked”。已复现。 | 接入 `validate_authority_chain`，或改名 `direct_state` 并标注非派发权威。 |
| B3 | 高 | 与 Plan 1.3 prepared payload 不兼容 | `control_view.py:46-48` | 1.3 的 payload 为 `{scope, plan}`，无 `source_event_id` / `proposal_event_id` → `KeyError`。已复现。1.3 正是路线图方向。 | 按 `plan.schema_version` 分支；可选字段 `.get()`；补 1.3 夹具。 |
| B4 | 中 | 与 `control_snapshot` 逐行重复 | `build_runtime.py:649-677` | v1 未删也未委托；`_utc` 为复制的简化版，格式错误抛裸 `ValueError` 而非 `RequestValidationError`。 | `control_snapshot` 委托给 v2 或删除；复用 `build_runtime._utc`。 |
| B5 | 中 | 无生产调用方 | 全库 grep | 只在 `BuildController` 定义处与 1 个测试出现；无 CLI / `read-build` 接入。闭合文档声称的 “monitoring, cancellation and budget/attempt surfaces” 不存在。 | 接入 `read-build --control-view` 并由取消路径消费，或删去 cancellation 措辞。 |
| B6 | 中 | 测试薄且不在 CI 门禁 | `tests/test_control_view.py`；`tools/check_release_source.py` | 只测 APPROVED + IN_FLIGHT；SUPERSEDED / REVOKED / EXPIRED / APPROVAL_REQUIRED、缺 prepared、naive tz 未测；helper `event()` 的 `revision` 参数未使用。`test_control_view`、`test_revision_store_dedup`、`test_a3a4_helpers` 均不在 `REQUIRED_MODULES`，而 `control_view`、`revision_store_dedup` 已进发布 `MODULES`。 | 补 5 态矩阵与异常路径；三份测试加入 `REQUIRED_MODULES`。 |
| B7 | 低 | “轻量”只在 Python 层成立 | `revision_store.py:290-307` | `EXPLAIN QUERY PLAN`：走 `(program_id, stream_revision)` 索引后逐行过滤 `event_type`，即遍历该 Program 全部行；8.5 GB 单 Program 仍 O(N)。 | 离线工具增加 `(program_id, event_type, stream_revision)` 索引。 |
| B8 | 高 | 未触及真正热点 | src 全库 | 68 处 `list_events()` 全量加载；`len(store.list_events(...))` 当计数器 6 处（`build_entrypoint.py:256/267/272/321`、`build_preview.py:206`）；`event_count()` 仅 2 处。`_current` / `advance` / `approve` / entrypoint 不变。 | 见 WP2。 |

读接口调用点统计（`src/`，不含定义与 dedup 覆写）：`list_events` 68、`list_events_by_types` 5、`get_event` 4、`event_count` 2。

对闭合文档 `docs/A3_A4_CLOSURE.md` 的核对：`_current` “is not replaced” 属实且合理；“for monitoring, cancellation …” 无代码对应（B5）；“revision-preserving” 在并发下不成立（B1）；活库迁移移出闭合条件是用户决定，但 S4 说明工具目前确实无法执行它。

---

## 2. A3-write / A3-migration（闭合文档涵盖、代码在 main）

| # | 严重度 | 问题 | 位置 | 证据 | 修法 |
| --- | --- | --- | --- | --- | --- |
| S1 | 严重 | Dedup store 并发写入导致数据损坏（已复现） | `revision_store_dedup.py:168-190` | `_prepare_entries` 把待写正文放到 `self._pending_contents`，`_append_aux` 在事务里取出并清空。同一实例两个线程交错后：事件 A 已提交并引用 digest `f826…`，content 表只有 B 的 `f2a1…`；此后 `list_events(P)` 永久抛 “source content reference is missing”，append-only 触发器使其无法原地修复。基类自己的 `test_racing_writers_get_one_commit_without_lost_updates` 就是同一实例多线程写——受支持契约被子类破坏。 | contents 随 entries 一起传给 `_append_aux`（元组返回或 contextvar）；加同实例并发回归。 |
| S2 | 高 | 源复用绕过 CAS 与幂等 | `build_runtime.py:159-162`；`build_entrypoint.py:279-282` | `record_source_snapshot(reuse_unchanged=True)` 命中复用时在 `append_batch` 之前 `return existing`：`expected_revision`、`idempotency_key` 不校验、不记录。entrypoint 仍返回 `control_state_write: True` 与旧事件的 `stream_revision`；响应不区分“复用”与“新捕获”。 | 命中时仍校验 `expected_revision`；返回 `reused: true`、`control_state_write: false`、当前 head revision。 |
| S3 | 中 | 复用检查本身重量级 | `build_runtime.py:137-147` | `reusable_source_event` 读取全部历史 `BUILD_SOURCES_CAPTURED` 正文做整字典比较（dedup 还需逐条 hydrate）。 | payload 记 `snapshot_sha256`，先比 hash。 |
| S4 | 中 | 迁移非流式、校验不完整 | `revision_store_dedup.py:34-131` | `migrate_to_dedup` 对全部 payload `fetchall()`，`contents` dict 持有全部唯一文本，8.5 GB 易 OOM；`verify_migration` 不比对 `control_idempotency` 的 hydrate 往返。 | 游标分批读写；verify 增加 `idempotent_events` 往返比对。 |

S1 复现要点：线程 A 先 `_prepare_entries`（`_pending_contents={A}`）→ 线程 B `_prepare_entries`（覆盖为 `{B}`）→ A 进入 `BEGIN IMMEDIATE`，`_append_aux` 取出 `{B}` 写入并清空，提交引用 A digest 的事件 → B 进入事务时 `_pending_contents` 已空，CAS 冲突回滚。最终库状态：`control_events` 中 A 的 payload 为 `{"text": {"content_sha256": "f826…"}}`，`control_source_content` 中只有 `f2a1… → "text-B"`。

---

## 3. 生成与校验的相对独立性

项目自己的定义（`docs/GENERIC_BUILD_RUNTIME.md`）：“独立性指实施不能改写控制器、判定代码或判定执行器，不是第三方认证”；ADR-0004 进一步声明“不防同 UID 恶意 agent”。按此口径逐层核对两条路线：

| 机制 | Plan ≤1.2（`BuildController`，生产路线） | Plan 1.3（`AgentBuildController`，TRUSTED_HOST 基线） | 结论 |
| --- | --- | --- | --- |
| 验收写入权 | 仅 controller 追加 ACCEPTED；模型自报 / exit 0 不直接产生验收 | 同左 | 保证 |
| verifier 物理位置 | 必须在 workspace 外；控制库与控制器代码不在任务写域 | 同左 | 保证 |
| 产物不可变 | 声明产物 size+sha 入事件，accepted 字节派发/验收前复核 | staging → CAS，不可覆盖、拒绝符号链接、drift HELD | 保证 |
| verifier 字节身份 | `verifier://` 引用文件 + `checker_files` 的 SHA-256，prepare 绑定、`_current(check_content=True)` 复核 | `task.verifier` 合同绑 code/expected 哈希；`task.verification` 无绑定 | 部分：只覆盖声明文件 |
| 读写域执行 | 依赖 Codex 沙箱 | `TrustedHostProvider.run` 完全忽略 `read_roots/write_roots`，裸 `subprocess.run` | v3 基线下不执行，只事后检测 |
| 可执行文件不可被改写 | `_validate_scope` 拒绝写域内 executables / receiver | `validate_scope_13` 不检查；夹具把 `dsh` 放在 workspace 内 | 1.3 退化 |
| 控制库写保护 | 触发器拦 UPDATE/DELETE；INSERT 不拦 | 同左 | 防误改，不防同 UID 恶意写（ADR-0004 承认） |
| 作者 / 模型独立 | 无 owner 字段；Plan、verifier、expected 通常由外层 agent 同一会话写 | `VerifierContract.owner` 只是非空字符串，无处比较 | 不保证，也不打算保证 |
| 校验→生成信息通道 | `repair_history` 回灌 verifier stdout/stderr 各 1200 字符 | `feedback` 2000 字符进下一次 prompt | 刻意保留；泄露程度取决于 verifier 作者 |
| 语义充分性 | exit 0 空检查即通过（文档承认） | 同左 | 完全交给宿主 |

**回答“能否保证”：**

- 能保证的：验收写入权、verifier 物理位置、产物不可变、声明文件的字节身份。机械、两条路线都成立。
- 只能检测、不能阻止的（v3 TRUSTED_HOST 基线）：实施方读 verifier、改未声明文件、INSERT 控制库、写 CAS。ADR-0004 明确让渡给“可选加固”。
- 不保证的：作者 / 模型独立、校验→生成信息通道的泄露程度、verifier 的语义充分性。系统只记录、不约束。

因此：相对独立性在“合作式实施方 + 可选沙箱”下成立；在默认基线下是“事后可检测的声明文件独立”；对外表述应与之匹配。

### 具体缺口

| # | 严重度 | 缺口 | 位置 | 证据 | 修法 |
| --- | --- | --- | --- | --- | --- |
| G1 | 严重 | TRUSTED_HOST 不执行任何文件系统边界 | `agents/sandbox_trusted.py:29-57` | `run()` 只用 argv/cwd/env/timeout；`command.read_roots/write_roots` 从未被读取。 | attempt 事件记录 `fs_enforcement: NONE\|SANDBOX`；assurance 细化为 `CONTRACT_INDEPENDENCE_DETECT_ONLY`。 |
| G2 | 高 | 1.3 scope 允许可执行文件在任务写域 | `agents/scope13.py:126-154` | `executables`、`agents[*].executable` 只做 `_absolute_file`；1.2 的 `_validate_scope:246-252` 有此检查。 | 移植 1.2 检查；修正夹具。 |
| G3 | 高 | verifier contract 非 CAS 模式静默不执行 | `agents/agent_controller.py`（`if verifier_contract is not None and use_cas`） | 声明 `task.verifier` 但无 staging/cas 时，只校验哈希不运行。 | 返回 `HELD_VERIFIER_NOT_RUNNABLE`。 |
| G4 | 高 | `sandbox.provider` 与 `execution.mode` 矛盾 | `scope13.py:160-165` vs `agent_controller.py:73-78` | scope 要求 provider ∈ {seatbelt,bwrap}，`_provider()` 遇 TRUSTED_HOST 直接裸跑；审批人看到 seatbelt，实际无沙箱。 | 互斥：TRUSTED_HOST 时强制 `provider="none"` 并显式标注；Readback 展示实际 provider。 |
| G5 | 中 | identity 不覆盖 verifier 的 import / fixture | `build_runtime.py:239-245, 259-260` | 只哈希 argv 中 `verifier://` 文件与 `checker_files`；`helpers.py`、fixture 可在 prepare 后静默修改。 | 对 `verification_root` 做目录级 manifest 并整体绑定。 |
| G6 | 中 | 现行文档矛盾 | `GENERIC_BUILD_RUNTIME.md` vs `ADR-0004` | 前者“无沙箱能力时不降级直跑”，后者 sandbox 可选、TRUSTED_HOST 为基线。 | 统一到 ADR-0004 口径并写明 TRUSTED_HOST 的实际保证范围。 |
| G7 | 低 | 历史路线：生成器内嵌校验器的修复循环 | `compiler.py:1473-1502` | `from .validator import validate_candidate`，同进程“验证→结构修复→再验证”≤3 轮；共享 `semantic_contracts.py` 谓词。自洽检查，非独立校验。已退役但仍是 `validate-core` 基线。 | 冻结并标注为历史自洽检查。 |

---

## 4. 工程质量与过程

| # | 严重度 | 问题 | 证据 | 修法 |
| --- | --- | --- | --- | --- |
| Q1 | 严重 | CI 门禁在 Linux 结构性红灯 | GitHub Actions：main 最近 15 次、分支 2 次全部失败于 “Run required public checks (skips fail)”。本地 Linux 复现：963 项，950 通过，6 skip（seatbelt 不可用），7 失败（agent controller / scope13 / e2e 落到未安装的 bwrap，且断言 `task_sandbox_provider == "seatbelt"`）。门禁要求 0 skip 0 fail → 只能在 macOS 通过。README 第 154 行自述“原生验证主要来自 macOS”，CI 却定义在 ubuntu-latest。 | WP6。 |
| Q2 | 高 | 路线图状态自相矛盾 | `FOUNDRY_ROADMAP_2026Q4.md` 顶部 “P3_FULL_CONTRACT_VERIFIED”，第 4 节列 “未完成：staging/CAS、独立 verifier contract、controller acceptance 更新、TRUSTED_HOST 正式路径、P3 无 Codex full build”；`AGENT_ADAPTER_CONTRACT.md` 标 `P1_PARTIAL_IMPLEMENTED`。 | 状态单一来源。 |
| Q3 | 中 | 两套控制器并存、投影不互通 | `build_state.py` 只服务 1.2；1.3 的 `BUILD_AGENT_REPAIR_REQUESTED` 不被 `project_readback_attempts` 识别；1.3 用 `len(events)` 自行 CAS。 | WP8。 |
| Q4 | 中 | 代码与文档体量失衡 | `src/` 92,239 行，其中历史路线约 60,563 行（66%），当前构建路线约 6,335 行，agents 2,220 行；`docs/` 124 文件 / 28,342 行，历史与现行混放。 | 历史路线移位冻结；文档分“现行/历史”。 |
| Q5 | 低 | A4 helper 小缺陷 | `render_markdown` 不渲染 `limitations`；`_reference` 不检查 hex；`hydrate_history` 冗余表达式。 | 随 WP1 修复。 |

GitHub Actions 记录（时间为 UTC+8）：

| 分支 | 提交 | 结论 | 触发时间 | 链接 |
| --- | --- | --- | --- | --- |
| a3-read-v2 | 98a1ffb | failure | 2026-10-28 10:03 | https://github.com/alexYG-arch/foundry-DS/actions/runs/40618636166 |
| a3-read-v2 | 4dcbaa5 | failure | 2026-10-27 22:13 | https://github.com/alexYG-arch/foundry-DS/actions/runs/40519075176 |
| main | a535be6 | failure | 2026-10-27 21:33 | https://github.com/alexYG-arch/foundry-DS/actions/runs/40513006444 |

---

## 5. 修复 / 升级计划

九个工作包，按依赖关系组织；不做日历估算，难度以“侵入度”和触及子系统表达。

依赖关系：`WP0 → WP3`；`WP1 → WP2`；`WP4 → WP5`；`WP4 → WP8`；`WP2 / WP3 / WP5 / WP6 → WP7`。推荐起手顺序：WP0 与 WP6 并行（止血 + 恢复 CI 信号），随后 WP1 与 WP4，再 WP2 / WP3 / WP5，最后 WP8、WP7。

### WP0 止血：Dedup 并发损坏（侵入度 低）

- 目标：消除 S1 的数据损坏路径，保持 `REVISION_V1_DEDUP` 格式不变。
- 改动：`_prepare_entries` 返回 `(entries, contents)` 或用 `contextvars`；`_append_aux(connection, entries, contents)`；删除 `_pending_contents`；基类 hook 签名随之调整（默认返回空 contents）；新增同实例双线程 Barrier 回归。
- 依赖：无。风险：极低。
- 退出证据：并发回归通过且 `list_events` 可 hydrate 全部事件；`test_revision_store_dedup` 加入 `REQUIRED_MODULES`。

### WP1 ControlView 收敛（侵入度 中）

- 目标：让 `CONTROL_VIEW_V2` 的三项承诺成立：一致 revision、与 `_current` 同口径、可被真实 surface 消费。
- 改动：`list_events_by_types` 增加 `up_to_revision`（含 dedup 覆写）；`build_control_view` 先 `event_count` 再带上界读取，接入 `validate_authority_chain`（新增 `AUTHORITY_CHAIN_INVALID` 态），按 `plan.schema_version` 兼容 1.3，复用 `build_runtime._utc`；`control_snapshot` 委托给 v2；`read-build --control-view`，取消/撤销路径以其 `stream_revision` 作 `expected_revision`；测试覆盖 5 态矩阵、缺 prepared、naive tz、派生授权、1.3 payload、注入式并发一致性；顺手修 Q5。
- 依赖：无。风险：低—中（`_current` 不动）。
- 退出证据：审查中的 3 个探针转为回归并通过；`test_control_view` 加入 `REQUIRED_MODULES`；`A3_A4_CLOSURE.md` 的 cancellation 措辞有对应代码。

### WP2 存储读路径瘦身——8.5 GB 的真正解（侵入度 高）

- 目标：派发 / 审批 / 读回热路径不再全量加载事件流。
- 改动：6 处 `len(store.list_events(...))` → `event_count`；`_current` 拆分为 control facts（typed reads：AUTH/ATTEMPT/REBIND 家族）+ content checks（`get_event(source_event_id)` / `_proposal_event` 点读，仅 `check_content=True` 时加载正文）；`approve_build_authorization`、`advance` 传入 typed 事件集（投影函数已是纯函数）；新增离线工具 `tools/index_store_event_type.py` 建 `(program_id, event_type, stream_revision)` 索引，不在 open 时自动执行。
- 依赖：WP1。风险：高——`_current` 是 CAS/派发边界，必须以“旧 `_current` vs 新 `_current` 在全部现有夹具上逐字段相等”作为过渡断言。
- 退出证据：差分断言在 `test_build_runtime` 全量夹具通过；对合成 10 万事件 Program，`advance` 不再读取 `BUILD_SOURCES_CAPTURED` 正文（SQLite trace 证明）。

### WP3 源复用与幂等协调 + 迁移流式化（侵入度 中）

- 目标：A3-write 的两套幂等机制一致；迁移工具可处理目标规模。
- 改动：`record_source_snapshot` 命中复用前校验 `expected_revision == event_count`，返回 `reused: true`；`capture-build-sources` 的 `control_state_write` 反映真实写入、`stream_revision` 返回当前 head；payload 新增 `snapshot_sha256`，`reusable_source_event` 先比 hash（旧事件无 hash 回退字节比较）；`migrate_to_dedup` 游标分批读写；`verify_migration` 增加 `control_idempotency` 往返比对。
- 依赖：WP0。风险：中（payload 新字段需核对旧读者容忍）。
- 退出证据：stale `expected_revision` 的复用请求返回 `RevisionConflictError`；合成 2 GB 库在 1 GB RSS 限制下迁移成功且 verify PASS。

### WP4 1.3 Scope / Controller 加固（侵入度 中）

- 目标：把 1.2 已有的机械保证移植到 1.3，消除 scope 与执行模式的矛盾。
- 改动：`validate_scope_13` 要求 `executables`、`agents[*].executable`（含 resolve 后路径）不落在任何 `task_write_roots`，`task.verification.argv` 至少一个 `verifier://` 并做 identity 绑定；`execution.mode=TRUSTED_HOST ⇔ sandbox.provider="none"` 强制一致；`AgentBuildController` 对声明 `task.verifier` 但 `use_cas=False` 返回 `HELD_VERIFIER_NOT_RUNNABLE`；attempt 事件记录 `fs_enforcement`、实际 provider、assurance 标签；修正夹具（`dsh` 移出 workspace）。
- 依赖：无。风险：中（1.3 夹具与 e2e 同步修改；对 1.2 零影响）。
- 退出证据：写域内可执行文件、seatbelt+TRUSTED_HOST 组合、无 CAS 的 verifier 合同三类负例均 fail-closed；`read-build` 对 1.3 attempt 可见实际 provider 与 enforcement。

### WP5 独立性标注与边界收敛（侵入度 中）

- 目标：把系统能保证与不能保证的独立性变成可读事实。
- 改动：`verification_root` 目录级 manifest 绑定（相对路径→sha256，排除 `__pycache__`）；verifier 结果 schema 增加 `public_reason` / `private_detail`，`repair_history` 与 1.3 `feedback` 只回灌 `public_reason`；`VerifierContract.owner` 与 producer owner 比较，相同则在事件与 Readback 标 `SAME_OWNER`（不阻断）；文档：`GENERIC_BUILD_RUNTIME.md` 撤回“无沙箱能力时不降级直跑”并补“TRUSTED_HOST 下的实际保证”，`AGENT_ADAPTER_CONTRACT.md` 增加 `CONTRACT_INDEPENDENCE_DETECT_ONLY`。
- 依赖：WP4。风险：中（目录级绑定会让 prepare 后改任何 verifier 文件都停下，是期望行为但改变工作流）。
- 退出证据：改动 verifier 的 import 文件后派发被拒；`SAME_OWNER` 在 Readback 可见；两份文档对 TRUSTED_HOST 的描述一致。

### WP6 CI 门禁按平台拆分（侵入度 低）

- 目标：CI 重新有信号；门禁语义不变（零 skip 零失败），按平台集解释。
- 改动：`REQUIRED_MODULES` 拆为 `COMMON` / `DARWIN_ONLY`（seatbelt 及其断言）/ `LINUX_ONLY`（bwrap），按 `sys.platform` 选择，非本平台集合不加载而非 skip；agent controller 测试由夹具注入 provider，保留一个 darwin-only 真实 seatbelt 用例；`source-checks.yml` matrix `ubuntu-latest` + `macos-latest`，Linux job 安装 `bubblewrap`。
- 依赖：无。风险：低。
- 退出证据：两平台 job 均 `SOURCE_CHECKS_PASS`；报告 JSON 记录 `platform_set`。

### WP7 文档收敛（侵入度 低）

- 目标：现行规范与历史记录分离；状态只有一个来源。
- 改动：`docs/` 分 `current/` 与 `history/`，`DOC_INDEX.md` 列现行文档；路线图 / 规格状态与门禁数字来自 CI 生成的 `STATUS.json`；AGENTS.md 精简为指向现行文档。
- 依赖：WP5、WP6（以及 WP2、WP3 的接口变化）。风险：低。
- 退出证据：路线图不再出现互相矛盾的状态；新贡献者可在 DOC_INDEX 中 5 份文档内找到现行规则。

### WP8 控制器投影统一（可选，侵入度 高）

- 目标：1.3 Program 享有与 1.2 相同的 readback / recovery / budget 投影。
- 改动：`build_state._apply_attempt_event` 识别 `BUILD_AGENT_REPAIR_REQUESTED`，`project_readback_attempts` 支持 AGENT executor；`AgentBuildController` 改用 `project_execution_state` / `attempt_budget`，去掉自有 started/finished 集合与 `len(events)` CAS；`read-build` 对 1.3 返回同构结构。
- 依赖：WP4。风险：高；建议在 1.3 成为默认路线前完成。
- 退出证据：1.2 与 1.3 的 readback 结构一致；1.3 e2e 用例在 `read-build` 中可恢复。

---

## 6. 建议

### 对本分支

1. 不以当前形态合入 main。最小合入条件：完成 WP1 中的一致性读、`validate_authority_chain` 接入、1.3 兼容、`control_snapshot` 委托、状态矩阵测试，并把测试加入 `REQUIRED_MODULES`。
2. 若短期内无法完成 WP1，退而求其次：`schema_version` 改为 `CONTROL_FACTS_DIRECT_V1`，`state` 改名 `direct_state`，文档删去 cancellation 用途，并补充“`stream_revision` 为读取结束时的计数，可能领先于所列事实”。
3. 闭合文档中 A3-migration 的闭合范围应明确“工具当前不支持流式迁移，活库规模不在验证范围”，而不只是“用户移出闭合条件”。

### 对仓库

4. 先修 S1 再做任何 dedup 推广；修复前不要把 `REVISION_V1_DEDUP` 用于真实 Program。
5. CI 恢复信号（WP6）应先于一切功能工作；连续 17 次红灯的门禁无法证明任何“全绿”声明。
6. 独立性的对外表述与实现对齐：在结果与 Readback 中记录 `fs_enforcement`、实际 provider、`SAME_OWNER`；文档统一到 ADR-0004 口径；不把 “contract independence” 写成安全属性。
7. 8.5 GB 问题的根因是热路径全量加载，而不是磁盘体积；dedup 与旁路视图只是缓解，优先做 WP2。
8. 把历史路线（约 60K 行）移位冻结，docs 按“现行 / 历史”分目录。

### 不建议做的事

- 不要为“修 TOCTOU”引入事件 hash 链或第二份状态副本；项目已有 revision CAS 原则，单事务读 / 上界过滤即可。
- 不要为了让 CI 变绿而放宽“零 skip”语义或移除 agent controller 测试；按平台拆集合即可。
- 不要在 `RevisionControlEventStore.__init__` 里自动建索引；保持“不自动迁移”，用离线工具。
- 不要用 `sandbox.provider` 继续表达执行模式；1.3 已有 `execution.mode`，两者必须一致或合并。

### 需要仓库所有者决定的事项

| 问题 | 选项 | 建议 |
| --- | --- | --- |
| 是否接受拆分 `_current` | 拆分（WP2）/ 保持全量加载，A3-read 仅作旁路监控 | 拆分。唯一触及热路径的方案。 |
| TRUSTED_HOST 基线下“独立性”的对外表述 | 维持 `CONTRACT_INDEPENDENCE` / 细化为 `…_DETECT_ONLY` 并记录 `fs_enforcement` | 细化。与“结论必须写实际模式”原则一致。 |
| 是否允许对控制库新建索引 | 离线工具 / 坚持零 schema 变化 | 离线工具。索引不在 `_require_exact_existing_schema` 检查范围。 |
| 1.3 何时成为默认 | WP4+WP8 完成后 / 先并存 | WP4 后允许生产使用并标 EXPERIMENTAL；WP8 后切默认。 |
| 是否接受 macOS runner 成本 | 双平台 matrix / 仅 Linux | 双平台。否则 seatbelt 保证不可审计。 |
| 历史 compiler/validator 去向 | 冻结移入 `legacy/` / 保持原位 | 冻结移位。已不在发布 `MODULES`。 |

---

## 附录 A：复现方法摘要

- **B1**：继承 `RevisionControlEventStore`，在 `list_events_by_types` 读到 ATTEMPT 家族时追加一条 `BUILD_AUTHORIZATION_REVOKED`，再调用 `build_control_view` → `state=APPROVED`、`stream_revision=3`，而 revision 3 是 REVOKED。
- **B2**：构造 p1（人工审批）→ p2（`rebind_from=p1`，审批带 `derived_authority` 指向 p1 的审批）→ 撤销 p1；`build_control_view(p2)` 返回 APPROVED，`validate_authority_chain(events, p2, now)` 抛 “build authorization or its source approval was revoked”。
- **B3**：以 `{"scope": {...}, "plan": {"schema_version": "1.3", ...}}` 作为 prepared payload 调用 `build_control_view` → `KeyError: 'source_event_id'`。
- **S1**：monkeypatch `DedupRevisionControlEventStore._prepare_entries` 加 `threading.Barrier(2)`，让 A 先准备、B 后准备、A 先进事务；A 提交后 `list_events` 抛 “source content reference is missing”，原始 SQL 可见悬空引用。
- **门禁**：`python3 -B tools/check_release_source.py --report out.json`（需 `jsonschema`、`cryptography`）；Linux 上得到 963 / 950 / 6 / 7。
- **查询计划**：`EXPLAIN QUERY PLAN SELECT * FROM control_events WHERE program_id=? AND stream_revision>? AND event_type IN (...)` → `SEARCH control_events USING INDEX control_events_program_revision (program_id=? AND stream_revision>?)`；库中仅有 `(program_id, stream_revision)` 一个显式索引。

## 附录 B：度量快照（2026-10-28）

| 项 | 值 |
| --- | --- |
| `src/` 总行数 | 92,239 |
| 历史路线（compiler、validator、semantic_contracts、service、control_kernel、portable_self_check.py.in） | 60,563 |
| 当前构建路线（build_*、revision_store*、control_view、acceptance_contract、source_intake） | 6,335 |
| `agents/` | 2,220 |
| `docs/` | 124 文件 / 28,342 行 |
| `tests/test_*.py` | 189 个文件；门禁 `REQUIRED_MODULES` 75 个 |
| 通用发布 `MODULES` | 51 个扁平模块 + `agents` 包；不含历史路线 |
