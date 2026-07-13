"""Convention profiler — measured numbers, never judgments.

measure() produces per-file counters from source text + parsed tree
(stored in the extraction record, so unchanged files are never re-measured
— token law). profile() aggregates counters into the repo profile:
sums plus derived coverage ratios (rounded, deterministic).

Measured: indent (space vs tab lines, leading-space run widths), quotes
(string tokens starting ' vs "), naming (snake_case defs, PascalCase
classes), docstring coverage, type-hint coverage.
"""
import ast
import io
import re
import tokenize

_SNAKE = re.compile(r"[a-z_][a-z0-9_]*\Z")
_PASCAL = re.compile(r"[A-Z][A-Za-z0-9]*\Z")

COUNTER_KEYS = (
    "lines", "indent_space_lines", "indent_tab_lines",
    "quote_single", "quote_double",
    "defs", "defs_snake", "defs_docstring", "defs_annotated",
    "classes", "classes_pascal",
)


def _fully_annotated(node):
    args = node.args
    names = args.posonlyargs + args.args + args.kwonlyargs
    # ponytail: self/cls skipped by name, vararg/kwarg ignored — good
    # enough for a coverage ratio, tighten if the number ever matters.
    required = [a for a in names if a.arg not in ("self", "cls")]
    return (node.returns is not None
            and all(a.annotation is not None for a in required))


def measure(source, tree):
    """Per-file counters (plain dict, json-ready)."""
    counts = dict.fromkeys(COUNTER_KEYS, 0)
    widths = {}
    for line in source.splitlines():
        counts["lines"] += 1
        if line.startswith("\t"):
            counts["indent_tab_lines"] += 1
        elif line.startswith(" ") and line.strip():
            counts["indent_space_lines"] += 1
            width = len(line) - len(line.lstrip(" "))
            widths[str(width)] = widths.get(str(width), 0) + 1
    counts["indent_width_lines"] = widths

    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.STRING or tok.type == tokenize.FSTRING_START:
                body = tok.string.lstrip("rbuRBUfF")
                if body.startswith("'"):
                    counts["quote_single"] += 1
                elif body.startswith('"'):
                    counts["quote_double"] += 1
    except tokenize.TokenizeError:
        pass  # tree parsed, so this is unreachable in practice; stay loud-free

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            counts["defs"] += 1
            counts["defs_snake"] += bool(_SNAKE.match(node.name))
            counts["defs_docstring"] += ast.get_docstring(node) is not None
            counts["defs_annotated"] += _fully_annotated(node)
        elif isinstance(node, ast.ClassDef):
            counts["classes"] += 1
            counts["classes_pascal"] += bool(_PASCAL.match(node.name))
    return counts


def _ratio(part, whole):
    return round(part / whole, 4) if whole else 0.0


def profile(counters_list):
    """Aggregate per-file counters into the repo convention profile."""
    total = dict.fromkeys(COUNTER_KEYS, 0)
    widths = {}
    for counters in counters_list:
        for key in COUNTER_KEYS:
            total[key] += counters[key]
        for width, n in counters["indent_width_lines"].items():
            widths[width] = widths.get(width, 0) + n
    # dominant indent width: most lines, ties broken by smaller width
    common = min(widths, key=lambda w: (-widths[w], int(w))) if widths else None
    return {
        "files_measured": len(counters_list),
        "counts": total,
        "indent_common_width": int(common) if common else 0,
        "docstring_coverage": _ratio(total["defs_docstring"], total["defs"]),
        "hint_coverage": _ratio(total["defs_annotated"], total["defs"]),
        "snake_case_def_ratio": _ratio(total["defs_snake"], total["defs"]),
        "pascal_class_ratio": _ratio(total["classes_pascal"], total["classes"]),
        "single_quote_ratio": _ratio(
            total["quote_single"],
            total["quote_single"] + total["quote_double"]),
    }


if __name__ == "__main__":
    source = (
        '"""Doc."""\n'
        "\n"
        "\n"
        "def good(a: int) -> int:\n"
        '    """Has doc."""\n'
        "    x = 'single'\n"
        '    y = "double"\n'
        "    return a\n"
        "\n"
        "\n"
        "def BadName(self_arg):\n"
        "    return 1\n"
        "\n"
        "\n"
        "class Thing:\n"
        "    def method(self, n: int) -> None:\n"
        "        pass\n"
    )
    counts = measure(source, ast.parse(source))
    assert counts["defs"] == 3 and counts["classes"] == 1
    assert counts["defs_snake"] == 2       # good, method
    assert counts["defs_docstring"] == 1   # good (module doc not a def)
    assert counts["defs_annotated"] == 2   # good, method (self skipped)
    assert counts["classes_pascal"] == 1
    assert counts["quote_single"] == 1
    assert counts["quote_double"] >= 2     # docstrings + "double"
    assert counts["indent_tab_lines"] == 0
    assert counts["indent_width_lines"]["4"] >= 4
    assert measure(source, ast.parse(source)) == counts  # deterministic

    prof = profile([counts, counts])
    assert prof["files_measured"] == 2
    assert prof["counts"]["defs"] == 6
    assert prof["indent_common_width"] == 4
    assert prof["docstring_coverage"] == round(2 / 6, 4)
    assert prof["hint_coverage"] == round(4 / 6, 4)
    assert profile([]) == profile([])      # empty repo doesn't crash
    assert profile([])["indent_common_width"] == 0
    print("conventions selftest ok")
