"""Repo registry: which repositories UMS manages.

Onboarding/offboarding is driven by Lifecycle's repository.onboarded /
repository.offboarded events — UMS consumes them, never publishes them
(COMPONENTS/memory.md). This module is only the bookkeeping; event wiring
is Phase 5.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RepoEntry:
    repo_id: str
    root_path: str


class Registry:
    def __init__(self):
        self._repos = {}

    def onboard(self, repo_id, root_path):
        if repo_id in self._repos:
            raise ValueError("registry.duplicate_repo:" + repo_id)
        entry = RepoEntry(repo_id=repo_id, root_path=root_path)
        self._repos[repo_id] = entry
        return entry

    def offboard(self, repo_id):
        if repo_id not in self._repos:
            raise ValueError("registry.unknown_repo:" + repo_id)
        del self._repos[repo_id]

    def get(self, repo_id):
        return self._repos.get(repo_id)

    def is_managed(self, repo_id):
        return repo_id in self._repos

    def repo_ids(self):
        return list(self._repos)


if __name__ == "__main__":
    reg = Registry()
    entry = reg.onboard("vault", "/repos/vault")
    assert reg.get("vault") is entry
    assert reg.is_managed("vault")
    assert reg.repo_ids() == ["vault"]
    try:
        reg.onboard("vault", "/elsewhere")
        raise SystemExit("duplicate onboard allowed")
    except ValueError:
        pass
    reg.offboard("vault")
    assert not reg.is_managed("vault")
    try:
        reg.offboard("vault")
        raise SystemExit("offboard of unknown repo allowed")
    except ValueError:
        pass
    print("registry selftest ok")
