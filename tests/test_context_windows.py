from qualframe.evidence_review import _context_offsets


def test_multi_sentence_span_gets_neighboring_context():
    text = "Before. First coded. Second coded. After."
    start, end = text.index("First"), text.index(" After")
    left, right = _context_offsets(text, start, end, 1, 1)
    assert text[left:right] == text
    assert _context_offsets(text, start, end, 0, 0) == (start, end)


def test_character_and_paragraph_context_preserve_exact_span():
    text = "Before\nCoding here\nAfter"
    start, end = text.index("Coding"), text.index("\nAfter")
    assert _context_offsets(text, start, end, 1, 1, "paragraphs") == (0, len(text))
    assert _context_offsets(text, start, end, 2, 3, "characters") == (start - 2, end + 3)
    assert _context_offsets(text, start, end, 0, 1, "paragraphs")[0] == start
