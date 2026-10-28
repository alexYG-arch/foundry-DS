# A4：当前视图与历史交接

`rsi_handoff.build_current_view` composes a bounded view from:

- a frozen baseline `id` + `sha256`;
- this-round changes;
- affected assertions;
- evidence references;
- history references (ID/hash, never embedded report text);
- pending items and limitations.

`render_markdown` is display-only. The view is not acceptance, and a reference
does not prove that the referenced bytes are complete or current. History is
kept by identity; a full old report is not recursively copied into a new report.

The existing RSI cases, Wiki, Reviewer and TDD tools remain the source of their
own records; this module adds a current-view envelope, not a second scheduler.
