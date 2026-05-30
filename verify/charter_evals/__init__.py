"""Charter regression evals (V3 #7a, B6 borrow).

Borrowed contract source: ECC ``eval-harness`` + ``agent-eval`` skills
(`affaan-m/ecc`, MIT). See ``docs/ECC_BORROWS.md`` B6.

Public surface
--------------

The harness itself lives in :mod:`verify.charter_evals.harness`.
Eval definitions per role live under
``verify/charter_evals/<role>/*.yaml`` and are loaded by the harness on
demand. Results write into the decision ledger
(``shared.audit.decision_ledger``) so charter regression history is
auditable and chained.
"""

from verify.charter_evals.harness import (
    CapabilityEval,
    EvalCriterion,
    EvalRunResult,
    PassAtK,
    evaluate_charter,
    pass_at_k,
    run_capability_eval,
)

__all__ = [
    "CapabilityEval",
    "EvalCriterion",
    "EvalRunResult",
    "PassAtK",
    "evaluate_charter",
    "pass_at_k",
    "run_capability_eval",
]
