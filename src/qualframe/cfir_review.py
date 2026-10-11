"""Derived CFIR review records; never change the source or model artifact."""
from __future__ import annotations

import re
from pathlib import Path

from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import CodeAssignment, EvidenceReviewRecord, EvidenceSpan


# Characters models often substitute when copying a quotation. Each maps to one character,
# so offsets in the normalized text still point at the original source characters.
_TYPOGRAPHY = {
    '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u2032': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': '"', '\u2033': '"',
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-', '\u2212': '-',
}


def normalized_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Collapse whitespace, quote and hyphen typography while retaining source offsets."""
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        value = ' ' if char.isspace() else _TYPOGRAPHY.get(char, char)
        if value == ' ' and chars and chars[-1] == ' ':
            offsets[-1] = (offsets[-1][0], index + 1)
        else:
            chars.append(value)
            offsets.append((index, index + 1))
    return ''.join(chars), offsets


def locate_quote(source: str, quote: str) -> tuple[int, int, str]:
    quote = quote.strip()
    if len(quote) > 1 and (quote[0], quote[-1]) in [('"', '"'), ('“', '”')]:
        quote = quote[1:-1]
    if not quote:
        return -1, -1, 'unresolved_exact_quote'
    pos = source.find(quote)
    if pos >= 0 and source.find(quote, pos + 1) < 0:
        return pos, pos + len(quote), 'unique_exact_quote'
    normalized, offsets = normalized_with_offsets(source)
    needle = normalized_with_offsets(quote)[0]
    pos = normalized.find(needle)
    if pos >= 0 and normalized.find(needle, pos + 1) < 0:
        return offsets[pos][0], offsets[pos + len(needle) - 1][1], 'normalized_quote_candidate'
    return -1, -1, 'unresolved_exact_quote'


def reference_codes(path: Path) -> list[dict[str, str]]:
    """Read the reference workbook's domain sections without rewriting it."""
    import openpyxl
    if not path.exists():
        return []
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    codes: list[dict[str, str]] = []
    domain = ''
    parent = ''
    try:
        for sheet in workbook:
            for row in sheet.iter_rows(values_only=True):
                label = str(row[0] or '').strip()
                definition = str(row[1] or '').strip() if len(row) > 1 else ''
                if not definition:
                    heading = label.splitlines()[0] if label else ''
                    if 'OUTCOMES ADDENDUM' in heading.upper():
                        domain, parent = 'OUTCOMES ADDENDUM', ''
                    elif re.match(r'^[IVX]+\.', heading):
                        domain = re.sub(r'^[IVX]+\.\s*', '', heading).split(':')[0].strip()
                        parent = ''
                    continue
                if definition.lower() == 'construct definition' or label.lower() == 'name' or not label:
                    continue
                if re.match(r'^[IVX]+\.\s+[A-Z ]+$', label):
                    parent = ''
                    continue
                is_child = bool(re.match(r'^\d+\.', label))
                if not is_child:
                    parent = label
                parent_label = parent if is_child else ''
                identity = sha256_for_text(domain + ':' + parent_label + ':' + label)[:20]
                display = f'{parent_label} / {label}' if parent_label else label
                codes.append(dict(id='cfir-' + identity, label=display, raw_label=label,
                    parent_label=parent_label, definition=definition, domain=domain))
    finally:
        workbook.close()
    return codes


def cfir_records(*, artifact, artifact_rel: str, artifact_path: Path, source_path: Path,
                 repo_root: Path, manifest, codes: list[dict[str, str]], codebook_hash: str,
                 code_label_policy: str = "legacy_v1"):
    if code_label_policy not in {"legacy_v1", "qualified_delimiters_v2"}:
        raise ValueError("Unknown CFIR code-label normalization policy.")
    source = transcript_to_text(source_path)
    source_hash = sha256_for_file(source_path)
    records = []
    for domain, rows in artifact.parsed_output.items():
        current_parent = ''
        for number, row in enumerate(rows, 1):
            if not {'CFIR Construct', 'Quote'} <= row.keys():
                continue
            label = str(row['CFIR Construct']).strip()
            def name(value):
                return re.sub(r'^(?:[A-Z]\d*|\d+)\.\s*', '', value).strip().casefold()
            in_domain = [c for c in codes if domain.lower().replace(' addendum', '') in c['domain'].lower()]
            qualified = re.split(r"\s+[–—-]\s+", label) if code_label_policy == "qualified_delimiters_v2" else []
            if len(qualified) == 2:
                # Delimiter-only sensitivity: both literal parent and child must
                # match. This does not map synonyms or broad "(general)" labels.
                candidates = [c for c in in_domain if name(c['raw_label']) == name(qualified[1])
                              and name(c['parent_label']) == name(qualified[0])]
            else:
                candidates = [c for c in in_domain if name(c['raw_label']) == name(label.split(':')[-1])]
                if ':' in label:
                    parent_name = name(label.split(':')[0])
                    candidates = [c for c in candidates if name(c['parent_label']) == parent_name]
            if len(candidates) > 1 and current_parent:
                candidates = [c for c in candidates if c['parent_label'] == current_parent]
            code = candidates[0] if len(candidates) == 1 else None
            if code and not code['parent_label']:
                current_parent = code['raw_label']
            quote = str(row['Quote'])
            absent = quote.strip().strip('"“”').lower() == 'no relevant quote found'
            start, end, method = (-1, -1, 'no_evidence') if absent else locate_quote(source, quote)
            identity = sha256_for_text(f'{artifact_rel}:{domain}:{number}')[:20]
            issues = []
            if code is None:
                issues.append('Construct could not be identified uniquely in the reference codebook.')
            if method == 'normalized_quote_candidate':
                issues.append('Formatting differs from the model quotation. Confirm the highlighted source passage with Save changes.')
            elif method == 'unresolved_exact_quote':
                issues.append('Select the evidence in the transcript; the quotation is missing or ambiguous.')
            span = EvidenceSpan(id='span-' + identity, meaning_unit_id='meaning-' + identity,
                source_id='source-' + source_hash[:24], source_sha256=sha256_for_text(source),
                start_offset=start, end_offset=end, exact_text=source[start:end],
                context_start_offset=start, context_end_offset=end, creation_method='automatic') if start >= 0 else None
            assignment = CodeAssignment(id='assignment-' + identity, meaning_unit_id='meaning-' + identity,
                evidence_span_id=span.id, codebook_id='cfir-reference', codebook_version=codebook_hash,
                code_id=code['id'], origin='model', rationale=row.get('Explanation'), run_id=manifest.run_id) if span and code else None
            records.append(EvidenceReviewRecord(record_id='evidence-' + identity, run_id=manifest.run_id,
                stage_id=artifact.stage_id, artifact_path=artifact_rel, artifact_sha256=sha256_for_file(artifact_path),
                sheet_name=domain, row_index=number, source_id='source-' + source_hash[:24],
                source_path=str(source_path.relative_to(repo_root)), source_sha256=source_hash,
                meaning_unit_id='meaning-' + identity, proposed_start_offset=-1, proposed_end_offset=-1,
                proposed_exact_text=quote, anchoring_method=method, evidence_span=span, assignment=assignment,
                code_label=code['label'] if code else label, code_definition=code['definition'] if code else None,
                proposed_code_id=code['id'] if code else None, proposed_rationale=row.get('Explanation', ''),
                record_kind='absence' if absent else 'evidence', model=artifact.model, provider=artifact.provider,
                prompt_sha256=artifact.prompt_sha256, configuration_fingerprint=manifest.configuration_fingerprint,
                validation_issues=issues))
    return records
