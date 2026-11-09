"""Compatible upgraded scoring dependency, same public API."""
def score(amount: float) -> float:
    return round(amount * 0.04, 2)
