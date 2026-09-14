# Shared Agent contract

All runtimes use this priority order:

1. Business/research rules and validation gates
2. This shared Agent contract
3. `docs/agent-default.md` (Generic Safe Profile)
4. An explicitly identified Agent-specific orchestration override

Agent-specific profiles may choose scheduling details such as concurrency,
subagent use, repository search, worktree handling, context management, and
test scheduling. They may not override domain semantics, validation rules,
provider contracts, canonical outputs, or deterministic workflow behavior.

The Agent is an orchestration layer. Python workflows remain responsible for
their defined data, provider, concurrency, validation, and artifact behavior.
If a workflow already manages internal concurrency, do not decompose it into
provider/data Agent tasks. Prevent uncontrolled `Agent × workflow × provider`
amplification.

Use canonical artifacts and their validation as the source of delivered facts.
An Agent must preserve `unknown`, `incomplete`, and `unverified` states rather
than filling gaps from memory or tool output. Deterministic renderers and
delivery manifests remain authoritative where the project defines them.

Profiles may improve routing or verification ergonomics only. They are not a
second business-rule, algorithm, data, or output-contract layer.
