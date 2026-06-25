# Research task — `pair_count` (algorithm/implementation)

## Objective

Improve `count_pairs(nums, target)` in `solution.py` so it returns the number of
**unordered index pairs** `(i, j)` with `i < j` and `nums[i] + nums[j] == target`,
using **less work** than the naive baseline.

## Success metric

- **Primary:** `executed_lines` — the number of source lines your `solution.py`
  executes on a fixed, hidden performance workload (lower is better). The naive
  baseline scans every pair, so it is quadratic; an `O(n)` approach (e.g. a single
  pass with a running count of previously-seen values) executes far fewer lines.
- **Correctness precondition (`passed`):** your `count_pairs` must return the exact
  right count on every held-out case **and** on the performance workload. A wrong-but-fast
  candidate can never be promoted — correctness is checked first.

## Allowed edit surface

- `solution.py` only. Keep the public signature `count_pairs(nums, target)`.

## Constraints

- Pure standard-library Python. No file, network, or subprocess access (the static
  safety gate rejects any candidate that does I/O, and the execution plane is offline).
- The evaluator (`eval.py`) and the held-out workload are read-only to you and never
  appear here — promotion is decided by the objective evaluator, not by self-judgment.
