from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import polars as pl

from polars_trading._utils import validate_columns

if TYPE_CHECKING:
    from polars_trading.typing import FrameType


def daily_vol(
    df: FrameType,
    timestamp_col: str,
    price_col: str,
    symbol_col: str | None = None,
    span: int = 100,
) -> FrameType:
    """This function calculates the daily volatility of a price series.

    It uses an the daily volatiity by looking back at the return from the oldest price
    in the last 24 hour period to the current price. It then calculates the exponential
    weighted standard deviation of the returns.

    This currently fails to account for weekend returns when there is no trading.

    Marco Lopez de Prado, Advances in Financial Machine Learning, pg. 44

    Args:
    ----
        df (DataFrame): The DataFrame containing the price series.
        timestamp_col (str): The column name containing the timestamps.
        price_col (str): The column name containing the prices.
        symbol_col (str | None): The column name containing the symbols. If None, it is
            assumed that the prices are for a single symbol. Defaults to None.
        span (int): The span of the exponential weighted standard deviation. Defaults to
            100.

    Returns:
        FrameType: The DataFrame with the daily volatility.
    """
    on_clause = [timestamp_col] if symbol_col is None else [timestamp_col, symbol_col]
    df = df.sort(timestamp_col)
    lagged_prices = df.select(
        *on_clause,
        (pl.col(timestamp_col) - timedelta(hours=24)).alias("lookback"),
    ).join_asof(df, left_on="lookback", right_on=timestamp_col, by=symbol_col)
    returns = df.join(
        lagged_prices.select(*on_clause, pl.col(price_col).alias("lookback_price")),
        on=on_clause,
    ).with_columns(pl.col(price_col).truediv("lookback_price").sub(1).alias("return"))
    vol_expr = (
        pl.col("return")
        .ewm_std(span=span)
        .over(symbol_col)
        .alias("daily_return_volatility")
    )
    return_cols = (
        [
            timestamp_col,
            symbol_col,
            vol_expr,
        ]
        if symbol_col
        else [
            timestamp_col,
            vol_expr,
        ]
    )

    return returns.select(*return_cols)


def get_vertical_barrier_by_timedelta(
    df: FrameType,
    timestamp_col: str,
    offset: str | timedelta,
    symbol_col: str | None = None,
) -> FrameType:
    """Create a vertical barrier column.

    The vertical barrier column will be the first timestamp observation after the
    offset of the timestamp column. For example, if you have timestamps at:
        2012-01-01
        2012-01-02
        2012-01-04
    And you offset by 1d, your vertical barriers will be:
        2012-01-04  # This is the first timestamp after 2012-01-01 + 1 day
        2012-01-04
        None

    Args:
    ----
        df (DataFrame): The DataFrame containing the price series.
        timestamp_col (str): The column name containing the timestamps.
        offset (str | timedelta): A string denoting the offset or a timedelta object.
            If a string is passed, it should follow common polars formatting.
        symbol_col (str | None): The column name containing the symbols. If None, it is
            assumed that the prices are for a single symbol. Defaults to None.
        span (int): The span of the exponential weighted standard deviation. Defaults to
            100.

    Returns:
        FrameType: The DataFrame with the vertical barrier.
    """
    if isinstance(offset, str):
        offset_expr = pl.col(timestamp_col).dt.offset_by(offset)
    elif isinstance(offset, timedelta):
        offset_expr = pl.col(timestamp_col) + offset

    if symbol_col is None:
        offsets = df.select(timestamp_col, offset_expr.alias("offset"))
    else:
        offsets = df.select(symbol_col, timestamp_col, offset_expr.alias("offset"))

    if symbol_col is None:
        return offsets.join_asof(
            df.select(pl.col(timestamp_col).alias("vertical_barrier")),
            left_on="offset",
            right_on="vertical_barrier",
            strategy="forward",
        ).select(timestamp_col, "vertical_barrier")
    return offsets.join_asof(
        df.select(symbol_col, pl.col(timestamp_col).alias("vertical_barrier")),
        left_on="offset",
        right_on="vertical_barrier",
        strategy="forward",
        by=symbol_col,
    ).select(symbol_col, timestamp_col, "vertical_barrier")


@validate_columns("timestamp_col", "price_col", "target_col")
def apply_profit_taking_stop_loss(
    df: FrameType,
    timestamp_col: str,
    price_col: str,  # noqa: ARG001
    target_col: str,
    vertical_barrier_col: str | None,
    profit_take: float | None = None,
    stop_loss: float | None = None,
    symbol_col: str | None = None,
) -> FrameType:
    out = df.sort(timestamp_col).with_columns(
        pl.col(target_col).mul(pl.lit(profit_take)).alias("__profit_take"),
        pl.col(target_col).mul(-pl.lit(stop_loss)).alias("__stop_loss"),
    )

    if vertical_barrier_col is None:
        vertical_barrier_col = "__vertical_barier"
        out = out.with_columns(pl.lit(None).alias(vertical_barrier_col))

    out = out.with_columns(
        pl.col(vertical_barrier_col).fill_null(pl.max(timestamp_col).over(symbol_col))
    )

    # TODO: Polars plugin here


def get_triple_barrier_label() -> FrameType:
    """Calculate the triple barrier label.

    This function will take in the required parameters and return a DataFrame with the
    following columns:
        timestamp: The timestamp of the start of the data.
        touch_timestamp: The timestamp of the touch of the first barrier.
        return: The return between the timestamp and the touch timestamp.
        label: The label of the return. This can be done in two ways:
            - {1, 0, -1}: Which will indicate which barrier was first touched.
            - {1, -1}: Which will indicate which barrier was first touched or the sign
                of the return if the vertical barrier was touched first.
    """
