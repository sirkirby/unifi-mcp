"""Scalars for values outside GraphQL's signed 32-bit Int range."""

from typing import NewType

import strawberry

BigInt = strawberry.scalar(
    NewType("BigInt", int),
    name="BigInt",
    description="A signed integer that can exceed GraphQL Int's 32-bit range.",
)
