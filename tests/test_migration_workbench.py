"""Migration workbench: upgrade-log analyzer + action taxonomy."""

import pytest

from odoo_mcp import diagnostics

SAMPLE_LOG = """
2026-07-01 10:00:01,001 INFO db odoo.modules.loading: loading module custom_billing
2026-07-01 10:00:02,002 ERROR db odoo.addons.base: Element '<xpath expr="//field[@name='vat']">' cannot be located in parent view
2026-07-01 10:00:02,010 ERROR db odoo.tools.convert: ValueError: External ID not found in the system: custom_billing.view_partner_form
2026-07-01 10:00:03,000 ERROR db odoo.sql_db: psycopg2.errors.NotNullViolation: null value in column "company_type"
2026-07-01 10:00:04,000 WARNING db odoo.addons: DeprecationWarning: name_get is deprecated
2026-07-01 10:00:05,000 ERROR db odoo.modules.loading: Some modules are not loaded, some dependencies or manifest may be missing
2026-07-01 10:00:02,002 ERROR db odoo.addons.base: Element '<xpath expr="//field[@name='vat']">' cannot be located in parent view
"""


def test_analyze_upgrade_log_classifies_and_dedupes():
    report = diagnostics.analyze_upgrade_log_report(
        SAMPLE_LOG, source_version="16.0", target_version="19.0"
    )
    assert report["success"] is True
    categories = {f["category"] for f in report["findings"]}
    assert {
        "view_xpath_not_found",
        "external_id_missing",
        "not_null_violation",
        "deprecation",
        "module_dependency",
    } <= categories
    # Duplicate xpath line reported once.
    xpath_findings = [
        f for f in report["findings"] if f["category"] == "view_xpath_not_found"
    ]
    assert len(xpath_findings) == 1
    summary = report["summary"]
    assert summary["clean"] is False
    assert summary["by_action"]["needs_script"] >= 3
    assert summary["log_truncated"] is False
    # Every finding carries evidence + suggestion + line number.
    for finding in report["findings"]:
        assert finding["evidence"] and finding["suggestion"] and finding["line"] > 0


def test_analyze_upgrade_log_clean_and_invalid_input():
    clean = diagnostics.analyze_upgrade_log_report("INFO all good\nINFO done")
    assert clean["summary"]["clean"] is True
    assert clean["findings"] == []
    with pytest.raises(ValueError):
        diagnostics.analyze_upgrade_log_report("   ")


def test_analyze_upgrade_log_truncates_huge_input():
    big = ("x" * 100 + "\n") * 12_000  # > MAX_LOG_BYTES
    report = diagnostics.analyze_upgrade_log_report(big)
    assert report["summary"]["log_truncated"] is True


def test_classify_finding_action_overrides_and_severity_fallback():
    assert (
        diagnostics.classify_finding_action("crud_override_missing_super", "warning")
        == diagnostics.ACTION_NEEDS_SCRIPT
    )
    assert (
        diagnostics.classify_finding_action("sudo_usage", "warning")
        == diagnostics.ACTION_NEEDS_REVIEW
    )
    assert (
        diagnostics.classify_finding_action("unknown_code", "error")
        == diagnostics.ACTION_NEEDS_SCRIPT
    )
    assert (
        diagnostics.classify_finding_action("unknown_code", "info")
        == diagnostics.ACTION_NO_ACTION
    )


def test_upgrade_risk_report_carries_action_worklist():
    report = diagnostics.upgrade_risk_report(
        source_version="16.0",
        target_version="19.0",
        source_findings=[
            {"code": "sudo_usage", "severity": "warning", "evidence": "x.py:1"}
        ],
    )
    assert "actions" in report["summary"]
    assert all("action" in risk for risk in report["risks"])


def test_scan_addons_report_carries_action_worklist(tmp_path):
    from odoo_mcp.agent_tools import scan_addons_source_report

    module = tmp_path / "demo_mod"
    module.mkdir()
    (module / "__manifest__.py").write_text(
        "{'name': 'demo', 'installable': False}", encoding="utf-8"
    )
    report = scan_addons_source_report(addons_paths=[str(tmp_path)])
    assert "actions" in report["summary"]
    assert all("action" in f for f in report["source_findings"])
