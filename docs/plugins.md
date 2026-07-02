# Tool plugins

Since v1.1 third parties can ship their own MCP tools for odoo-mcp as normal
Python packages — no fork required. An agency can add its vertical's tools
(`construction_wip_report`, `pharma_batch_trace`, …) and keep pulling
upstream releases.

## Security model — read first

- **Installation alone activates nothing.** A plugin only loads when its
  entry-point name is listed in `ODOO_MCP_PLUGINS`. No env var → no plugin
  code runs, ever.
- **A plugin is arbitrary Python running in the server process** with the
  server's Odoo credentials. There is no sandbox. Install only plugins you
  trust exactly as much as odoo-mcp itself.
- **Fail-isolated:** a plugin that raises at load time is recorded in
  `health_check.plugins.failed` and skipped; builtin tools keep serving.
- **Contract:** plugins must follow the same rules as builtin tools —
  bounded reads, `api.redact_records` on record data, the
  `{"success": ...}` envelope, and **no direct writes** (route changes
  through the gated write workflow). The API deliberately exposes no
  gate-bypassing helpers; a plugin that mutates data directly is violating
  the contract and should be treated as untrusted.

## Writing a plugin

1. Create a package with an `odoo_mcp.tools` entry point:

   ```toml
   [project.entry-points."odoo_mcp.tools"]
   my_plugin = "my_pkg.plugin:register"
   ```

2. Implement `register(api)` — `api` is `odoo_mcp.plugin_api`
   (`api.PLUGIN_API_VERSION == 1`):

   ```python
   def register(api):
       @api.tool(description="...", annotations=api.READ_ONLY_TOOL,
                 structured_output=True)
       def my_tool(ctx, model: str, instance: str | None = None) -> dict:
           try:
               api.validate_model_name(model)
               instance_name, odoo = api.resolve_odoo(ctx, instance)
               rows = odoo.search_read(model_name=model, domain=[],
                                       fields=["id", "name"], offset=0,
                                       limit=api.clamp_limit(50), order=None)
               rows, redacted = api.redact_records(instance_name, model, rows)
               return {"success": True, "tool": "my_tool", "result": rows,
                       "redacted_fields": redacted}
           except Exception as e:
               return api.error_envelope("my_tool", e)
   ```

3. Install it next to odoo-mcp and opt in:

   ```bash
   pip install my-plugin
   ODOO_MCP_PLUGINS=my_plugin uvx odoo-mcp
   ```

A complete runnable example lives in
[`examples/plugin-example/`](../examples/plugin-example/).

## Stable API (v1)

| Member | Purpose |
| --- | --- |
| `api.tool` | The `@mcp.tool` decorator (same options as builtin tools) |
| `api.resolve_odoo(ctx, instance)` | `(instance_name, client)` with multi-instance routing |
| `api.redact_records(instance, model, records)` | Apply the deployment's field ACL |
| `api.error_envelope(tool_name, err)` | Standard failure envelope |
| `api.validate_model_name`, `api.clamp_limit` | Input hygiene helpers |
| `api.READ_ONLY_TOOL`, `api.PREVIEW_TOOL` | Tool annotation presets |
| `api.PLUGIN_API_VERSION` | Bumped only on breaking API changes |

## Trimming the tool surface

Independent of plugins, deployments can cut the tool list per client
(useful when a small agent drowns in 41 tools):

```bash
# keep only the read basics
ODOO_MCP_TOOLS_INCLUDE="search_records,read_record,list_models,get_model_fields,health_check"
# or drop whole groups
ODOO_MCP_TOOLS_EXCLUDE="*_across_instances,search_employee,search_holidays"
```

CSV fnmatch globs; include (when set) wins first, then exclude removes.
Removed tools are listed in `health_check.plugins.tools_filtered`.
