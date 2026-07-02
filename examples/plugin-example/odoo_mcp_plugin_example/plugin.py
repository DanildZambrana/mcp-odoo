"""Example odoo-mcp tool plugin.

Install this package next to odoo-mcp, then opt in:

    ODOO_MCP_PLUGINS=example uvx odoo-mcp

The ``register`` entry point receives the stable plugin API
(``odoo_mcp.plugin_api``). Follow the same rules as builtin tools: bounded
reads, field-ACL redaction on record data, the success/error envelope, and
NO direct writes — data modification must go through the gated workflow.
"""

from typing import Any, Dict, Optional


def register(api: Any) -> None:
    @api.tool(
        description="Example plugin tool: count records of a model",
        annotations=api.READ_ONLY_TOOL,
        structured_output=True,
    )
    def example_count_records(
        ctx: Any,
        model: str,
        instance: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Count records the current user can see in one model."""
        try:
            api.validate_model_name(model)
            instance_name, odoo = api.resolve_odoo(ctx, instance)
            count = odoo.execute_method(model, "search_count", [])
            return {
                "success": True,
                "tool": "example_count_records",
                "model": model,
                "instance": instance_name,
                "count": count,
            }
        except Exception as e:  # noqa: BLE001
            return api.error_envelope("example_count_records", e)
