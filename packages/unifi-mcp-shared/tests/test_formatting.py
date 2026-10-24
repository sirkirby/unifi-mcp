"""Tests for the shared formatting module."""

from unifi_core.formatting import error_response, success_response


def test_success_response():
    result = success_response(data={"clients": 42})
    assert result == {"success": True, "data": {"clients": 42}}


def test_success_response_no_data():
    result = success_response()
    assert result == {"success": True}


def test_success_response_with_extra_kwargs():
    result = success_response(data="ok", message="done")
    assert result == {"success": True, "data": "ok", "message": "done"}


def test_error_response():
    result = error_response("Something went wrong")
    assert result == {"success": False, "error": "Something went wrong"}


def test_error_response_with_extra_kwargs():
    result = error_response("fail", code=404)
    assert result == {"success": False, "error": "fail", "code": 404}
