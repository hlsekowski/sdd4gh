# ADR 0010: OpenCode coding-agent execution

> **Purpose:** Records the decision to use OpenCode as the coding-agent execution technology for the SDD process.
> **Read when:** implementing or changing the coding-agent execution layer.
> **Owns:** the OpenCode selection and its boundaries; ADR 0007 continues to own SDD process responsibilities.

## Status

Accepted

## Context

ADR 0004 defines the worker/task execution model but deliberately selects no runtime technology. Its §9 requires a separate decision for each runtime technology when introduced.

ADR 0008 previously bundled LangGraph, OpenCode, Kubernetes, and LiteLLM into a single decision record. This ADR separates the OpenCode decision as required by ADR 0004 §9.

## Decision

Use [OpenCode](https://opencode.ai/docs/) as the coding-agent execution technology for the SDD process.

OpenCode performs the SDD coding-agent role. Its configurable provider endpoint supports connecting to an OpenAI-compatible model endpoint. The project configuration defaults every agent to local inference. A non-local provider may be used only when its no-charge terms and account safeguards have been verified; paid API usage, subscriptions, and defaults that can incur charges are not authorized. OpenCode configuration alone cannot verify a provider's billing terms. Local inference is one supported zero-cost option, not the only permitted option.

OpenCode can use the LiteLLM OpenAI-compatible endpoint (ADR 0012) without taking over workflow orchestration.

Configured hosted models, including NVIDIA models, are subject to an opt-in
developer-only drift check. The check compares the repository's
`models_policy.json` functionality policy and NVIDIA model catalog with
`opencode.json`, smoke-tests discovered and configured models, and reports
candidate additions and removals. It never edits model configuration.

## Consequences

### Positive

- Strong fit alongside LangGraph and LiteLLM for the SDD coding-agent role.
- Defaults to a local model endpoint, preserving the project's zero-cost constraint while allowing verified no-charge alternatives.
- Separate ADR per technology as ADR 0004 §9 requires.

### Limitations

- Local inference is the default. Developers who explicitly select a non-local provider must verify that the provider and account cannot incur charges.
- OpenCode does not replace workflow orchestration; that remains LangGraph's concern (ADR 0009).

## Related

- [ADR 0003: Local AI-Driven Development Workflow](0003-local-development-workflow.md) — local-first and zero-cost constraints
- [ADR 0004: Worker and Task Execution Model](0004-worker-task-model.md) — worker/task invariants and runtime neutrality
- [ADR 0007: SDD Process](0007-sdd-process.md) — responsibilities of the process that invokes a coding agent
- [ADR 0008: Workflow runtime and model-routing selection](0008-workflow-runtime-and-model-routing.md) — umbrella decision record
- [ADR 0012: LiteLLM model routing](0012-litellm-model-routing.md) — model routing for workflow-agent calls
- [Project constitution](../constitution.md) — constraints for technology selection
