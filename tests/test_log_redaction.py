"""Tests for the log redaction filter's recursive argument handling.

``test_security.py`` covers the core ``redact`` regex and a basic filter pass.
This module locks in the recursive ``record.args`` rewriting (tuples, lists,
dicts, and non-string passthrough) that keeps uvicorn's ``AccessFormatter``
happy while still scrubbing the ``?auth=`` password from every shape of arg.
"""

import logging

from qrdrop.core.log_redaction import RedactAuthFilter, _redact_arg, redact


class TestRedactArg:
    def test_string_is_redacted(self) -> None:
        assert _redact_arg("GET /?auth=secret") == "GET /?auth=<redacted>"

    def test_tuple_preserves_shape_and_redacts(self) -> None:
        out = _redact_arg(("a", "/?auth=secret", 200))
        assert out == ("a", "/?auth=<redacted>", 200)
        assert isinstance(out, tuple)

    def test_list_is_redacted_elementwise(self) -> None:
        out = _redact_arg(["/?auth=one", "/?auth=two"])
        assert out == ["/?auth=<redacted>", "/?auth=<redacted>"]
        assert isinstance(out, list)

    def test_dict_values_are_redacted(self) -> None:
        out = _redact_arg({"request_line": "GET /?auth=hunter2", "status": 200})
        assert out == {"request_line": "GET /?auth=<redacted>", "status": 200}

    def test_nested_structures_are_redacted(self) -> None:
        out = _redact_arg({"items": [("GET /?auth=zzz",)]})
        assert out == {"items": [("GET /?auth=<redacted>",)]}

    def test_non_string_scalars_pass_through_unchanged(self) -> None:
        assert _redact_arg(200) == 200
        assert _redact_arg(None) is None
        assert _redact_arg(3.14) == 3.14


class TestFilter:
    def test_dict_style_args_are_redacted(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="%(request_line)s",
            # A sole mapping arg must be wrapped in a tuple; logging unwraps it.
            args=({"request_line": "GET /?auth=topsecret HTTP/1.1"},),
            exc_info=None,
        )
        assert RedactAuthFilter().filter(record) is True
        assert "topsecret" not in record.getMessage()
        assert "auth=<redacted>" in record.getMessage()

    def test_record_without_args_is_left_alone(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="server started",
            args=None,
            exc_info=None,
        )
        assert RedactAuthFilter().filter(record) is True
        assert record.getMessage() == "server started"

    def test_non_string_msg_is_not_mangled(self) -> None:
        # Logging allows a non-string msg; the filter must not coerce it.
        sentinel = {"event": "startup"}
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=sentinel,
            args=None,
            exc_info=None,
        )
        assert RedactAuthFilter().filter(record) is True
        assert record.msg is sentinel

    def test_filter_always_returns_true(self) -> None:
        # The filter redacts but never drops records.
        record = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="nothing sensitive",
            args=None,
            exc_info=None,
        )
        assert RedactAuthFilter().filter(record) is True


class TestRedactEdgeCases:
    def test_redacts_value_terminated_by_ampersand(self) -> None:
        assert redact("/?auth=abc&x=1") == "/?auth=<redacted>&x=1"

    def test_case_insensitive_key(self) -> None:
        assert redact("/?AUTH=abc") == "/?AUTH=<redacted>"

    def test_no_match_returns_input_unchanged(self) -> None:
        assert redact("/browse/dir?sort=name") == "/browse/dir?sort=name"
