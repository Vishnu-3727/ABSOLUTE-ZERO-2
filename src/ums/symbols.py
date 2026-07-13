"""Symbol extraction — pluggable seam, exactly ONE built-in (Python ast).

extract(language, tree) routes through EXTRACTORS; unknown language ->
None (file-level record only, decided by the caller). Parsing and the
unparsed-file accounting live in extraction.py — this module receives an
already-parsed tree, so parse cost is paid once per file.

Symbols are plain dicts (json-ready for the canonical form):
{"name", "qualname", "kind": class|function|method, "line", "signature",
 "doc"}. Full docstrings kept — they are Phase 3's summarizer input.
"""
import ast


def _signature(node):
    sig = "(" + ast.unparse(node.args) + ")"
    if node.returns is not None:
        sig += " -> " + ast.unparse(node.returns)
    return sig


def extract_python(tree):
    """Symbol list from a parsed module, in source order."""
    symbols = []

    def visit(body, prefix, in_class):
        for node in body:
            if isinstance(node, ast.ClassDef):
                qual = prefix + node.name
                symbols.append({
                    "name": node.name, "qualname": qual, "kind": "class",
                    "line": node.lineno, "signature": "",
                    "doc": ast.get_docstring(node)})
                visit(node.body, qual + ".", True)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + node.name
                symbols.append({
                    "name": node.name, "qualname": qual,
                    "kind": "method" if in_class else "function",
                    "line": node.lineno, "signature": _signature(node),
                    "doc": ast.get_docstring(node)})
                visit(node.body, qual + ".", False)
    visit(tree.body, "", False)
    return symbols


# ponytail: one built-in extractor; other languages are a future seam,
# not built (blueprint: vault is Python, non-Python = file-level record).
EXTRACTORS = {"python": extract_python}


def extract(language, tree):
    """Route to the language's extractor; None when no extractor exists."""
    extractor = EXTRACTORS.get(language)
    if extractor is None:
        return None
    return extractor(tree)


if __name__ == "__main__":
    source = '''
"""Module doc."""


def top(a, b: int = 1) -> int:
    """Adds."""
    def inner():
        pass
    return a + b


class Greeter:
    """Says hi."""

    def hi(self, name: str) -> str:
        return "hi " + name


async def fetch():
    pass
'''
    syms = extract("python", ast.parse(source))
    by_qual = {s["qualname"]: s for s in syms}
    assert [s["qualname"] for s in syms] == [
        "top", "top.inner", "Greeter", "Greeter.hi", "fetch"]
    assert by_qual["top"]["kind"] == "function"
    assert by_qual["top"]["signature"] == "(a, b: int=1) -> int"
    assert by_qual["top"]["doc"] == "Adds."
    assert by_qual["top.inner"]["kind"] == "function"  # nested, not method
    assert by_qual["Greeter"]["kind"] == "class"
    assert by_qual["Greeter"]["doc"] == "Says hi."
    assert by_qual["Greeter.hi"]["kind"] == "method"
    assert by_qual["Greeter.hi"]["signature"] == "(self, name: str) -> str"
    assert by_qual["fetch"]["kind"] == "function"
    # determinism: same source, same table
    assert extract("python", ast.parse(source)) == syms
    # seam: unknown language has no extractor
    assert extract("markdown", None) is None
    print("symbols selftest ok")
