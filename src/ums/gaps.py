"""Semantic gap detector — the ONLY place an LLM request may originate.

Lists what deterministic summarization could NOT cover. Emits work-order
records; NEVER calls any model (Phase 3+ concern, elsewhere). Defaults
to deterministic: a gap exists only when the deterministic inputs
(docstrings, parse) are absent, never because a summary "could be nicer".

Work order: {"path", "content_hash", "reason"} — sorted, explicit output.
"""


def detect(extraction):
    """Work orders for one repo's extraction output."""
    orders = []
    for path, entry in sorted(extraction["files"].items()):
        reasons = []
        cls = entry["classification"]
        if entry["unparsed"] is not None:
            reasons.append("unparsed")
        elif cls["language"] == "python":
            if not entry["module_doc"]:
                reasons.append("no_module_docstring")
            undocumented = sum(1 for s in entry["symbols"] or ()
                               if not s["doc"])
            if undocumented:
                reasons.append("undocumented_symbols:%d" % undocumented)
        elif cls["language"] == "unknown":
            reasons.append("no_extractor")
        orders.extend({"path": path, "content_hash": entry["content_hash"],
                       "reason": reason} for reason in reasons)
    return orders


if __name__ == "__main__":
    extraction = {"files": {
        "good.py": {"classification": {"language": "python", "role": "source"},
                    "content_hash": "h1", "module_doc": "Doc.",
                    "symbols": [{"doc": "d"}], "unparsed": None},
        "bad.py": {"classification": {"language": "python", "role": "source"},
                   "content_hash": "h2", "module_doc": None,
                   "symbols": [{"doc": None}, {"doc": "d"}, {"doc": None}],
                   "unparsed": None},
        "broken.py": {"classification": {"language": "python", "role": "source"},
                      "content_hash": "h3", "module_doc": None,
                      "symbols": None, "unparsed": "SyntaxError:x"},
        "data.bin": {"classification": {"language": "unknown", "role": "source"},
                     "content_hash": "h4", "module_doc": None,
                     "symbols": None, "unparsed": None},
        "README.md": {"classification": {"language": "markdown", "role": "doc"},
                      "content_hash": "h5", "module_doc": None,
                      "symbols": None, "unparsed": None},
    }}
    orders = detect(extraction)
    assert [(o["path"], o["reason"]) for o in orders] == [
        ("bad.py", "no_module_docstring"),
        ("bad.py", "undocumented_symbols:2"),
        ("broken.py", "unparsed"),
        ("data.bin", "no_extractor"),
    ]
    assert all(o["content_hash"] for o in orders)
    assert detect(extraction) == orders  # deterministic
    assert detect({"files": {}}) == []
    print("gaps selftest ok")
