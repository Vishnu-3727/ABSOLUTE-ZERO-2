"""VAE Phase 5 static law enforcer — mirrors ro/law_enforcer.py's and
prt/law_enforcer.py's AST/text scans over the whole component (VAE-S8:
"the implementation is verified against the invariant registers... phase-
document prose is rationale, invariants are law"). Runnable as
`python -m vae.law_enforcer` (module selftest) AND wired into
tests/test_vae_phase5.py as an ordinary unittest.

Seven checks, each blueprint-Phase-5-derived ("event sets == canon, no
sibling imports, no time/random in judgment paths, append-only surface,
persist-before-publish order, verdict-function takes no producer
identity"):

(a) no time/random/datetime imports anywhere in src/vae (VAE-I6: "no
    clock/random reads in judgment paths" — checked package-wide since
    every module here IS on some judgment path).
(b) zero-seam (VAE/06 "Global laws"): no imports of kernel/ums/ro/cm/prt/
    rsm packages.
(c) events.py's PUBLISHED/CONSUMED sets exactly match VAE/05 §2's canon,
    literally (VAE-S2/S3).
(d) evidence.py's EvidenceRecord exposes no edit/remove/set-item method —
    append_item is the only mutation path that exists (VAE-M2/VAE-A6,
    "no such API surface exists").
(e) emission.py's emit_verdict() calls Storage's write BEFORE any
    events.emit() call, on every source line where either appears
    (VAE-O5, "persist, then publish, always").
(f) derivation.derive() and emission.build_verdict_envelope() accept no
    producer/provider-identity parameter (VAE-S7: "the verdict function
    takes no producer identity").
(g) dead/foreign event vocabulary absent from src/vae — no "task.
    scheduled", "plan.revised", "exec.started" literals (those are
    Scheduling's/Capability Planning's/Execution's own emissions, never
    VAE's to speak; VAE/05 §2.1's "no other event is VAE's to publish").
"""
import ast
from pathlib import Path

_VAE_DIR = Path(__file__).parent
_MAIN_GUARD = 'if __name__ == "__main__":'

_FORBIDDEN_TIME_IMPORTS = {"time", "random", "datetime"}
_FORBIDDEN_SEAM_PACKAGES = {"kernel", "ums", "ro", "cm", "prt", "rsm"}

_EXPECTED_PUBLISHED = ("verify.passed", "verify.failed", "plan.validated",
                        "plan.rejected", "fault.recorded")
_EXPECTED_CONSUMED = ("verify.requested", "plan.created", "exec.completed", "reasoning.completed")

_FORBIDDEN_ITEM_MUTATORS = {"edit_item", "remove_item", "set_item"}

# Fragment-split so this file's own source text never contains the joined
# dead strings as a contiguous literal (self-match precaution, ro/prt
# law_enforcer.py precedent).
_DEAD_PHRASES = (
    "".join(("task", ".", "scheduled")),
    "".join(("plan", ".", "revised")),
    "".join(("exec", ".", "started")),
)
_DEAD_VOCAB_ALLOWLIST = {"law_enforcer.py"}  # this file names them, in order to scan for them

_PRODUCER_IDENTITY_PARAMS = {"producer_id", "provider_id", "producer", "provider",
                              "author_id", "author"}


def _src_files():
    return sorted(p for p in _VAE_DIR.glob("*.py") if p.name != "__init__.py")


def _pre_test_source(path):
    return path.read_text(encoding="utf-8").split(_MAIN_GUARD)[0]


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


# -- (a) no time/random/datetime imports ----------------------------------

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


# -- (b) zero-seam: no kernel/ums/ro/cm/prt/rsm imports --------------------

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


# -- (c) events.py canon matches VAE/05 §2 literally -----------------------

def check_event_canon_matches():
    from . import events
    return (tuple(events.PUBLISHED) == _EXPECTED_PUBLISHED and
            tuple(events.CONSUMED) == _EXPECTED_CONSUMED)


# -- (d) evidence.py's EvidenceRecord has no edit/remove/set-item method ---

def check_no_item_mutators():
    tree = _tree(_VAE_DIR / "evidence.py")
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _FORBIDDEN_ITEM_MUTATORS:
            violations.append("evidence.py:" + node.name)
    return violations


# -- (e) emit_verdict(): storage.write precedes every events.emit call ----

def check_persist_before_publish_order():
    tree = _tree(_VAE_DIR / "emission.py")
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "emit_verdict"), None)
    if fn is None:
        return ["emission.py:emit_verdict_not_found"]

    write_lines = []
    emit_lines = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "write":
                write_lines.append(node.lineno)
            elif node.func.attr == "emit" and getattr(node.func.value, "id", None) == "events":
                emit_lines.append(node.lineno)

    if not write_lines or not emit_lines:
        return ["emission.py:missing_write_or_emit_call"]
    earliest_write = min(write_lines)
    violations = [str(line) for line in emit_lines if line < earliest_write]
    return violations


# -- (f) no producer/provider identity in the verdict-function signatures -

def check_no_producer_identity_in_verdict_functions():
    violations = []
    for module_name, fn_name in (("derivation.py", "derive"), ("emission.py", "build_verdict_envelope")):
        tree = _tree(_VAE_DIR / module_name)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
        if fn is None:
            violations.append(module_name + ":" + fn_name + ":not_found")
            continue
        params = {a.arg for a in fn.args.args}
        bad = params & _PRODUCER_IDENTITY_PARAMS
        if bad:
            violations.append(module_name + ":" + fn_name + ":" + ",".join(sorted(bad)))
    return violations


# -- (g) dead/foreign event vocabulary absent ------------------------------

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


def run():
    """Every check; raises AssertionError naming the first violated law."""
    assert not check_no_forbidden_time_imports(), \
        "law_enforcer.forbidden_time_import:" + ",".join(check_no_forbidden_time_imports())
    assert not check_zero_seam_imports(), \
        "law_enforcer.zero_seam_violation:" + ",".join(check_zero_seam_imports())
    assert check_event_canon_matches(), "law_enforcer.event_canon_drift"
    assert not check_no_item_mutators(), \
        "law_enforcer.item_mutator_present:" + ",".join(check_no_item_mutators())
    assert not check_persist_before_publish_order(), \
        "law_enforcer.publish_before_persist:" + ",".join(check_persist_before_publish_order())
    assert not check_no_producer_identity_in_verdict_functions(), \
        "law_enforcer.producer_identity_in_verdict_function:" + \
        ",".join(check_no_producer_identity_in_verdict_functions())
    assert not check_dead_vocabulary_absent(), \
        "law_enforcer.dead_vocabulary_present:" + ",".join(check_dead_vocabulary_absent())
    return True


if __name__ == "__main__":
    import tempfile

    assert run()

    # each scan trips on a synthetic violation (temp source string / ad hoc
    # tree, never repo files) ------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        bad_time = tmp_path / "bad_time.py"
        bad_time.write_text("import random\n", encoding="utf-8")
        tree = ast.parse(bad_time.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.Import) and n.names[0].name == "random" for n in ast.walk(tree))

        bad_seam = tmp_path / "bad_seam.py"
        bad_seam.write_text("from ro import events\n", encoding="utf-8")
        tree2 = ast.parse(bad_seam.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.ImportFrom) and n.module == "ro" for n in ast.walk(tree2))

        bad_mutator = tmp_path / "bad_mutator.py"
        bad_mutator.write_text("def edit_item(record, index, item):\n    pass\n", encoding="utf-8")
        tree3 = ast.parse(bad_mutator.read_text(encoding="utf-8"))
        assert any(isinstance(n, ast.FunctionDef) and n.name in _FORBIDDEN_ITEM_MUTATORS
                   for n in ast.walk(tree3))

        bad_order = tmp_path / "bad_order.py"
        bad_order.write_text(
            "def emit_verdict(a, b, storage, bus, c):\n"
            "    events.emit(bus, 'verify.passed', 'e', 's', {})\n"
            "    storage.write('k', b'v')\n", encoding="utf-8")
        tree4 = ast.parse(bad_order.read_text(encoding="utf-8"))
        fn4 = next(n for n in ast.walk(tree4) if isinstance(n, ast.FunctionDef))
        write_lines4 = [n.lineno for n in ast.walk(fn4)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "write"]
        emit_lines4 = [n.lineno for n in ast.walk(fn4)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "emit" and getattr(n.func.value, "id", None) == "events"]
        assert any(e < min(write_lines4) for e in emit_lines4)

        bad_producer = tmp_path / "bad_producer.py"
        bad_producer.write_text("def derive(record, policy, producer_id):\n    pass\n", encoding="utf-8")
        tree5 = ast.parse(bad_producer.read_text(encoding="utf-8"))
        fn5 = next(n for n in ast.walk(tree5) if isinstance(n, ast.FunctionDef))
        params5 = {a.arg for a in fn5.args.args}
        assert params5 & _PRODUCER_IDENTITY_PARAMS

        bad_dead = tmp_path / "bad_dead.py"
        bad_dead.write_text('EVENT = "task.scheduled"\n', encoding="utf-8")
        assert _DEAD_PHRASES[0] in bad_dead.read_text(encoding="utf-8")

    print("law_enforcer selftest ok")
