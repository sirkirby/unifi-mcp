"""Scalars for values outside GraphQL's signed 32-bit Int range."""

from typing import NewType

import strawberry


def _parse_big_int(value: object) -> int:
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise ValueError("BigInt must be a 64-bit integer")
    return value


BigInt = strawberry.scalar(
    NewType("BigInt", int),
    name="BigInt",
    parse_value=_parse_big_int,
    description="A signed integer that can exceed GraphQL Int's 32-bit range.",
)
