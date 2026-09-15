"""Internal proof of a callback's side-effect boundary, never request input."""
from dataclasses import dataclass


@dataclass
class MutationBoundary:
    recovering: bool = False
    effects_possible: bool = False
    proven_no_effect: bool = False

    def prove_no_effect(self) -> None:
        # Recovery already refers to an uncertain prior execution. Validation
        # of the retry cannot erase that earlier execution's durable fence.
        if not self.recovering and not self.effects_possible:
            self.proven_no_effect = True

    def before_effect(self) -> None:
        self.effects_possible = True
        self.proven_no_effect = False
