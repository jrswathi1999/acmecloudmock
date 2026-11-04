"""Customer traffic: real checkouts against the running shop.

    python -m ops.traffic [n]
"""
import random
import sys
from collections import Counter

from ops import common

PRODUCT_IDS = [1, 2, 3]
REGIONS = ["US", "US", "EU", "APAC"]  # US twice as likely as EU or APAC


def run(n: int) -> Counter:
    rng = random.Random()
    statuses = Counter()
    for _ in range(n):
        status, _ = common.http(
            "POST", "/checkout",
            {"product_id": rng.choice(PRODUCT_IDS), "qty": 1, "region": rng.choice(REGIONS)},
        )
        statuses[status] += 1
    summary = ", ".join(f"{count} x {'no connection' if code == 0 else f'HTTP {code}'}"
                        for code, count in sorted(statuses.items()))
    common.say(f"  traffic: {n} checkouts -> {summary}")
    return statuses


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
