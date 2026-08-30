from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.parser import BytesParser


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    content_type: str
    content: bytes


def parse_multipart_form(
    content_type: str,
    body: bytes,
) -> tuple[dict[str, list[str]], dict[str, UploadedFile]]:
    """Parse a bounded multipart form using the standard-library MIME parser."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Expected a multipart form upload.")
    header = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("ascii", errors="strict")
    message = BytesParser(policy=policy.default).parsebytes(header + body)
    if not message.is_multipart():
        raise ValueError("Upload did not contain valid multipart data.")
    fields: dict[str, list[str]] = {}
    files: dict[str, UploadedFile] = {}
    part_count = 0
    for part in message.iter_parts():
        part_count += 1
        if part_count > 20:
            raise ValueError("Upload contains too many form parts.")
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            if name in files:
                raise ValueError(f"Upload contains duplicate file field '{name}'.")
            files[name] = UploadedFile(
                filename=filename,
                content_type=part.get_content_type(),
                content=payload,
            )
        else:
            charset = part.get_content_charset() or "utf-8"
            try:
                value = payload.decode(charset)
            except (LookupError, UnicodeDecodeError) as exc:
                raise ValueError(f"Form field '{name}' is not valid text.") from exc
            fields.setdefault(name, []).append(value)
    return fields, files
