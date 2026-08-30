from __future__ import annotations

import pytest

from qualframe.web_forms import parse_multipart_form


def _multipart_body(boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="actor"\r\n\r\n'
        "researcher\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="rationale"\r\n\r\n'
        "Approved synthetic test import.\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="upload"; filename="SYN-01.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "Synthetic transcript text.\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")


def test_parse_multipart_form_preserves_fields_and_file_bytes() -> None:
    boundary = "qualframe-boundary"
    fields, files = parse_multipart_form(
        f"multipart/form-data; boundary={boundary}",
        _multipart_body(boundary),
    )

    assert fields["actor"] == ["researcher"]
    assert fields["rationale"] == ["Approved synthetic test import."]
    assert files["upload"].filename == "SYN-01.txt"
    assert files["upload"].content == b"Synthetic transcript text."


def test_parse_multipart_form_rejects_non_multipart_content() -> None:
    with pytest.raises(ValueError, match="multipart"):
        parse_multipart_form("application/x-www-form-urlencoded", b"actor=x")
