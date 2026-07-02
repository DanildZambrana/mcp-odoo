"""Data-quality pack: core checks, ACL exclusion, async allowlist."""

from typing import Any, Dict, List

import pytest

from odoo_mcp import data_quality
from odoo_mcp.tools_async import ASYNC_OPERATIONS

FIELDS_META = {
    "id": {"type": "integer", "store": True},
    "name": {"type": "char", "store": True, "required": True},
    "email": {"type": "char", "store": True},
    "vat": {"type": "char", "store": True},
    "parent_id": {
        "type": "many2one",
        "relation": "res.partner",
        "store": True,
        "required": False,
    },
    "salary": {"type": "float", "store": True},
    "tag_ids": {"type": "many2many", "relation": "res.tag", "required": True},
}


class FakeOdoo:
    """Minimal client exposing the three calls the checks use."""

    def __init__(self) -> None:
        self.calls: List[Any] = []

    def get_model_fields(self, model: str) -> Dict[str, Any]:
        return dict(FIELDS_META)

    def execute_method(self, model: str, method: str, *args: Any, **kw: Any) -> Any:
        self.calls.append((model, method, args))
        if method == "read_group":
            key = args[2][0]
            if key == "email":
                return [
                    {"email": "dup@x.com", "__count": 3},
                    {"email": "solo@x.com", "__count": 1},
                ]
            return [{key: "v", f"{key}_count": 1}]
        if method == "search_count":
            field = args[0][0][0]
            return 2 if field == "name" else 0
        if method == "search":
            # Target-existence probe: id 99 is missing.
            requested = set(args[0][0][2])
            return sorted(requested - {99})
        raise AssertionError(f"unexpected method {method}")

    def search_read(self, **kw: Any) -> List[Dict[str, Any]]:
        fields = kw.get("fields") or []
        if "parent_id" in fields:
            return [
                {"id": 1, "parent_id": [7, "OK Corp"]},
                {"id": 2, "parent_id": [99, "Ghost Corp"]},
            ]
        return [
            {"id": 1, "email": "good@x.com", "vat": "VN0312345678"},
            {"id": 2, "email": "not-an-email", "vat": "12"},
        ]


def _report(**kwargs):
    return data_quality.build_data_quality_report(
        FakeOdoo(), "default", "res.partner", **kwargs
    )


def test_all_checks_run_and_summarize():
    report = _report()
    assert report["success"] is True
    assert report["checks_run"] == list(data_quality.ALL_CHECKS)
    by_name = {r["check"]: r for r in report["results"]}

    dup = by_name["duplicates"]
    assert dup["issue_count"] == 2  # 3 records sharing one email → 2 extra
    assert dup["evidence"][0]["value"] == "dup@x.com"

    missing = by_name["missing_required"]
    assert missing["issue_count"] == 2
    assert missing["fields_checked"] == ["name"]  # m2m + system fields excluded

    orphans = by_name["orphaned_references"]
    assert orphans["issue_count"] == 1
    assert orphans["evidence"][0]["missing_target_id"] == 99

    fmt = by_name["format_anomalies"]
    assert fmt["issue_count"] == 2  # bad email + short vat
    assert report["summary"]["clean"] is False
    assert report["summary"]["total_issues"] == 7


def test_check_selection_and_unknown_check():
    report = _report(checks=["duplicates"])
    assert [r["check"] for r in report["results"]] == ["duplicates"]
    with pytest.raises(ValueError, match="Unknown checks"):
        _report(checks=["nope"])


def test_field_acl_excludes_denied_fields(monkeypatch):
    class Policy:
        def restricted_fields(self, instance, model, names):
            return [n for n in names if n == "email"]

    monkeypatch.setattr(data_quality, "get_field_policy", lambda: Policy())
    report = _report(checks=["duplicates", "format_anomalies"])
    assert report["skipped_restricted_fields"] == ["email"]
    by_name = {r["check"]: r for r in report["results"]}
    assert "email" not in by_name["duplicates"]["fields_checked"]
    assert "email" not in by_name["format_anomalies"]["fields_checked"]


def test_checks_fail_independently():
    class BoomOdoo(FakeOdoo):
        def execute_method(self, model, method, *args, **kw):
            if method == "read_group":
                raise RuntimeError("boom")
            return super().execute_method(model, method, *args, **kw)

    report = data_quality.build_data_quality_report(
        BoomOdoo(), "default", "res.partner", checks=["duplicates", "missing_required"]
    )
    by_name = {r["check"]: r for r in report["results"]}
    assert by_name["duplicates"]["error"] == "boom"
    assert by_name["missing_required"]["issue_count"] == 2
    assert "duplicates" in report["summary"]["checks_errored"]


def test_data_quality_registered_for_async():
    assert "data_quality_report" in ASYNC_OPERATIONS
