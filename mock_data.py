"""Mock data generator: builds a fake job in the external JSON format."""

_SAMPLE = "the cat sitted on the mat while the dog barked at the mailman"


def generate_mock():
    """Return a job dict with fabricated underlines.

    Mixes spans with replacement candidates and one highlight-only span
    (no candidates) so both operator flows are exercised.
    """
    words = _SAMPLE.split()
    plan = {
        2: ("sitted", ["sat", "was sitting"], "grammatical error"),
        4: ("the", [], "possible false positive"),
        5: ("mat", ["matte", "doormat"], "weird spelling"),
        9: ("barked", ["bakked", "borked"], "weird spelling"),
        12: ("mailman", ["mail man", "postman"], "phrasing"),
    }
    parts = []
    underlines = []
    pos = 0
    for i, word in enumerate(words):
        if i > 0:
            parts.append(" ")
            pos += 1
        start = pos
        typed, candidates, utype = plan.get(i, (word, None, None))
        parts.append(typed)
        pos += len(typed)
        if candidates is not None:
            u = {
                "limit": {"left_pos": start, "right_pos": start + len(typed)},
                "type": utype,
            }
            if candidates:
                u["candidates"] = candidates
            underlines.append(u)
    return {"text": "".join(parts), "underlines": underlines}
