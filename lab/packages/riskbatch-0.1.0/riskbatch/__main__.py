"""Run score calculation, optionally invoking a compiled native extension."""
import ctypes
import os
import sys
from scorecodec import score


def main() -> None:
    amount = 100.0
    result = score(amount)
    if "--native" in sys.argv:
        path = os.environ.get("RISKBATCH_NATIVE_LIBRARY", "libscoremath.so")
        library = ctypes.CDLL(path)
        native_score = library.score_native
        native_score.argtypes = [ctypes.c_int]
        native_score.restype = ctypes.c_int
        result = float(native_score(int(amount))) / 100
    assert abs(result - 4.0) < 1e-9, f"Unexpected calculation: {result}"
    print(f"Scored {amount:.2f} EUR -> {result:.2f} EUR: OK")


if __name__ == "__main__":
    main()
