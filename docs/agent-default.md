# Generic Safe Agent profile

Use this profile when no explicitly identified Agent-specific profile exists.
An unknown runtime must not guess that it is Codex, Claude Code, or Cursor
merely because it supports shell commands, parallel tools, or subagents.

The safe default is one workflow-level execution at a time, conservative
context loading, narrow repository search, and focused verification. Upgrade a
capability only after the runtime explicitly confirms it and the change remains
independently checkable.

## Capability matrix

| Capability | Safe upgrade condition |
|---|---|
| `supports_parallel_tools` | Parallelize only independent, top-level, read-only work; never multiply workflow concurrency. |
| `supports_subagents` | Delegate bounded work with explicit scope, file boundaries, acceptance command, and a structured return summary. |
| `supports_isolated_worktree` | Use an isolated worktree only for independent edits; otherwise preserve the current worktree. |
| `supports_repo_index` | Use an index to narrow search, but never infer missing rules or semantics from it. |
| `supports_context_compaction` | Compact only after preserving the active contract, artifact paths, and validation requirements. |
| `supports_background_tasks` | Allow only low-risk, read-only, independently verifiable work with an explicit completion check. |

When Python owns workflow, dispatch, or provider concurrency, the Agent must
not split provider/data subtasks. Avoid uncontrolled `Agent × workflow ×
provider` multiplication.

This profile controls orchestration only. It cannot alter business/research
semantics, validation gates, provider contracts, canonical artifacts, or output
contracts. See `docs/agent-contract.md` for the shared boundary.
