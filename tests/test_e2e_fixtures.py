"""E2E fixture의 삭제 범위 보호를 검증하는 단위 테스트. Docker E2E 결과가 아니다."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.e2e import fixtures


RUN_ID = "e2e-" + "a" * 32


class FixtureSession:
    """소유권 검증에 필요한 조회만 제공하며 변경 쿼리는 허용하지 않는다."""

    def __init__(self, *, signup=False, linked_resource=None, job_state=None):
        self.objects = {}
        self.signup = None
        self.linked_resource = linked_resource
        self.job_state = job_state
        self.scalar_count = 0
        self.scalars_count = 0
        self.manifest = SimpleNamespace(
            id=RUN_ID + "-manifest", kind="E2E_RUN", version=RUN_ID, verified=False,
            data={
                "fixtureVersion": fixtures.FIXTURE_VERSION,
                "runId": RUN_ID,
                "accounts": {},
                "signupLoginId": RUN_ID + "-signup",
                "referenceIds": [RUN_ID + "-" + name for name in fixtures.REFERENCE_NAMES],
            },
        )
        self.objects[fixtures.ReferenceData, self.manifest.id] = self.manifest
        for name in fixtures.ACCOUNT_NAMES:
            account = SimpleNamespace(id="account-" + name, login_id=RUN_ID + "-" + name)
            self.objects[fixtures.Account, account.id] = account
            self.manifest.data["accounts"][name] = {
                "accountId": account.id, "loginId": account.login_id,
            }
        for reference_id in self.manifest.data["referenceIds"]:
            self.objects[fixtures.ReferenceData, reference_id] = SimpleNamespace(version=RUN_ID)
        if signup:
            self.signup = SimpleNamespace(id="signup-account", login_id=RUN_ID + "-signup")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        return self

    def connection(self):
        return None

    def get(self, model, identity):
        return self.objects.get((model, identity))

    def scalar(self, statement):
        self.scalar_count += 1
        if self.scalar_count == 1:
            return self.signup
        return self.linked_resource

    def scalars(self, statement):
        self.scalars_count += 1
        if self.scalars_count == 1:
            return [SimpleNamespace(id="owned-resource")]
        if self.scalars_count == 2:
            return [SimpleNamespace(state=self.job_state)] if self.job_state else []
        raise AssertionError("보호 조건 확인 전에 파일을 조회했습니다.")

    def execute(self, statement):
        raise AssertionError("보호 조건에 해당하는 실행에서 데이터를 삭제했습니다.")


@pytest.mark.parametrize("run_id", ["", "e2e-*", "e2e-" + "a" * 31, "e2e-" + "A" * 32,
                                     "other-" + "a" * 32, RUN_ID + "-suffix"])
def test_fixture_rejects_ambiguous_run_ids(run_id):
    with pytest.raises(fixtures.FixtureError, match="run ID"):
        fixtures.validate_run_id(run_id)


def test_fixture_ownership_includes_only_manifest_accounts_and_exact_signup():
    db = FixtureSession(signup=True)
    assert fixtures.owned_accounts(db, db.manifest, RUN_ID) == {
        "account-user", "account-other", "account-technician", "signup-account",
    }


@pytest.mark.parametrize("change", [
    {"fixtureVersion": -1}, {"runId": "another-run"}, {"accounts": {}},
    {"signupLoginId": "unrelated-user"}, {"referenceIds": ["shared-reference"]},
])
def test_fixture_cleanup_rejects_changed_manifest(change):
    db = FixtureSession()
    db.manifest.data.update(deepcopy(change))
    with pytest.raises(fixtures.FixtureError, match="manifest"):
        fixtures.owned_accounts(db, db.manifest, RUN_ID)


@pytest.mark.parametrize("field,value", [
    ("kind", "SOURCE"), ("version", "another-run"), ("verified", True),
])
def test_fixture_cleanup_rejects_reference_masquerading_as_manifest(field, value):
    db = FixtureSession()
    setattr(db.manifest, field, value)
    with pytest.raises(fixtures.FixtureError, match="manifest"):
        fixtures.owned_accounts(db, db.manifest, RUN_ID)


@pytest.mark.parametrize("replacement", [None, "unrelated-login"])
def test_fixture_cleanup_rejects_missing_or_reassigned_account(replacement):
    db = FixtureSession()
    if replacement is None:
        del db.objects[fixtures.Account, "account-user"]
    else:
        db.objects[fixtures.Account, "account-user"].login_id = replacement
    with pytest.raises(fixtures.FixtureError, match="계정 소유권"):
        fixtures.owned_accounts(db, db.manifest, RUN_ID)


def test_fixture_cleanup_rejects_reference_owned_by_another_run():
    db = FixtureSession()
    reference_id = db.manifest.data["referenceIds"][0]
    db.objects[fixtures.ReferenceData, reference_id].version = "another-run"
    with pytest.raises(fixtures.FixtureError, match="기준 자료 소유권"):
        fixtures.owned_accounts(db, db.manifest, RUN_ID)


def test_fixture_cleanup_preserves_data_when_another_owner_references_it(monkeypatch):
    db = FixtureSession(linked_resource="foreign-resource")
    monkeypatch.setattr(fixtures, "validate_environment", lambda *args: None)
    monkeypatch.setattr(fixtures, "lock", lambda *args: None)
    with pytest.raises(fixtures.FixtureError, match="다른 계정 자료"):
        fixtures.cleanup_attempt(SimpleNamespace(), lambda: db, RUN_ID)


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
def test_fixture_cleanup_waits_for_worker_before_deleting(monkeypatch, state):
    db = FixtureSession(job_state=state)
    monkeypatch.setattr(fixtures, "validate_environment", lambda *args: None)
    monkeypatch.setattr(fixtures, "lock", lambda *args: None)
    assert fixtures.cleanup_attempt(SimpleNamespace(), lambda: db, RUN_ID) is None
