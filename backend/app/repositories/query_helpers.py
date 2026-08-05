"""Declarative list filters, ordering, and pagination helpers for repositories."""
from enum import StrEnum
from typing import Any


class FilterOp(StrEnum):
    """Supported filter operations for apply_filters."""
    EQ = "eq"                  # column == value  (None is skipped)
    LIKE = "like"              # column.ilike(f"%{value}%")  (falsy is skipped)
    RANGE = "range"            # {key}_min / {key}_max  ->  >= / <=
    DATE_RANGE = "date_range"  # {key}_from / {key}_to  ->  >= / <=


# Type alias for a single filter spec entry: (key, column_expr, op)
FilterSpec = tuple[str, Any, FilterOp]


def apply_filters(stmt: Any, filters: dict, specs: list[FilterSpec]) -> Any:
    """Apply declarative filter specs to *stmt*.

    Args:
        stmt: A SQLModel / SQLAlchemy select statement.
        filters: A dict of filter key → value (None values are typically
                 already stripped by the caller, but each op handles them
                 defensively).
        specs: List of (key, column, FilterOp) tuples describing each
               standard filter to apply.

    Returns:
        The statement with all matching where-clauses appended.
    """
    for key, column, op in specs:
        if op == FilterOp.EQ:
            val = filters.get(key)
            if val is not None:
                stmt = stmt.where(column == val)

        elif op == FilterOp.LIKE:
            val = filters.get(key)
            if val:
                stmt = stmt.where(column.ilike(f"%{val}%"))

        elif op == FilterOp.RANGE:
            lo = filters.get(f"{key}_min")
            hi = filters.get(f"{key}_max")
            if lo is not None:
                stmt = stmt.where(column >= lo)
            if hi is not None:
                stmt = stmt.where(column <= hi)

        elif op == FilterOp.DATE_RANGE:
            lo = filters.get(f"{key}_from")
            hi = filters.get(f"{key}_to")
            if lo is not None:
                stmt = stmt.where(column >= lo)
            if hi is not None:
                stmt = stmt.where(column <= hi)

    return stmt


def apply_ordering(
    stmt: Any,
    order_by: str,
    order_dir: str,
    sort_fields: dict[str, Any],
    default_col: Any,
    tie_break_col: Any = None,
) -> Any:
    """Append ORDER BY to *stmt* using an explicit field mapping.

    Args:
        stmt: A SQLModel / SQLAlchemy select statement.
        order_by: The requested sort key (e.g. ``"name"``).
        order_dir: ``"asc"`` or ``"desc"`` (case-insensitive).
        sort_fields: Mapping from sort-key string to ORM column expression.
                     Unknown keys fall back to *default_col*.
        default_col: Column expression used when *order_by* is not in
                     *sort_fields*.
        tie_break_col: Optional secondary column for stable ordering.
                       Must already be accessible from the statement (i.e.
                       part of a join that is always present).

    Returns:
        The statement with ORDER BY appended.
    """
    col = sort_fields.get(order_by, default_col)
    desc = order_dir.lower() == "desc"
    stmt = stmt.order_by(col.desc() if desc else col.asc())
    if tie_break_col is not None:
        stmt = stmt.order_by(tie_break_col.desc() if desc else tie_break_col.asc())
    return stmt


def apply_pagination(stmt: Any, page: int, page_size: int) -> Any:
    """Append OFFSET / LIMIT to *stmt* for keyset-style pagination.

    Args:
        stmt: A SQLModel / SQLAlchemy select statement.
        page: 1-based page number.
        page_size: Number of rows per page.

    Returns:
        The statement with OFFSET and LIMIT appended.
    """
    return stmt.offset((page - 1) * page_size).limit(page_size)
