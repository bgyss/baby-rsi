# Session tutorial — operating siro in dialogue

This is a worked **conversational session**: what it looks like to operate the system from
inside Claude Code using the repo-local skills, instead of typing `siro` commands yourself.
Where [`operating_guide.md`](operating_guide.md) is the command reference (organized by
flags), this is a narrated end-to-end dialogue (organized by what you actually want to do).

The skills live in [`.claude/skills/`](../.claude/skills/) and are available as `/siro`,
`/siro-run`, `/siro-watch`, `/siro-govern`, `/siro-pilot` once Claude Code discovers them at
the start of a session in this repo. The transcript below is illustrative — exact numbers
and ids will differ — but the *shape* of every turn (read state → propose a plan → confirm
anything governed → run → report the objective result) is what the skills are built to do.

Throughout, two rules from `/siro` are always in force:

- **Tier 0 is the default** — local, offline, free. Going to Tier 1/2 is stated explicitly.
- **Agents propose, humans approve.** Anything that spends money, mutates state, or is
  governed is previewed and confirmed first; approvals are never self-granted.

---

## 1. "How's the system doing?" — observe first

> **You:** How's the research org doing right now?

Claude recognizes a status request and uses **`/siro-watch`**, which reads the archives with
the machine-readable `--json` flag (Goal 21) so it can report precise numbers:

```zsh
uv run siro --json summarize-research
uv run siro --json provider-report --model-calls runs/model_calls.jsonl
uv run siro --json list-approvals --status pending
```

> **Claude:** Here's the snapshot:
> - **Suite health:** `algorithm` 7/10 promoted, `training` 6/10, `policy` 3/10 (stuck —
>   no promotion in the last 4 cycles). Strategy diversity is healthy except in `policy`.
> - **Integrity:** 0 safety-gate failures, 1 reproducibility failure (`policy/sentiment_rules`).
> - **Spend:** \$0.00 — everything so far ran at Tier 0.
> - **Pending approvals:** none.
>
> The clear soft spot is the `policy` family. Want me to try a cycle there, or look at the
> reproducibility failure first?

It leads with the anomaly (`policy` stuck, one repro failure) rather than dumping raw output.

---

## 2. "Try to speed up pair_count" — run an experiment

> **You:** Let's improve the algorithm side. Try to make `pair_count` faster.

Claude uses **`/siro-run`**. The intent maps to the research suite; the task lives at
`tasks/research/algorithm/pair_count`. Because a run mutates archives (and would spend money
at Tier 1), it **previews with `--dry-run` first** and asks for confirmation:

```zsh
uv run siro --dry-run run-research tasks/research/algorithm/pair_count --config config/tier0.local.yaml
```

> **Claude:** Plan:
> - **Command:** `siro run-research tasks/research/algorithm/pair_count`
> - **Tier:** Tier 0 (local, offline, free)
> - **Effect:** runs the org on the task and writes to `runs/research_attempts.jsonl`
> - **Governance:** none
>
> This is free and local. Run it?

> **You:** Yes.

```zsh
uv run siro run-research tasks/research/algorithm/pair_count --config config/tier0.local.yaml
```

> **Claude:** Done. **Promoted.** The candidate replaced the quadratic scan with a
> complement-count pass; the objective evaluator measured fewer executed lines on the fixed
> workload (the primary metric), the reproducibility gate matched on rerun, and the safety
> gate passed. The improvement is recorded as a promotion in the archive.

Note what Claude reports: the **objective** result (the evaluator's metric and the gates),
not a self-assessment that the code "looks faster."

---

## 3. "Run it at a bigger compute budget" — a governed action

> **You:** Nice. Can we run that under a larger compute budget to be sure?

A larger compute tier is **governed** (Goal 11). Claude previews it and surfaces the gate
rather than trying to push through it:

```zsh
uv run siro --dry-run run-scaled tasks/research/algorithm/pair_count --compute-tier 1
```

> **Claude:** Heads up — this one is gated:
> - **Tier:** Tier 2 (governed, human-gated)
> - **Governance:** compute-tier > 0 requires a human approval bound to `(experiment, tier)`,
>   plus a recorded pass at the next-smaller tier.
>
> So this needs an approval before it can run. Want me to record the request so you can
> approve it?

> **You:** Yes, request it.

Claude switches to **`/siro-govern`** to record the request (an agent *may* request; only a
human decides):

```zsh
uv run siro request-approval budget_increase \
    --target "pair_count@tier1" \
    --payload '{"experiment":"pair_count","tier":1}' \
    --rationale "confirm the speedup holds under a larger compute budget"
```

> **Claude:** Recorded pending request `a1b2c3d4e5f6`. I can't approve it myself — that's a
> human decision. When you're ready, you (a registered operator) approve it:
>
> ```zsh
> uv run siro approve a1b2c3d4e5f6 --by <your-operator-id>
> ```
>
> Once it's approved, say the word and I'll re-run the scaled command.

> **You:** Approved it. Go.

```zsh
uv run siro run-scaled tasks/research/algorithm/pair_count --compute-tier 1
```

> **Claude:** Ran under compute tier 1 within the wall-clock + memory ceiling; the result
> reproduced the promotion. No budget breach. Recorded to the archive.

The boundary held the whole way: Claude requested, *you* approved, and only then did the
governed action run.

---

## 4. "Should we pay for frontier models?" — the bounded pilot

> **You:** Before we spend on frontier models, can we tell if it's worth it?

That's exactly the bounded operational pilot (Goal 20). Claude uses **`/siro-pilot`**:

```zsh
uv run siro pilot-init      # fixed plan + transcript
uv run siro pilot-run       # required arms (Tier 0 + cheap frontier)
uv run siro pilot-report    # cost-per-promotion report
```

Before the frontier arm spends money, it confirms with you and checks budget headroom is
approved. Then it interprets the report:

> **Claude:** Pilot report written to `reports/pilot_report.md`. Summary: the cheap-frontier
> arm promoted 2 more tasks than Tier 0 at \$0.83 per accepted promotion; hidden-test and
> reproducibility rates held. The report's recommendation is **revise** — frontier helped on
> `policy` but not `algorithm`. Acting on that (a real scale-up) is a separate human-gated
> governance step; the pilot doesn't authorize it, and neither do I.

---

## 5. Keep it monitored

> **You:** Keep an eye on things while I work.

Claude runs **`/siro-watch`** on a cadence (you can drive this with `/loop`), reporting only
**deltas** — new failures, newly-pending approvals, spend crossing a threshold — and escalates
anything human-gated instead of acting on it.

---

## What to take away

- You never typed a raw `siro` command — the skills composed them, and you stayed in plain
  language.
- Every governed or money-spending step was **previewed (`--dry-run`), confirmed, then run**;
  the approval was **yours**, never the agent's.
- Outcomes were reported from the **objective evaluator and gates**, negatives included.
- Dropping any of this to Tier 0 is config-only — the same dialogue, fully local and free.

For the underlying commands and flags, see [`operating_guide.md`](operating_guide.md). For
the bounds these skills enforce, see [`13_self_improvement_loop.md`](13_self_improvement_loop.md)
and [`05_evaluation_and_safety_gates.md`](05_evaluation_and_safety_gates.md).
