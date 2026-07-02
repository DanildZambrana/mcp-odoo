"""Plugin loading, isolation, and tool filtering."""

import asyncio
from types import SimpleNamespace

from odoo_mcp import plugin_api, server, server_core


def _tools():
    return {t.name for t in asyncio.run(server.mcp.list_tools())}


def _fake_entry_points(monkeypatch, mapping):
    """mapping: name -> register callable (or loader raising)."""

    entries = []
    for name, register in mapping.items():
        entries.append(SimpleNamespace(name=name, load=lambda r=register: r))

    def fake_entry_points(*, group):
        assert group == "odoo_mcp.tools"
        return entries

    import importlib.metadata as md

    monkeypatch.setattr(md, "entry_points", fake_entry_points)


def test_no_env_means_no_plugin_load(monkeypatch):
    monkeypatch.delenv("ODOO_MCP_PLUGINS", raising=False)
    server_core.load_plugins(plugin_api)
    posture = server_core.plugin_posture()
    assert posture["enabled"] == []
    assert posture["loaded"] == []
    assert posture["failed"] == {}


def test_plugin_registers_tool_and_survives_failures(monkeypatch):
    def good(api):
        from typing import Any, Dict

        @api.tool(description="demo plugin tool", structured_output=True)
        def plugin_demo_tool() -> Dict[str, Any]:
            return {"success": True, "tool": "plugin_demo_tool"}

    def bad(api):
        raise RuntimeError("kaboom")

    _fake_entry_points(monkeypatch, {"good": good, "bad": bad})
    monkeypatch.setenv("ODOO_MCP_PLUGINS", "good, bad, ghost")
    try:
        server_core.load_plugins(plugin_api)
        posture = server_core.plugin_posture()
        assert posture["loaded"] == ["good"]
        assert "RuntimeError: kaboom" in posture["failed"]["bad"]
        assert "ghost" in posture["failed"]
        assert "plugin_demo_tool" in _tools()
    finally:
        server.mcp._tool_manager._tools.pop("plugin_demo_tool", None)
        monkeypatch.delenv("ODOO_MCP_PLUGINS", raising=False)
        server_core.load_plugins(plugin_api)


def test_tool_filter_include_exclude(monkeypatch):
    registry = server.mcp._tool_manager._tools
    before = dict(registry)
    try:
        monkeypatch.setenv(
            "ODOO_MCP_TOOLS_INCLUDE", "search_records,read_record,health_check"
        )
        monkeypatch.setenv("ODOO_MCP_TOOLS_EXCLUDE", "read_*")
        server_core.apply_tool_filter()
        names = _tools()
        assert names == {"search_records", "health_check"}
        filtered = server_core.plugin_posture()["tools_filtered"]
        assert "aggregate_records" in filtered and "read_record" in filtered
    finally:
        registry.clear()
        registry.update(before)
        monkeypatch.delenv("ODOO_MCP_TOOLS_INCLUDE", raising=False)
        monkeypatch.delenv("ODOO_MCP_TOOLS_EXCLUDE", raising=False)
        server_core.apply_tool_filter()


def test_filter_noop_without_env(monkeypatch):
    monkeypatch.delenv("ODOO_MCP_TOOLS_INCLUDE", raising=False)
    monkeypatch.delenv("ODOO_MCP_TOOLS_EXCLUDE", raising=False)
    count_before = len(_tools())
    server_core.apply_tool_filter()
    assert len(_tools()) == count_before
    assert server_core.plugin_posture()["tools_filtered"] == []


def test_health_check_reports_plugin_posture():
    from odoo_mcp.tools_read import health_check

    report = health_check()
    assert report["plugins"] == server_core.plugin_posture()


def test_plugin_api_surface_is_stable():
    from odoo_mcp import plugin_api

    assert plugin_api.PLUGIN_API_VERSION == 1
    for member in (
        "tool",
        "resolve_odoo",
        "redact_records",
        "error_envelope",
        "validate_model_name",
        "clamp_limit",
        "READ_ONLY_TOOL",
        "PREVIEW_TOOL",
    ):
        assert hasattr(plugin_api, member), member
