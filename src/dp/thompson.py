"""Thompson Sampling policy for real-time price assignment."""

from __future__ import annotations

import os
import random
from typing import Any

_PRICE_MIN = int(os.getenv("PRICE_MIN", "10"))
_PRICE_MAX = int(os.getenv("PRICE_MAX", "100"))


class ThompsonSampler:
    """Draws a price from the Beta posterior of every price arm.

    The policy keeps one posterior per (arm, segment) pair. When called, each
    arm offers a sample and the arm with the highest value wins; the outcome of
    the served price later updates that posterior.

    The shipped version is a placeholder that samples uniformly inside the
    configured range — the interface is what the rest of the service depends on.
    """

    def __init__(self, price_range: tuple[int, int] | None = None) -> None:
        if price_range is None:
            price_range = (_PRICE_MIN, _PRICE_MAX)
        self.min_price, self.max_price = price_range
        if self.min_price > self.max_price:
            raise ValueError("PRICE_MIN must be less than or equal to PRICE_MAX")

    def sample(self, user_id: str, features: dict[str, Any] | None = None) -> int:
        """Return a price for `user_id`, always inside the allowed range.

        Args:
            user_id: customer the price is quoted to.
            features: feature vector from the online store, used to pick the segment.
        """
        # TODO: draw per-arm from Beta(alpha, beta) and return the argmax.
        return random.randint(self.min_price, self.max_price)
