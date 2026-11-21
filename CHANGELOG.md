# Changelog

Notable project changes are recorded under `Unreleased` and updated for each pull request.

## Unreleased

- Added bounded issue-intake analysis with ranked clarification options, title-fit checks, and idempotent issue comments.
- Centralized shared confidence bands for issue analysis and decision gates.
- Added an explicit opt-in NVIDIA model drift check that reports add/remove candidates without modifying OpenCode configuration.
- Added an opt-in, monitor-only Ollama model drift check with memory-fit estimates and supervised fit verification.
- Added Ollama model-store disk-space warnings and safety stops before pulls and model loads.
- Added reproducible OpenCode runtime model-resolution and opt-in local smoke validation.
- Added least-privilege OpenCode agent permissions with shell, edit, and delegation regressions.
- Added a catalog format for documenting intentionally dropped code paths.
- Added a standardized GitHub issue intake template at `.github/issue_template.md`.
- Audited and repaired Markdown references, removed cross-repository issue citations, and extended checks to all repository Markdown files.
- Added a pinned, developer-only OpenCode config validation check.
