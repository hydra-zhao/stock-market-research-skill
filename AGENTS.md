# Public Agent orchestration profile

This file is a Codex-oriented example. Apply it only when the runtime is
explicitly identified as Codex; otherwise start with `docs/agent-default.md`.

Priority is fixed: business/research rules and validation gates →
`docs/agent-contract.md` → `docs/agent-default.md` → this Agent-specific
override. This profile changes execution mechanics only. It cannot change
domain semantics, provider contracts, validation rules, canonical outputs, or
deterministic workflow behavior.

## Review chain

- The primary agent owns architecture decisions, semantic changes, and final
  review.
- A lightweight subagent may handle a bounded, independently checkable task
  only when its scope, allowed and forbidden files, acceptance command, and
  return fields are stated up front.
- A reviewer checks the evidence, diff, and focused verification before a
  result is accepted.
- A delegation must report files read or changed, commands run, test results,
  unresolved risks, and whether domain rules were touched.

## Workflow-level orchestration

Treat a workflow as the unit of orchestration. If the Python workflow already
owns dispatch, provider concurrency, caching, retries, or fallback, do not
split those provider/data tasks into more Agents. Avoid uncontrolled
`Agent × workflow × provider` concurrency amplification; use serial execution
when independence, ordering, or shared-write safety is uncertain.

Use narrow repository search, artifact-first inspection, and focused tests.
Preserve unrelated working-tree changes and never infer private rules from
missing context. Agent profiles may tune concurrency, subagent use, search,
worktree handling, context loading, and test scheduling only.
