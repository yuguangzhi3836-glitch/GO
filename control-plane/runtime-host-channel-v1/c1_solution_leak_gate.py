"""U6: the DeepSeek Solution-Leak Gate. An interface, and today only a bypass.

What this is for
----------------
A solution-leak gate exists to stop a candidate answer from being handed to the model
that is supposed to produce that answer: if the expected solution is already in the
prompt, a green result proves nothing about the model and everything about the leak. The
intended checker is a DeepSeek call that reviews the assembled prompt for one.

What this round implements
--------------------------
Nothing of that. This round adds the SEAM ONLY: the decision point exists, every caller
can ask it, and its answer is recorded - so the day the checker arrives, it arrives behind
an interface that already has callers rather than as a new wire threaded through the
channel. No SDK, no secret, no API configuration and no network call is added here.

The one thing this file is careful about
----------------------------------------
`GATE_DISABLED` and `PASS` are NOT the same claim, and this module never lets them look
like one. A disabled gate has not reviewed anything, so its record says `reviewed=False`
next to `decision="PASS"`. That pair is the honest description of a bypass: "we did not
look, and we are not blocking". Nothing downstream may read `decision == "PASS"` alone as
evidence that a checker ran - it must also see `reviewed`, which only a real checker may
set True.

Fail-closed on a half-done enable
---------------------------------
Turning the switch on without a checker must REFUSE, not pass. `evaluate()` therefore
raises rather than returning a permissive record when `SOLUTION_LEAK_GATE_ENABLED` is
True and no implementation is present. The alternative - a switch that silently does
nothing - is the failure mode this whole file exists to prevent: someone flips it in the
belief they have enabled a gate, and the gate is not there.
"""
from __future__ import annotations

from c1_execution_contract import Refused

# The switch. False is the only supported value today; see the module docstring.
SOLUTION_LEAK_GATE_ENABLED = False

# Stable vocabulary, so a caller never has to match on prose.
DECISION_PASS = "PASS"
DECISION_REFUSED = "REFUSED"
REASON_GATE_DISABLED = "GATE_DISABLED"
REASON_GATE_NOT_IMPLEMENTED = "SOLUTION_LEAK_GATE_NOT_IMPLEMENTED"

# The model a real checker would use. Named but never reached: nothing in this round can
# produce a call, and `model_called` is False in every record that can be returned.
GATE_MODEL = "deepseek"


def evaluate(*, objective: str, scope: str, history=None) -> dict:
    """Decide whether this task's prompt may be shown to the executing model.

    Currently always the bypass record: `decision="PASS"`, `reason="GATE_DISABLED"`,
    `reviewed=False`, `model_called=False`, `calls=0`. Those five fields together are the
    decision; `decision` alone is not.

    Raises `Refused("SOLUTION_LEAK_GATE_NOT_IMPLEMENTED")` when the switch is on and no
    checker exists. That is deliberate and is the function's only other outcome: an
    enabled-but-absent gate must stop the work, because the work would otherwise proceed
    on the strength of a gate that was never run.
    """
    if not SOLUTION_LEAK_GATE_ENABLED:
        return {
            "gate": "solution_leak",
            "enabled": False,
            "decision": DECISION_PASS,
            "reason": REASON_GATE_DISABLED,
            "reviewed": False,
            "model": None,
            "model_called": False,
            "calls": 0,
        }
    # No checker is implemented. Reaching here means someone enabled the switch expecting
    # enforcement; refusing is the only honest answer.
    raise Refused(REASON_GATE_NOT_IMPLEMENTED)


def describe() -> dict:
    """The gate's current mode, for a `--check` line or a test. Performs no work."""
    return {
        "gate": "solution_leak",
        "enabled": bool(SOLUTION_LEAK_GATE_ENABLED),
        "mode": "BYPASS" if not SOLUTION_LEAK_GATE_ENABLED else "UNIMPLEMENTED",
        "decision": DECISION_PASS if not SOLUTION_LEAK_GATE_ENABLED else DECISION_REFUSED,
        "reason": REASON_GATE_DISABLED if not SOLUTION_LEAK_GATE_ENABLED
        else REASON_GATE_NOT_IMPLEMENTED,
        "enforcement": "DEFERRED",
    }
