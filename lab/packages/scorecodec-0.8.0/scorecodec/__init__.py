"""Deliberately incompatible old dependency: score() is not exported."""
def legacy_score(amount: float) -> float:
    return round(amount * 0.04, 2)
