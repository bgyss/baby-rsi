"""Defensive stub for the confirmation (Regime C) task (Goal 27).

This task's authority is the Goal 26 ``external-oracle`` adapter, which scores the candidate on
an ingested, approved, signed wet-lab assay result — it runs **no candidate code** and never
executes this file. The stub exists only because the task layout requires an ``eval.py``; if it
were ever run directly (a misconfiguration), it emits a non-passing metric rather than
fabricating a result, so a confirmation can never come from the execution plane.
"""

import json


def main():
    print(
        json.dumps(
            {
                "primary": 0.0,
                "passed": False,
                "secondary": {},
                "notes": "",
                "error": (
                    "confirmation is governed: a measured_potency result must arrive as a "
                    "signed, human-approved external assay result (Goal 26), not from the "
                    "execution plane"
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
