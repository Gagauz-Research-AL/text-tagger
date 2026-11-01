"""Pure text-tagger logic: no I/O, operates on the job dict.

Job format (external JSON):
{"text": "...", "underlines": [{"limit": {"left_pos": 0, "right_pos": 1},
                                "type": "grammatical error",
                                "candidates": ["a", "b"]}]}
Spans are 0-based character offsets, right_pos exclusive (Python slice
semantics), and underlines must not overlap.
"""


def load_job(raw):
    """Normalize an external-format dict into the internal job dict."""
    text = raw["text"]
    underlines = []
    for u in raw.get("underlines", []):
        if "limit" in u:
            left, right = u["limit"]["left_pos"], u["limit"]["right_pos"]
        else:
            left, right = u["left_pos"], u["right_pos"]
        left, right = int(left), int(right)
        if not 0 <= left < right <= len(text):
            raise ValueError(f"invalid span [{left}, {right}) for text of length {len(text)}")
        underlines.append({
            "left_pos": left,
            "right_pos": right,
            "type": u.get("type", ""),
            "candidates": list(u.get("candidates", [])),
        })
    underlines.sort(key=lambda u: u["left_pos"])
    for a, b in zip(underlines, underlines[1:]):
        if b["left_pos"] < a["right_pos"]:
            raise ValueError(f"overlapping underlines at [{a['left_pos']}, {a['right_pos']}) "
                             f"and [{b['left_pos']}, {b['right_pos']})")
    return {"text": text, "underlines": underlines}


def render(job):
    """Split the text into display pieces.

    Returns a list of (chunk, underline_index) where underline_index is None
    for plain text and the 0-based underline position for tagged spans.
    """
    pieces = []
    pos = 0
    for i, u in enumerate(job["underlines"]):
        l, r = u["left_pos"], u["right_pos"]
        if l > pos:
            pieces.append((job["text"][pos:l], None))
        pieces.append((job["text"][l:r], i))
        pos = r
    pieces.append((job["text"][pos:], None))
    return pieces


def replace_segment(job, idx, new_text):
    """Replace the span covered by underline idx with new_text.

    Used for cycling a candidate in AND for operator free-typing. Later
    underlines are shifted by the length delta; the underline itself is
    removed (the tag is resolved for that segment).
    """
    u = job["underlines"][idx]
    l, r = u["left_pos"], u["right_pos"]
    delta = len(new_text) - (r - l)
    job["text"] = job["text"][:l] + new_text + job["text"][r:]
    remaining = []
    for j, other in enumerate(job["underlines"]):
        if j == idx:
            continue
        if other["left_pos"] >= r:
            other["left_pos"] += delta
            other["right_pos"] += delta
        remaining.append(other)
    job["underlines"] = remaining
    return new_text


def apply_replacement(job, idx, candidate):
    """Apply a specific candidate of the selected underline. Alias of
    replace_segment kept for readability in the future web layer."""
    return replace_segment(job, idx, candidate)


def drop(job, idx):
    """False positive: remove the underline, keep the original text."""
    job["underlines"].pop(idx)


def approve(job):
    """Approve the session: the result is the final text."""
    return job["text"]
