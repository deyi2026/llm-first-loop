#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D"
cat > "$D/calc.py" <<'PYEOF'
def median(nums):
    nums = list(nums)
    n = len(nums)
    return nums[n // 2]


def mean(nums):
    nums = list(nums)
    return sum(nums) / len(nums)
PYEOF
cat > "$D/test_calc.py" <<'PYEOF'
import unittest

from calc import median, mean


class TestCalc(unittest.TestCase):
    def test_median_odd(self):
        self.assertEqual(median([3, 1, 2]), 2)

    def test_median_single(self):
        self.assertEqual(median([7]), 7)

    def test_median_even(self):
        self.assertEqual(median([1, 3, 2, 5, 4, 6]), 3.5)

    def test_mean(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)


if __name__ == "__main__":
    unittest.main()
PYEOF
printf '#!/usr/bin/env bash\ncd "$(dirname "$0")"\npython3 -m unittest -v test_calc\n' > "$D/run_tests.sh"
chmod +x "$D/run_tests.sh"
shasum -a 256 "$D/test_calc.py" | awk '{print $1}' > "$D/.fixture-test-sha"
if (cd "$D" && bash run_tests.sh >/dev/null 2>&1); then
  echo "SETUP-BROKEN: tests already pass at setup" >&2; exit 3
fi
