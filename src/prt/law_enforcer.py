"""PRT Phase 5 static law enforcer — precedent: ums/cm law_enforcer.py's
AST/text scans over the whole component enforcing structural invariants no
runtime unit test can catch (an invariant about the SHAPE of the source,
not its behavior on any given input). Runnable as `python -m src.prt.
law_enforcer` (module selftest) AND wired into tests/test_prt_phase5.py as
an ordinary unittest.

Six laws, each PRT/05-derived:
(a) dead vocabulary (PRT/05 §4 D1/D2 draft names, PRT-S2) never appears in
    PRODUCTION code — only events.py may NAME it, to refuse it; a selftest
    demonstrating refusal (retirement.py, reliability_bridge.py) is not
    production usage, so it is only checked in the pre-`__main__`-guard
    portion of every OTHER file. This module is itself allowlisted (it
    only discusses the dead names in prose, never fragments them below).
(b) no `import time`/`random`/`datetime` anywhere in src/prt (PRT-B3/H1:
    wall-clock and randomness are forbidden binding/health inputs,
    structurally, not just by convention).
(c) health.py imports nothing from registry.py (PRT-H2).
(d) events.py's PUBLISHED/CONSUMED sets exactly match PRT/05 §4's canon
    table, literally.
(e) binding.py contains no registry mutation call (`.apply(`) — binding
    reads the registry, never writes it.
(f) AllowAllLegality is never referenced as a DEFAULT in src/ — only its
    own definition (load_policy.py) and explicit test-fixture use survive
    (boundary ruling); checked the same pre-`__main__`-guard way as (a).
"""
import ast
from pathlib import Path

_PRT_DIR = Path(__file__).parent
_MAIN_GUARD = 'if __name__ == "__main__":'

# Fragment-split so THIS file's own source text never contains the joined
# dead strings — a scan that (hypothetically) included law_enforcer.py
# itself must not self-flag its own enforcement logic.
_DEAD_PHRASES = (
    "".join(("plugin", ".", "disabled")),
    "".join(("process", ".", "failed")),
    "".join(("process", ".", "timeout")),
)
# events.py is the sole file permitted to NAME dead vocabulary, in order to
# refuse it (its own _DEAD rejection dict is production code, by design).
# law_enforcer.py itself is allowlisted too: its module docstring discusses
# the dead names in prose (never fragmented, unlike _DEAD_PHRASES below).
_DEAD_VOCAB_ALLOWLIST = {"events.py", "law_enforcer.py"}

_FORBIDDEN_IMPORTS = {"time", "random", "datetime"}

_EXPECTED_PUBLISHED = ("plugin.discovered", "plugin.registered", "plugin.loaded",
                       "plugin.unloaded", "plugin.health.changed")
_EXPECTED_CONSUMED = ("plugin.lifecycle.changed", "reliability.updated",
                      "exec.failed", "exec.timeout", "exec.completed")


def _src_files():
    return sorted(p for p in _PRT_DIR.glob("*.py") if p.name != "__init__.py")


def _pre_test_source(path):
    text = path.read_text(encoding="utf-8")
    return text.split(_MAIN_GUARD)[0]


def check_dead_vocabulary_absent():
    """(a) — dead vocabulary absent from production code."""
    violations = []
    for path in _src_files():
        if path.name in _DEAD_VOCAB_ALLOWLIST:
            continue
        pre_test = _pre_test_source(path)
        for phrase in _DEAD_PHRASES:
            if phrase in pre_test:
                violations.append(path.name + ":" + phrase)
    return violations


def check_no_forbidden_time_imports():
    """(b) — no wall-clock/randomness import anywhere in src/prt."""
    violations = []
    for path in _src_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_IMPORTS:
                        violations.append(path.name + ":import " + alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in _FORBIDDEN_IMPORTS:
                    violations.append(path.name + ":from " + node.module)
    return violations


def check_health_no_registry_import():
    """(c) — health.py imports nothing from registry.py (PRT-H2)."""
    tree = ast.parse((_PRT_DIR / "health.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.rsplit(".", 1)[-1])
        elif isinstance(node, ast.Import):
            imported.update(n.name.rsplit(".", 1)[-1] for n in node.names)
    return "registry" in imported


def check_event_canon_matches():
    """(d) — events.py's declared sets exactly equal PRT/05 §4's table."""
    from . import events
    return (tuple(events.PUBLISHED) == _EXPECTED_PUBLISHED and
            tuple(events.CONSUMED) == _EXPECTED_CONSUMED)


def check_binding_no_registry_mutation():
    """(e) — binding.py's own logic never mutates the registry (its
    selftest fixture setup, after the `__main__` guard, legitimately
    builds a Registry via apply() the same way every other module's
    selftest does — that is fixture setup, not binding.py's production
    code path, which only ever reads)."""
    pre_test = _pre_test_source(_PRT_DIR / "binding.py")
    return ".apply(" not in pre_test


def check_allowall_not_a_default():
    """(f) — AllowAllLegality is never a production default."""
    violations = []
    for path in _src_files():
        pre_test = _pre_test_source(path)
        if "AllowAllLegality(" in pre_test:
            violations.append(path.name)
    return violations


_CHECKS = (
    ("dead_vocabulary_present", check_dead_vocabulary_absent),
    ("forbidden_time_import", check_no_forbidden_time_imports),
    ("allowall_default_in", check_allowall_not_a_default),
)


def run():
    """Every check; raises AssertionError naming the first violated law."""
    for label, check in _CHECKS:
        violations = check()
        assert not violations, "law_enforcer." + label + ":" + ",".join(violations)

    assert not check_health_no_registry_import(), "law_enforcer.health_imports_registry"
    assert check_event_canon_matches(), "law_enforcer.event_canon_drift"
    assert check_binding_no_registry_mutation(), "law_enforcer.binding_mutates_registry"

    return True


if __name__ == "__main__":
    assert run()
    print("law_enforcer selftest ok")
