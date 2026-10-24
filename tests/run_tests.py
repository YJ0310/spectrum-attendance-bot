#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Unified E2E Test Runner for SPeCTRUM Automated Attendance System.
Executes test tiers:
  - Tier 1: Core Feature Coverage (tests/test_tier1_features.py)
  - Tier 2: Boundary & Corner Cases (tests/test_tier2_boundaries.py)
  - Tier 3: Cross-Feature Combinations (tests/test_tier3_combinations.py)
  - Tier 4: Real-World Application Scenarios (tests/test_tier4_scenarios.py)

Usage:
  python3 tests/run_tests.py              # Run all tiers
  python3 tests/run_tests.py --tier 1     # Run Tier 1 only
  python3 tests/run_tests.py --tier 2     # Run Tier 2 only
  python3 tests/run_tests.py --tier 3     # Run Tier 3 only
  python3 tests/run_tests.py --tier 4     # Run Tier 4 only
  python3 tests/run_tests.py -v           # Verbose test runner
"""

import argparse
import os
import sys
import time
import unittest
import warnings

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Disable background long-polling daemons during test execution
os.environ["ENABLE_BOT_DAEMON"] = "0"
os.environ["ENABLE_CLASS_WATCHER"] = "0"

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

TIER_MODULES = {
    1: ("Tier 1: Feature Coverage", "tests.test_tier1_features"),
    2: ("Tier 2: Boundary & Corner Cases", "tests.test_tier2_boundaries"),
    3: ("Tier 3: Cross-Feature Combinations", "tests.test_tier3_combinations"),
    4: ("Tier 4: Real-World Scenarios", "tests.test_tier4_scenarios"),
}


def run_tier(tier_num: int, tier_name: str, module_name: str, verbosity: int = 1) -> tuple[unittest.TestResult, float]:
    """Loads and executes a single test tier module."""
    print("=" * 72)
    print(f"▶ Running {tier_name} ({module_name})")
    print("=" * 72)

    loader = unittest.TestLoader()
    try:
        suite = loader.loadTestsFromName(module_name)
    except Exception as e:
        print(f"❌ Failed to load {module_name}: {e}")
        result = unittest.TestResult()
        result.errors.append((module_name, str(e)))
        return result, 0.0

    runner = unittest.TextTestRunner(verbosity=verbosity)
    start_time = time.time()
    result = runner.run(suite)
    elapsed = time.time() - start_time
    print(f"⏱️ Finished in {elapsed:.2f}s\n")
    return result, elapsed


def main():
    parser = argparse.ArgumentParser(description="SPeCTRUM E2E Test Suite Runner")
    parser.add_argument(
        "--tier",
        type=int,
        choices=[1, 2, 3, 4],
        help="Run only a specific test tier (1, 2, 3, or 4)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose test execution output",
    )
    args = parser.parse_args()

    verbosity = 2 if args.verbose else 1

    selected_tiers = [args.tier] if args.tier else [1, 2, 3, 4]

    print("\n" + "=" * 72)
    print("🚀 SPeCTRUM AUTOMATED ATTENDANCE — E2E TEST RUNNER")
    print("=" * 72)
    print(f"Working Directory : {PROJECT_ROOT}")
    print(f"Tiers to Execute  : {selected_tiers}")
    print(f"Python Version    : {sys.version.split()[0]}")
    print("=" * 72 + "\n")

    overall_start = time.time()
    tier_results = []
    total_failures = 0
    total_errors = 0

    for t_num in selected_tiers:
        t_name, mod_name = TIER_MODULES[t_num]
        result, elapsed = run_tier(t_num, t_name, mod_name, verbosity=verbosity)
        tier_results.append((t_num, t_name, result, elapsed))
        total_failures += len(result.failures)
        total_errors += len(result.errors)

    overall_elapsed = time.time() - overall_start

    # Print Summary Table
    print("\n" + "=" * 72)
    print("📊 TEST SUITE EXECUTION SUMMARY")
    print("=" * 72)
    print(f"{'Tier':<35} | {'Run':<5} | {'Pass':<5} | {'Fail':<5} | {'Skip':<5} | {'Time':<6}")
    print("-" * 72)

    total_run = 0
    total_passed = 0
    total_skipped = 0

    for t_num, t_name, res, elapsed in tier_results:
        runs = res.testsRun
        fails = len(res.failures) + len(res.errors)
        skips = len(res.skipped)
        passed = runs - fails - skips

        total_run += runs
        total_passed += passed
        total_skipped += skips

        status_flag = "✅ PASS" if fails == 0 else "❌ FAIL"
        print(f"{t_name:<35} | {runs:<5} | {passed:<5} | {fails:<5} | {skips:<5} | {elapsed:.2f}s  {status_flag}")

    print("-" * 72)
    print(
        f"{'TOTALS':<35} | {total_run:<5} | {total_passed:<5} | {total_failures + total_errors:<5} | {total_skipped:<5} | {overall_elapsed:.2f}s"
    )
    print("=" * 72)

    if total_failures == 0 and total_errors == 0:
        print(f"\n🎉 ALL TESTS PASSED! ({total_passed} passed, {total_skipped} skipped in {overall_elapsed:.2f}s)\n")
        sys.exit(0)
    else:
        print(f"\n❌ TEST SUITE FAILED with {total_failures} failures and {total_errors} errors.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
