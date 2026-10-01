"""Failure-path checks for the opt-in live harness; no Things access."""

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def test_smoke_setup_registers_cleanup_before_readback(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "smoke_fixture", "tests/live/conftest.py"
    )
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setitem(
        sys.modules,
        "things",
        SimpleNamespace(tasks=Mock(side_effect=RuntimeError("readback failed"))),
    )
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    cleanup = Mock()
    monkeypatch.setattr(smoke, "_trash_and_verify", cleanup)
    finalizers = []
    request = SimpleNamespace(addfinalizer=finalizers.append)
    tools = SimpleNamespace(
        add_project=AsyncMock(
            return_value={"success": True, "project_id": "new-project"}
        )
    )

    with pytest.raises(RuntimeError, match="readback failed"):
        smoke.smoke_session.__wrapped__(request, tools)

    assert len(finalizers) == 1
    finalizers[0]()
    assert cleanup.call_args.args[0].project_id == "new-project"


def test_regression_setup_registers_cleanup_before_second_project(monkeypatch):
    from regression import conftest as regression

    monkeypatch.setitem(sys.modules, "things", SimpleNamespace(tasks=lambda **_: []))
    monkeypatch.setattr(regression.time, "sleep", lambda _: None)
    cleanup = Mock()
    monkeypatch.setattr(regression, "_teardown_sandbox", cleanup)
    mcp = SimpleNamespace(
        call=AsyncMock(
            side_effect=[
                {"success": True, "area_id": "new-area"},
                {"success": True, "project_id": "new-project"},
                {"success": False},
            ]
        )
    )
    finalizers = []
    request = SimpleNamespace(addfinalizer=finalizers.append)

    with pytest.raises(AssertionError, match="project B"):
        regression.sandbox.__wrapped__(request, SimpleNamespace(), mcp)

    assert len(finalizers) == 1
    finalizers[0]()
    session = cleanup.call_args.args[0]
    assert session.area_id == "new-area"
    assert session.tracked_project_ids == ["new-project"]
    assert session.project_b_id is None
    assert session.tag_created_via is None


def test_whitespace_tag_cleanup_preserves_existing_blank_tag(monkeypatch):
    from regression import conftest as regression
    from regression import test_tags

    old = {"uuid": "existing-blank", "title": ""}
    new = {"uuid": "new-blank", "title": ""}
    monkeypatch.setitem(
        sys.modules,
        "things",
        SimpleNamespace(tags=Mock(side_effect=[[old], [old, new]])),
    )
    monkeypatch.setattr(
        test_tags,
        "_second_server",
        lambda *_args, **_kwargs: (
            None,
            SimpleNamespace(call_sync=lambda *_a, **_k: {"success": False}),
        ),
    )
    delete = Mock()
    monkeypatch.setattr(regression, "_delete_tag_via_applescript", delete)

    test_tags.TestCreateTag().test_whitespace_only_name_rejected(None, None)

    delete.assert_called_once_with("new-blank")


@pytest.mark.parametrize("created_new", [False, True])
def test_regression_teardown_only_deletes_new_same_title_tag(monkeypatch, created_new):
    from regression import conftest as regression

    old = {"uuid": "existing-tag", "title": "test-title"}
    new = {"uuid": "new-tag", "title": "test-title"}
    deleted = []
    tags = [old, new] if created_new else [old]
    monkeypatch.setitem(
        sys.modules,
        "things",
        SimpleNamespace(
            tags=lambda: [t for t in tags if t["uuid"] not in deleted],
            get=lambda *_args, **_kwargs: None,
            tasks=lambda **_kwargs: [],
            areas=lambda: [],
        ),
    )
    monkeypatch.setattr(regression.time, "sleep", lambda _: None)
    delete = Mock(side_effect=deleted.append)
    monkeypatch.setattr(regression, "_delete_tag_via_applescript", delete)
    session = regression.Sandbox()
    session.tag_name = "test-title"
    session.tag_existing_ids = {"existing-tag"}
    session.tag_created_via = "create_tag"
    session.tag_id = "new-tag" if created_new else None

    regression._teardown_sandbox(session)

    assert deleted == (["new-tag"] if created_new else [])
