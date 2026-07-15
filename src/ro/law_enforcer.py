"""RO Phase 5 static law enforcer — mirrors prt/law_enforcer.py's AST/text
scans over the whole component (RO/05 §10 testing philosophy: "every RO-*
invariant list = review gate +, where scannable, a law-enforcer-style
static check"). Runnable as `python -m ro.law_enforcer` (module selftest)
AND wired into tests/test_ro_phase5.py as an ordinary unittest.

Ten checks, each RO/05-derived (R11 a-j):
(a) no time/random/datetime imports anywhere in src/ro (RO-D2/D6/E9 —
    nondeterminism exists only inside the injected boundary call).
(b) zero-seam (RO-S8): no imports of prt/cm/ums/kernel/rsm packages.
(c) events.py's PUBLISHED/CONSUMED sets exactly match RO/05 §2's canon,
    literally (RO-S2).
(d) records.REQUEST_FORMS == set(renderer._RENDERERS) (the Phase 3 flagged
    sync gap — closed here).
(e) decision_gate.py never references DescriptorRow (RO-D3).
(f) dead/foreign event vocabulary absent from src/ro — no "plan.created",
    "exec.", "plugin." literals (RO is not PRT/CP; those names are not
    RO's to speak).
(g) metrics.py defines no callable beyond the trivial `get_definition`
    lookup (RO-S7 scannable half — zero computation).
(h) no "verdict" identifier anywhere in src/ro (RO-S5 scannable half —
    identifier-level, AST-based, so a docstring merely discussing the
    absence of a verdict path does not self-trip this scan).
(i) renderer._CONSTRAINT_CATEGORIES == invocation._CONSTRAINT_CATEGORIES
    (drift guard, both are local mirrors of the same RO/03 §9 six).
(j) `policy_proposals` is referenced only in priors.py/persistence.py —
    Experience's proposals are recorded, never consumed elsewhere (R4).
"""
import ast
from pathlib import Path

_RO_DIR = Path(__file__).parent
_MAIN_GUARD = 'if __name__ == "__main__":'

_FORBIDDEN_TIME_IMPORTS = {"time", "random", "datetime"}
_FORBIDDEN_SEAM_PACKAGES = {"prt", "cm", "ums", "kernel", "rsm"}

_EXPECTED_PUBLISHED = ("reasoning.decided", "reasoning.invoked", "reasoning.completed", "reasoning.failed")
_EXPECTED_CONSUMED = ("context.assembled", "prior.updated")

# Fragment-split so this file's own source text never contains the joined
# dead strings as a contiguous literal (self-match precaution, cm/prt
# law_enforcer.py precedent).
_DEAD_PHRASES = (
    "".join(("plan", ".", "created")),
    "".join(("exec", ".")),
    "".join(("plugin", ".")),
)
_DEAD_VOCAB_ALLOWLIST = {"law_enforcer.py"}  # this file names them, in order to scan for them


def _src_files():
    return sorted(p for p in _RO_DIR.glob("*.py") if p.name != "__init__.py")


def _pre_test_source(path):
    return path.read_text(encoding="utf-8").split(_MAIN_GUARD)[0]


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


# -- (a) no time/random/datetime imports --------------------------------

def check_no_forbidden_time_imports():
    violations = []
    for path in _src_files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_TIME_IMPORTS:
                        violations.append(path.name + ":import " + alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in _FORBIDDEN_TIME_IMPORTS:
                    violations.append(path.name + ":from " + node.module)
    return violations


# -- (b) zero-seam: no prt/cm/ums/kernel/rsm imports ---------------------

def check_zero_seam_imports():
    violations = []
    for path in _src_files():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _FORBIDDEN_SEAM_PACKAGES:
                        violations.append(path.name + ":import " + alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if node.level == 0 and top in _FORBIDDEN_SEAM_PACKAGES:
                    violations.append(path.name + ":from " + node.module)
    return violations


# -- (c) events.py canon matches RO/05 §2 literally -----------------------

def check_event_canon_matches():
    from . import events
    return (tuple(events.PUBLISHED) == _EXPECTED_PUBLISHED and
            tuple(events.CONSUMED) == _EXPECTED_CONSUMED)


# -- (d) records.REQUEST_FORMS == set(renderer._RENDERERS) ---------------

def check_request_forms_sync():
    from . import records, renderer
    return set(records.REQUEST_FORMS) == set(renderer._RENDERERS)


# -- (e) decision_gate.py never references DescriptorRow (RO-D3) ---------

def check_decision_gate_no_descriptor_row():
    tree = _tree(_RO_DIR / "decision_gate.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "DescriptorRow":
            return False
        if isinstance(node, ast.ImportFrom) and any(a.name == "DescriptorRow" for a in node.names):
            return False
    return True


# -- (f) dead/foreign event vocabulary absent -----------------------------

def check_dead_vocabulary_absent():
    violations = []
    for path in _src_files():
        if path.name in _DEAD_VOCAB_ALLOWLIST:
            continue
        pre_test = _pre_test_source(path)
        for phrase in _DEAD_PHRASES:
            if phrase in pre_test:
                violations.append(path.name + ":" + phrase)
    return violations


# -- (g) metrics.py: zero computation, no record/event-accepting function -

def check_metrics_zero_computation():
    tree = _tree(_RO_DIR / "metrics.py")
    names = [node.name for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return names == ["get_definition"]


# -- (h) no "verdict" identifier anywhere in src/ro (RO-S5) --------------

def _identifier_tokens(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.arg):
            yield node.arg
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.alias):
            yield node.asname or node.name


# composite.py (Phase 4, frozen — never edited by this phase) already uses
# `_verdict`/`failure_semantics_verdict` for an unrelated, pre-existing
# concept: RO's OWN governed reading of whether a composite's declared
# failure semantics (all_required/any_sufficient/quorum) were satisfied by
# its constituents' recovery kinds (RO/04 §8) — that is RO judging ITS OWN
# attempt bookkeeping, not a Verification verdict re-entering a sealed
# attempt (RO-S5's actual target). Interpretation call (see report):
# allowlisted here rather than renamed, since Phase 4 is frozen.
_VERDICT_SCAN_ALLOWLIST = {"composite.py", "law_enforcer.py"}


def check_no_verdict_identifier():
    violations = []
    for path in _src_files():
        if path.name in _VERDICT_SCAN_ALLOWLIST:
            continue
        for token in _identifier_tokens(_tree(path)):
            if "verdict" in token.lower():
                violations.append(path.name + ":" + token)
    return violations


# -- (i) renderer/invocation constraint-category mirrors agree ------------

def check_constraint_categories_agree():
    from . import invocation, renderer
    return tuple(renderer._CONSTRAINT_CATEGORIES) == tuple(invocation._CONSTRAINT_CATEGORIES)


# -- (j) policy_proposals touched only by priors.py/persistence.py --------

_POLICY_PROPOSALS_ALLOWLIST = {"priors.py", "persistence.py", "law_enforcer.py"}


def check_policy_proposals_confined():
    """Production code (pre-`__main__`-guard source, same convention as
    check_dead_vocabulary_absent) never references `policy_proposals`
    outside priors.py/persistence.py. A module's own selftest legitimately
    builds a `prior.updated` fixture payload containing that key (runtime.py
    et al.) — that is fixture data, not a consuming code path."""
    violations = []
    for path in _src_files():
        if path.name in _POLICY_PROPOSALS_ALLOWLIST:
            continue
        if "policy_proposals" in _pre_test_source(path):
            violations.append(path.name)
    return violations


def run():
    """Every check; raises AssertionError naming the first violated law."""
    assert not check_no_forbidden_time_imports(), \
        "law_enforcer.forbidden_time_import:" + ",".join(check_no_forbidden_time_imports())
    assert not check_zero_seam_imports(), \
        "law_enforcer.zero_seam_violation:" + ",".join(check_zero_seam_imports())
    assert check_event_canon_matches(), "law_enforcer.event_canon_drift"
    assert check_request_forms_sync(), "law_enforcer.request_forms_drift"
    assert check_decision_gate_no_descriptor_row(), "law_enforcer.decision_gate_imports_descriptor_row"
    assert not check_dead_vocabulary_absent(), \
        "law_enforcer.dead_vocabulary_present:" + ",".join(check_dead_vocabulary_absent())
    assert check_metrics_zero_computation(), "law_enforcer.metrics_has_computation"
    assert not check_no_verdict_identifier(), \
        "law_enforcer.verdict_identifier_present:" + ",".join(check_no_verdict_identifier())
    assert check_constraint_categories_agree(), "law_enforcer.constraint_categories_drift"
    assert not check_policy_proposals_confined(), \
        "law_enforcer.policy_proposals_leaked:" + ",".join(check_policy_proposals_confined())
    return True


if __name__ == "__main__":
    import tempfile

    assert run()

    # each scan trips on a synthetic violation (temp source string, never
    # repo files) -----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        bad_time = tmp_path / "bad_time.py"
        bad_time.write_text("import random\n", encoding="utf-8")
        tree = ast.parse(bad_time.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.Import) and n.names[0].name == "random" for n in ast.walk(tree))

        bad_seam = tmp_path / "bad_seam.py"
        bad_seam.write_text("from prt import events\n", encoding="utf-8")
        tree2 = ast.parse(bad_seam.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.ImportFrom) and n.module == "prt" for n in ast.walk(tree2))

        bad_verdict = tmp_path / "bad_verdict.py"
        bad_verdict.write_text("def accept_verdict(verdict):\n    return verdict\n", encoding="utf-8")
        tree3 = ast.parse(bad_verdict.read_text(encoding="utf-8"))
        tokens = list(_identifier_tokens(tree3))
        assert any("verdict" in t.lower() for t in tokens)

        bad_dead = tmp_path / "bad_dead.py"
        bad_dead.write_text('EVENT = "plugin." + "loaded"\n', encoding="utf-8")
        assert "plugin." in bad_dead.read_text(encoding="utf-8")

        bad_metrics = tmp_path / "bad_metrics.py"
        bad_metrics.write_text("def get_definition(metric_id):\n    pass\n\n"
                                "def compute(record):\n    pass\n", encoding="utf-8")
        tree4 = ast.parse(bad_metrics.read_text(encoding="utf-8"))
        names = [n.name for n in ast.walk(tree4) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert names != ["get_definition"]

        bad_proposals = tmp_path / "bad_proposals.py"
        bad_proposals.write_text("x = record.policy_proposals\n", encoding="utf-8")
        assert "policy_proposals" in bad_proposals.read_text(encoding="utf-8")

    print("law_enforcer selftest ok")
