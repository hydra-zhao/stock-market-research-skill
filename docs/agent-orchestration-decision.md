# Agent orchestration decision record

- Agent orchestration is separated from the shared business/research core.
- A Generic Safe Profile is the conservative fallback for unknown runtimes.
- Codex, Claude Code, and Cursor profiles are opt-in overrides for execution
  mechanics only; no duplicated implementation is maintained per Agent.
- Workflow-level orchestration remains separate from provider/data orchestration.
- Python core, provider contracts, validation gates, and canonical outputs
  remain shared.
- Future optimization requires measured workflow evidence; theoretical
  parallelism alone is not a reason to change the core.

This public record intentionally omits private benchmarks, workflow names,
cache identifiers, model settings, user data, and production incidents.
