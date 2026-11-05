"""Mock data generator: builds a fake job in the external JSON format."""

def _build_job(id, text, plan):
    """Builds a job with calculated spans based on word index.
    plan: { index: (replacement_text, candidates, type) }
    """
    words = text.split()
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
    return {"id": id, "text": "".join(parts), "underlines": underlines}

def generate_mock_jobs():
    """Return a list of mock jobs for the backlog."""
    return [
        _build_job("txt-001", "the cat sitted on the mat while the dog barked at the mailman", {
            2: ("sitted", ["sat", "was sitting"], "grammatical error"),
            4: ("the", [], "possible false positive"),
            5: ("mat", ["matte", "doormat"], "weird spelling"),
            9: ("barked", ["bakked", "borked"], "weird spelling"),
            12: ("mailman", ["mail man", "postman"], "phrasing"),
        }),
        _build_job("txt-002", "their going too the market later, but the whether looks unpredictable", {
            0: ("their", ["they're", "there"], "grammatical error"),
            2: ("too", ["to"], "phrasing"),
            8: ("whether", ["weather"], "weird spelling"),
        })
    ]

def generate_mock():
    """Alias for the first mock job for compatibility."""
    return generate_mock_jobs()[0]
