"""Deterministic summarizer — tiered summaries with hard token ceilings.

Tiers: full / section / reference. Zero LLM: input is the extraction
record (docstrings, signatures) plus raw text for doc files (headings,
README). A token = one whitespace-split word (ponytail: crude but
deterministic; swap for a real tokenizer only if ceilings ever matter
to a model). Summary text NEVER contains the file path, so records are
safely keyed by content hash alone (identical files share a summary).

Doc summaries also carry "tokens": identifier-ish words for the
relationship deriver — hash-pure, filtered against module names later.
"""
import re

FULL_TOKENS = 256
SECTION_TOKENS = 64
REFERENCE_TOKENS = 25  # blueprint: <=25-token reference tier

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_./]+")
MAX_DOC_TOKENS = 200  # ponytail: cap mention candidates per doc


def token_count(text):
    return len(text.split())


def _cap(text, ceiling):
    words = text.split()
    return " ".join(words[:ceiling])


def _first_line(text):
    return text.strip().splitlines()[0] if text and text.strip() else ""


def _python_summary(entry):
    lines = []
    if entry["module_doc"]:
        lines.append(_first_line(entry["module_doc"]))
    symbol_lines = []
    for sym in entry["symbols"] or ():
        piece = sym["kind"] + " " + sym["qualname"] + sym["signature"]
        if sym["doc"]:
            piece += ": " + _first_line(sym["doc"])
        symbol_lines.append(piece)
    full = " | ".join(lines + symbol_lines)
    section = " | ".join(
        [lines[0]] if lines else []
        + [sym["kind"] + " " + sym["qualname"] for sym in entry["symbols"] or ()])
    reference = lines[0] if lines else " ".join(
        s["qualname"] for s in (entry["symbols"] or ())[:6])
    return full, section, reference, []


def _doc_summary(text):
    headings = [line.lstrip("# ").strip() for line in text.splitlines()
                if line.startswith("#")]
    reference = headings[0] if headings else _first_line(text)
    section = " | ".join(headings) if headings else _first_line(text)
    tokens = sorted(set(_IDENTIFIER.findall(text)))[:MAX_DOC_TOKENS]
    return text, section, reference, tokens


def summarize_file(entry, text=None):
    """Tiered summary record for one extraction entry.

    text = decoded file content, required only for doc-language files
    (markdown/text); everything else summarizes from the entry alone.
    """
    cls = entry["classification"]
    if entry["unparsed"] is not None:
        base = ("UNPARSED " + cls["language"] + " file: " + entry["unparsed"],) * 3
        full, section, reference, tokens = base[0], base[1], base[2], []
    elif cls["language"] == "python":
        full, section, reference, tokens = _python_summary(entry)
    elif cls["language"] in ("markdown", "text") and text is not None:
        full, section, reference, tokens = _doc_summary(text)
    else:
        stub = cls["language"] + " " + cls["role"] + " file"
        full = section = reference = stub
        tokens = []
    return {
        "full": _cap(full, FULL_TOKENS),
        "section": _cap(section, SECTION_TOKENS),
        "reference": _cap(reference, REFERENCE_TOKENS),
        "tokens": tokens,
    }


if __name__ == "__main__":
    py_entry = {
        "classification": {"language": "python", "role": "source"},
        "module_doc": "Core module.\n\nLong detail paragraph.",
        "symbols": [
            {"kind": "function", "qualname": "add",
             "signature": "(a: int, b: int) -> int", "doc": "Add two numbers."},
            {"kind": "class", "qualname": "Calc", "signature": "",
             "doc": "Tiny calculator."},
        ],
        "unparsed": None,
    }
    record = summarize_file(py_entry)
    assert record["reference"] == "Core module."
    assert "function add(a: int, b: int) -> int: Add two numbers." in record["full"]
    assert token_count(record["reference"]) <= REFERENCE_TOKENS
    assert token_count(record["section"]) <= SECTION_TOKENS
    assert token_count(record["full"]) <= FULL_TOKENS
    assert summarize_file(py_entry) == record  # deterministic

    doc_entry = {"classification": {"language": "markdown", "role": "doc"},
                 "module_doc": None, "symbols": None, "unparsed": None}
    doc = summarize_file(doc_entry, "# Title\n\nUses pkg.core and app.py\n## Sub\n")
    assert doc["reference"] == "Title"
    assert doc["section"] == "Title | Sub"
    assert "pkg.core" in doc["tokens"] and "app.py" in doc["tokens"]

    broken = summarize_file({"classification": {"language": "python", "role": "source"},
                             "module_doc": None, "symbols": None,
                             "unparsed": "SyntaxError:x"})
    assert broken["reference"].startswith("UNPARSED python")

    other = summarize_file({"classification": {"language": "toml", "role": "config"},
                            "module_doc": None, "symbols": None, "unparsed": None})
    assert other["reference"] == "toml config file"

    # ceilings enforced by truncation
    big_doc = summarize_file(doc_entry, "# " + "word " * 999)
    assert token_count(big_doc["full"]) <= FULL_TOKENS
    assert token_count(big_doc["reference"]) <= REFERENCE_TOKENS
    # no-docstring python: reference falls back to symbol names
    no_doc = dict(py_entry, module_doc=None)
    assert summarize_file(no_doc)["reference"] == "add Calc"
    print("summarize selftest ok")
