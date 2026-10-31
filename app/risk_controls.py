from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RiskLimits:
    initial_capital: float = 100.00
    max_position_pct: float = 25.0
    max_daily_loss: float = 5.00
    max_open_positions: int = 3


class RiskControls:
    def __init__(self, limits: RiskLimits):
        values = (
            limits.initial_capital,
            limits.max_position_pct,
            limits.max_daily_loss,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Risk limits must be finite numbers.")
        if limits.initial_capital <= 0:
            raise ValueError("Initial capital must be positive.")
        if not 0 < limits.max_position_pct <= 100:
            raise ValueError("Maximum position percentage must be between 0 and 100.")
        if limits.max_daily_loss <= 0:
            raise ValueError("Maximum daily loss must be positive.")
        if limits.max_open_positions < 1:
            raise ValueError("Maximum open positions must be at least 1.")

        self.limits = limits

    def check_new_position(
        self,
        order_value: float,
        available_cash: float,
        equity: float,
        open_positions: int,
        daily_realized_pnl: float,
    ) -> tuple[bool, str]:
        numeric_values = (order_value, available_cash, equity, daily_realized_pnl)

        if not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            for v in numeric_values
        ):
            return False, "Invalid or non-finite numeric input."

        if not isinstance(open_positions, int) or isinstance(open_positions, bool):
            return False, "Invalid open-position count."

        if order_value <= 0:
            return False, "Order value must be positive."

        if available_cash < 0 or equity <= 0:
            return False, "Invalid cash or equity value."

        if open_positions < 0:
            return False, "Invalid open-position count."

        if daily_realized_pnl <= -self.limits.max_daily_loss:
            return False, "Daily realized-loss limit reached."

        if open_positions >= self.limits.max_open_positions:
            return False, "Maximum open positions reached."

        max_position_value = equity * self.limits.max_position_pct / 100

        if order_value > max_position_value:
            return False, "Order exceeds maximum position size."

        if order_value > available_cash:
            return False, "Insufficient available cash."

        return True, "Order passes preliminary risk checks."
