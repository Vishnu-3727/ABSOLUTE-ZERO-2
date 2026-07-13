"""Per-file language + role classification. Extension + marker based.

Pure table lookup over the path and (for extensionless files) the first
line's shebang. Measured facts, no judgment, no content parsing.
"""
import os

LANG_BY_EXT = {
    ".py": "python",
    ".md": "markdown",
    ".rst": "text",
    ".txt": "text",
    ".json": "json",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".sh": "shell",
}

CONFIG_LANGS = ("json", "toml", "ini", "yaml")
DOC_LANGS = ("markdown", "text")


def _shebang_language(head):
    """Language from a #! first line, else None."""
    if not head.startswith(b"#!"):
        return None
    first_line = head.split(b"\n", 1)[0]
    if b"python" in first_line:
        return "python"
    if b"sh" in first_line:  # sh, bash, zsh
        return "shell"
    return None


def classify(path, head=b""):
    """Return {"language", "role"} for a repo-relative posix path.

    head = leading bytes of the file (only consulted when the extension
    says nothing — shebang marker).
    """
    ext = os.path.splitext(path)[1].lower()
    language = LANG_BY_EXT.get(ext) or _shebang_language(head) or "unknown"
    parts = path.split("/")
    name = parts[-1]
    if name.startswith("test_") or name.endswith("_test.py") or "tests" in parts[:-1]:
        role = "test"
    elif language in CONFIG_LANGS:
        role = "config"
    elif language in DOC_LANGS:
        role = "doc"
    else:
        role = "source"
    return {"language": language, "role": role}


if __name__ == "__main__":
    assert classify("pkg/core.py") == {"language": "python", "role": "source"}
    assert classify("tests/test_x.py") == {"language": "python", "role": "test"}
    assert classify("test_y.py")["role"] == "test"
    assert classify("README.md") == {"language": "markdown", "role": "doc"}
    assert classify("settings.toml") == {"language": "toml", "role": "config"}
    assert classify("conf.yml")["role"] == "config"
    assert classify("bin/tool", b"#!/usr/bin/env python3\n") == \
        {"language": "python", "role": "source"}
    assert classify("bin/run", b"#!/bin/bash\n")["language"] == "shell"
    assert classify("mystery.bin") == {"language": "unknown", "role": "source"}
    assert classify("data", b"no shebang")["language"] == "unknown"
    print("classify selftest ok")
