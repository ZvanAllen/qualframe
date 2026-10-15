"""Derived CFIR review records; never change the source or model artifact."""
from __future__ import annotations

import re
import unicodedata
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


def normalized_words_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Lower-case words, remove punctuation and retain original character offsets.

    Apostrophes (including typographic variants) remain significant. Other punctuation
    and symbols are dropped, whitespace is collapsed, and combining marks are kept.
    Lower-casing can expand a character, so each resulting character retains its full
    source range. No stemming, spelling correction or word substitutions are attempted.
    """
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    for index, original in enumerate(text):
        char = _TYPOGRAPHY.get(original, original)
        if char.isspace():
            if chars and chars[-1] == ' ':
                offsets[-1] = (offsets[-1][0], index + 1)
            elif chars:
                chars.append(' ')
                offsets.append((index, index + 1))
        elif char == "'" or char.isalnum() or unicodedata.category(char).startswith('M'):
            lowered = char.lower()
            chars.extend(lowered)
            offsets.extend([(index, index + 1)] * len(lowered))
    if chars and chars[-1] == ' ':
        chars.pop()
        offsets.pop()
    return ''.join(chars), offsets


def locate_words_quote(source: str, quote: str) -> tuple[int, int, str]:
    """Suggest one whole-word match for confirmation, never choose among repeats."""
    normalized, offsets = normalized_words_with_offsets(source)
    needle = normalized_words_with_offsets(quote)[0]
    if not needle or not any(char.isalnum() for char in needle):
        return -1, -1, 'unresolved_exact_quote'
    position = normalized.find(needle)
    match = None
    while position >= 0:
        end = position + len(needle)
        if (position == 0 or normalized[position - 1] == ' ') and (end == len(normalized) or normalized[end] == ' '):
            if match is not None:
                return -1, -1, 'unresolved_exact_quote'
            match = offsets[position][0], offsets[end - 1][1]
        position = normalized.find(needle, position + 1)
    if match is not None:
        return *match, 'normalized_words_candidate'
    return -1, -1, 'unresolved_exact_quote'


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
    if pos >= 0:
        return -1, -1, 'unresolved_exact_quote'  # Repeated typography matches remain ambiguous.
    return locate_words_quote(source, quote)


def reference_codes(path: Path) -> list[dict[str, str]]:
    """Read the reference workbook's domain sections without rewriting it."""
    import openpyxl
    if not path.exists():
        return []
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    codes: list[dict[str, str]] = []
    domain = ''
    parent = ''
    section = ''  # Outcomes Addendum groups, such as "ANTECEDENT ASSESSMENTS"
    try:
        for sheet in workbook:
            for row in sheet.iter_rows(values_only=True):
                label = str(row[0] or '').strip()
                definition = str(row[1] or '').strip() if len(row) > 1 else ''
                if not definition:
                    heading = label.splitlines()[0] if label else ''
                    if 'OUTCOMES ADDENDUM' in heading.upper():
                        domain, parent, section = 'OUTCOMES ADDENDUM', '', ''
                    elif re.match(r'^[IVX]+\.', heading):
                        domain = re.sub(r'^[IVX]+\.\s*', '', heading).split(':')[0].strip()
                        parent, section = '', ''
                    continue
                if definition.lower() == 'construct definition' or label.lower() == 'name' or not label:
                    continue
                if re.fullmatch(r'notes?\s*:?', label, re.IGNORECASE):
                    continue  # explanatory notes between constructs (for example in the Inner Setting domain)
                if re.match(r'^[IVX]+\.\s+[A-Z ]+$', label):
                    parent = ''
                    section = re.sub(r'^[IVX]+\.\s*', '', label).strip()
                    continue
                is_child = bool(re.match(r'^\d+\.', label))
                if not is_child:
                    parent = label
                parent_label = parent if is_child else ''
                identity = sha256_for_text(domain + ':' + parent_label + ':' + label)[:20]
                display = f'{parent_label} / {label}' if parent_label else label
                codes.append(dict(id='cfir-' + identity, label=display, raw_label=label,
                    parent_label=parent_label, definition=definition, domain=domain, section=section))
    finally:
        workbook.close()
    return codes


# How a model's "CFIR Construct" label is matched to the reference codebook.
# legacy_v1 and qualified_delimiters_v2 are frozen: historical benchmarks were normalized with them.
# outline_labels_v3 (11 October 2026) reads the forms models write when copying the codebook's
# outline: "H. Innovation Deliverers: 4. Motivation", "F. Engaging – 1. Innovation Deliverers",
# "II.B.1. Actual Implementation Outcomes: Adoption". Outline numbers, case, spacing, dash and
# quote typography and "&"/"and" are ignored; names must otherwise match exactly, and a qualifier
# must name the code's parent construct, its Outcomes Addendum group or its domain.
# outline_labels_v4 (used for review) adds compound outline numbers without a final full stop
# ("A.3 Work Infrastructure", "II.A.3 Sustainability", "I.A Acceptability"), takes the parent
# from such a number when a sub-construct name alone is ambiguous ("E.3 Opportunity" is the
# Opportunity of E. Implementation Leads), and reads a trailing parenthesis as the parent
# ("F2. Innovation Recipients (Engaging)"). v3 is kept unchanged for indexes made with it.
LABEL_POLICIES = ("legacy_v1", "qualified_delimiters_v2", "outline_labels_v3", "outline_labels_v4")
REVIEW_LABEL_POLICY = "outline_labels_v4"
_SEGMENT = r'(?:[IVX]+|[A-Z]\d*|\d+)'
_OUTLINE_NUMBER = re.compile(rf'^\s*(?:{_SEGMENT}\.)+\s*')
_OUTLINE_NUMBER_V4 = re.compile(rf'^\s*(?:{_SEGMENT}\.)*{_SEGMENT}(?:\.|(?=\s))\s*')
_QUALIFIER = re.compile(r'\s*:\s*|\s+[/>-]\s+')


def construct_name(value: str, version: int = 4) -> str:
    """A construct name without its outline number, for comparison."""
    value = normalized_with_offsets(str(value or ''))[0]
    pattern = _OUTLINE_NUMBER_V4 if version >= 4 else _OUTLINE_NUMBER
    value = pattern.sub('', value).replace('&', ' and ')
    return ' '.join(value.casefold().split())


def _parent_letter(part: str) -> str:
    """The parent's outline letter in a compound number: "E.3 Opportunity" or "F2. Engaging" -> "E"/"F"."""
    number = _OUTLINE_NUMBER_V4.match(part)
    if not number:
        return ''
    segments = [s for s in re.split(r'[.\s]+', number.group(0)) if s]
    if len(segments) == 1 and re.fullmatch(r'[A-Z]\d+', segments[0]):
        return segments[0][0]
    if len(segments) >= 2 and re.fullmatch(r'[A-Z]', segments[-2]):
        return segments[-2]
    return ''


def _outline_candidates(label: str, in_domain: list[dict[str, str]], current_parent: str,
                        version: int = 4) -> list[dict[str, str]]:
    parts = [part for part in _QUALIFIER.split(normalized_with_offsets(label.strip())[0]) if part.strip()]
    if not parts:
        return []
    child_part, qualifier_part = parts[-1], parts[-2] if len(parts) > 1 else ''

    def named(part: str) -> list[dict[str, str]]:
        child = construct_name(part, version)
        return [c for c in in_domain if construct_name(c['raw_label'], version) == child]

    candidates = named(child_part)
    if version >= 4 and not candidates and not qualifier_part:
        bracket = re.fullmatch(r'(.*\S)\s*\(([^()]+)\)\s*', child_part)
        if bracket:
            candidates, qualifier_part = named(bracket.group(1)), bracket.group(2)
    if qualifier_part:
        qualifier = construct_name(qualifier_part, version)
        candidates = [c for c in candidates if qualifier in {
            construct_name(c['parent_label'], version), construct_name(c.get('section', ''), version),
            construct_name(re.sub(r'\s+domain$', '', c['domain'], flags=re.IGNORECASE), version)} - {''}]
    elif len(candidates) > 1:
        letter = _parent_letter(child_part) if version >= 4 else ''
        narrowed = [c for c in candidates if letter and re.match(rf'{letter}\.', c['parent_label'])]
        if len(narrowed) == 1:
            return narrowed
        if current_parent:
            candidates = [c for c in candidates if c['parent_label'] == current_parent]
    return candidates


def _frozen_policy_code(label: str, in_domain: list[dict[str, str]], current_parent: str, policy: str):
    """legacy_v1 and qualified_delimiters_v2, unchanged so historical benchmarks reproduce."""
    def name(value):
        return re.sub(r'^(?:[A-Z]\d*|\d+)\.\s*', '', value).strip().casefold()
    qualified = re.split(r"\s+[–—-]\s+", label) if policy == "qualified_delimiters_v2" else []
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
    return code, current_parent


def cfir_records(*, artifact, artifact_rel: str, artifact_path: Path, source_path: Path,
                 repo_root: Path, manifest, codes: list[dict[str, str]], codebook_hash: str,
                 code_label_policy: str = "legacy_v1"):
    if code_label_policy not in LABEL_POLICIES:
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
            in_domain = [c for c in codes if domain.lower().replace(' addendum', '') in c['domain'].lower()]
            if code_label_policy in {"outline_labels_v3", "outline_labels_v4"}:
                candidates = _outline_candidates(label, in_domain, current_parent,
                                                 version=int(code_label_policy[-1]))
                code = candidates[0] if len(candidates) == 1 else None
                if code:
                    current_parent = code['parent_label'] or code['raw_label']
            else:
                code, current_parent = _frozen_policy_code(label, in_domain, current_parent, code_label_policy)
            quote = str(row['Quote'])
            absent = quote.strip().strip('"“”').lower() == 'no relevant quote found'
            start, end, method = (-1, -1, 'no_evidence') if absent else locate_quote(source, quote)
            identity = sha256_for_text(f'{artifact_rel}:{domain}:{number}')[:20]
            issues = []
            if code is None:
                issues.append('Construct could not be identified uniquely in the reference codebook.')
            if method == 'normalized_quote_candidate':
                issues.append('Formatting differs from the model quotation. Confirm the highlighted source passage with Save changes.')
            elif method == 'normalized_words_candidate':
                issues.append('Case or punctuation differs from the model quotation. Confirm the highlighted source passage before accepting.')
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
