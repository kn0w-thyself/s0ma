"""Parser — Stages 1-2: Parsing and AST construction for the s0ma DSL.

Public API:
    parse_s0ma(source, filename) -> S0maModule
    S0maParser — class-based parser interface
    extract_body(raw_body, filename, body_start_line) -> BodyInfo
    validate_body(...) -> list[S0maError]
"""

from s0ma_dsl.parser.body_extractor import (
    BodyInfo,
    BodyType,
    extract_body,
    validate_body,
    validate_example_body,
)
from s0ma_dsl.parser.s0ma_parser import S0maParser, parse_s0ma

__all__ = [
    "BodyInfo",
    "BodyType",
    "S0maParser",
    "extract_body",
    "parse_s0ma",
    "validate_body",
    "validate_example_body",
]
