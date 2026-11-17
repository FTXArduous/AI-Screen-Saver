import math
from ..models import CandidateResult

RADICES = (8, 10, 12, 16, 20, 24, 32, 36)

def digit_count(n: int, radix: int) -> int:
    return 1 if n <= 1 else math.ceil(math.log(n, radix))

def build_candidates() -> list[CandidateResult]:
    results = []
    max_integer = 100_000
    # 24 decimal fractional places translated into radix digits; ceiling preserves at least that resolution.
    for radix in RADICES:
        integer_digits = digit_count(max_integer, radix)
        fractional_digits = math.ceil(24 * math.log(10, radix))
        total = integer_digits + fractional_digits
        compactness = max(1.0, 5.0 - (total - 21) * 0.22)
        # Scores are explicit hypotheses/priors, not measured outcomes.
        for subdivision in ("uniform", "recursive"):
            recursive = subdivision == "recursive"
            uniformity = 4.8 if not recursive else 3.4
            navigation = {8: 3.0, 10: 4.4, 12: 4.8, 16: 4.2, 20: 3.4, 24: 3.2, 32: 3.0, 36: 2.7}[radix]
            compute = {8: 4.7, 10: 4.2, 12: 3.8, 16: 4.9, 20: 3.7, 24: 3.6, 32: 4.8, 36: 3.5}[radix]
            if recursive:
                compute -= 0.35
                navigation -= 0.1
            astronomy = 3.5  # neutral prior until real catalog and spatial-index benchmarks exist
            total_score = (compactness + uniformity + navigation + compute + astronomy) / 5
            cid = f"C{len(results)+1:02d}"
            results.append(CandidateResult(cid, radix, subdivision, integer_digits, fractional_digits,
                round(compactness, 3), round(uniformity, 3), round(navigation, 3), round(compute, 3),
                astronomy, round(total_score, 3)))
    return results
