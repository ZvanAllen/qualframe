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
    *,
    allow_multiple: bool = False,
) -> tuple[dict[str, list[str]], dict[str, UploadedFile | list[UploadedFile]]]:
    """Parse a bounded multipart form using the standard-library MIME parser.

    With ``allow_multiple`` a file field may repeat (a multi-file picker); its value is
    then a list of uploads. Otherwise duplicate file fields are rejected.
    """
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Expected a multipart form upload.")
    header = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("ascii", errors="strict")
    message = BytesParser(policy=policy.default).parsebytes(header + body)
    if not message.is_multipart():
        raise ValueError("Upload did not contain valid multipart data.")
    fields: dict[str, list[str]] = {}
    files: dict[str, UploadedFile | list[UploadedFile]] = {}
    part_count = 0
    for part in message.iter_parts():
        part_count += 1
        if part_count > 210:
            raise ValueError("Upload contains too many form parts.")
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            if not filename and not payload:
                continue  # an empty file input
            upload = UploadedFile(filename=filename, content_type=part.get_content_type(), content=payload)
            if allow_multiple:
                existing = files.setdefault(name, [])
                assert isinstance(existing, list)
                existing.append(upload)
            else:
                if name in files:
                    raise ValueError(f"Upload contains duplicate file field '{name}'.")
                files[name] = upload
        else:
            charset = part.get_content_charset() or "utf-8"
            try:
                value = payload.decode(charset)
            except (LookupError, UnicodeDecodeError) as exc:
                raise ValueError(f"Form field '{name}' is not valid text.") from exc
            fields.setdefault(name, []).append(value)
    return fields, files
