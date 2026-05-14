"""Scope check tests."""

import pytest
from unifi_api.auth.scopes import Scope, parse_scopes, scope_allows


def test_parse_scopes() -> None:
    assert parse_scopes("read") == frozenset({Scope.READ})
    assert parse_scopes("read,write") == frozenset({Scope.READ, Scope.WRITE})
    assert parse_scopes("admin") == frozenset({Scope.ADMIN})


def test_admin_implies_all() -> None:
    admin = frozenset({Scope.ADMIN})
    assert scope_allows(admin, Scope.READ) is True
    assert scope_allows(admin, Scope.WRITE) is True
    assert scope_allows(admin, Scope.ADMIN) is True


def test_read_does_not_imply_write() -> None:
    read_only = frozenset({Scope.READ})
    assert scope_allows(read_only, Scope.READ) is True
    assert scope_allows(read_only, Scope.WRITE) is False
    assert scope_allows(read_only, Scope.ADMIN) is False


def test_invalid_scope_string() -> None:
    with pytest.raises(ValueError):
        parse_scopes("delete")
