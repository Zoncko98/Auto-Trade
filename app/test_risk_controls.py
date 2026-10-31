from risk_controls import RiskControls, RiskLimits

risk = RiskControls(RiskLimits(
    initial_capital=100.00,
    max_position_pct=25.0,
    max_daily_loss=5.00,
    max_open_positions=3,
))

tests = [
    ("valid order", risk.check_new_position(20, 100, 100, 0, 0)[0], True),
    ("oversized order", risk.check_new_position(30, 100, 100, 0, 0)[0], False),
    ("insufficient cash", risk.check_new_position(20, 10, 100, 0, 0)[0], False),
    ("daily loss limit", risk.check_new_position(20, 100, 100, 0, -5)[0], False),
    ("position limit", risk.check_new_position(20, 100, 100, 3, 0)[0], False),
    ("zero-value order", risk.check_new_position(0, 100, 100, 0, 0)[0], False),
]

failed = 0
for name, actual, expected in tests:
    status = "PASS" if actual == expected else "FAIL"
    print(f"{status}: {name}")
    if actual != expected:
        failed += 1

print(f"RESULT: {len(tests) - failed}/{len(tests)} tests passed")


# Additional tests for invalid inputs.
extra_tests = [
    ("NaN order", risk.check_new_position(float("nan"), 100, 100, 0, 0)[0], False),
    ("infinite order", risk.check_new_position(float("inf"), 100, 100, 0, 0)[0], False),
    ("negative cash", risk.check_new_position(10, -1, 100, 0, 0)[0], False),
    ("negative equity", risk.check_new_position(10, 100, -1, 0, 0)[0], False),
    ("negative position count", risk.check_new_position(10, 100, 100, -1, 0)[0], False),
    ("invalid position count", risk.check_new_position(10, 100, 100, 0.5, 0)[0], False),
]

extra_failed = 0
for name, actual, expected in extra_tests:
    status = "PASS" if actual == expected else "FAIL"
    print(f"{status}: {name}")
    if actual != expected:
        extra_failed += 1

print(f"EXTRA RESULT: {len(extra_tests) - extra_failed}/{len(extra_tests)} tests passed")
raise SystemExit(1 if extra_failed else 0)
