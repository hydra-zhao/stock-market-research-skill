# Claude Code orchestration profile

Apply this file only when the runtime explicitly identifies itself as Claude
Code; otherwise use `docs/agent-default.md`.

- Follow `docs/agent-contract.md` and the business/research rules first.
- Prefer one workflow-level task and artifact-first inspection. Use subagents
  only when explicitly available and when the work is isolated and independently
  checkable.
- Every delegation states scope, allowed and forbidden files, the acceptance
  command, and return fields: files, commands, tests, unresolved risks, and
  whether domain rules were touched.
- Do not split provider/data work from a workflow that already owns internal
  concurrency. Avoid multiplying Agent, workflow, and provider concurrency.
- Keep context focused: read the relevant instruction and artifact, then test
  the smallest affected scope. Preserve unrelated working-tree changes.

This profile changes scheduling, search, context, worktree, and test choices
only. It cannot change domain semantics, validation gates, provider contracts,
canonical outputs, or deterministic workflow behavior.
