# Goal Prompt 13 - Documentation Consistency Contract

## Goal

Make repository documentation consistency a checked contract rather than a manual habit.
This goal addresses the first refinement from `../14_project_retrospective.md`: status drift
between the README, goal prompts, and implementation reality.

The docs are a source of truth for future agents. A stale README, stale goal map, or missing
Self-improvement section can cause the next build step to start from a false premise.

Depends on Goals 01-12.

## Requirements

- Add a machine-readable goal manifest, for example `docs/goal_prompts/goals.json`, that
  records for each goal:
  - goal number,
  - title,
  - status (`implemented` or `specified`),
  - capability tier or refinement category,
  - prompt path,
  - primary modules/artifacts,
  - one-sentence summary.
- Add a docs consistency checker, for example `siro check-docs` or a script under `scripts/`,
  that verifies:
  - every `docs/goal_prompts/goal_*.md` appears in the manifest,
  - every manifest prompt path exists,
  - every goal prompt contains a `## Self-improvement` section,
  - `README.md` mentions the current implemented/spec status accurately,
  - the README document map contains every numbered top-level doc.
- Add a lightweight docs privacy check for Codex-authored docs, scoped to repo docs and
  goal prompts, that rejects accidental personal-machine paths unless explicitly allowed.
- Update `README.md` to explain the manifest/checker and keep the implementation-status
  section generated or mechanically checked against the manifest.

## Acceptance criteria

- Running the checker passes on the current repository.
- If a goal prompt is added without a manifest entry, the checker fails with a clear error.
- If a goal prompt lacks `## Self-improvement`, the checker fails with the prompt path.
- If README status says a goal is unimplemented while the manifest says implemented, the
  checker fails.
<!-- docs-privacy-allow-start: intentional forbidden-path examples for the privacy checker -->
- The docs privacy check catches accidental `/Users/`, `/home/`, `.codex`, `/Applications`,
  and `/private/tmp` references in generated docs unless explicitly allowlisted.
<!-- docs-privacy-allow-end -->
- The checker is wired into an existing thin task (`mise run ...`) or documented in the
  README with the exact command.

## Constraints

- Do not make documentation generation a large framework. Keep it readable and easy to
  audit.
- Do not overwrite hand-written narrative sections unless the generated section is clearly
  delimited.
- Keep repo-internal paths project-root-relative in docs.
- Do not mark a goal implemented unless the implementation and tests actually exist.

## Self-improvement

This goal makes the build process itself harder to mislead. Documentation and prompt drift
become observable failures in the same bounded improvement cycle defined in
`../13_self_improvement_loop.md`.

- **Records**: docs-check results, including failures, should be recorded in the run output
  or CI/task log; any future automated summaries may archive repeated docs failure patterns.
- **Reflects / proposes**: the outer loop may propose documentation or manifest updates,
  but they are checked mechanically before acceptance.
- **Validated / gated**: a docs change promotes only when the consistency checker and
  privacy scan pass.
- **Bounds**: the checker may report drift but may not silently change implemented status,
  weaken safety docs, or remove required Self-improvement sections without human review.
