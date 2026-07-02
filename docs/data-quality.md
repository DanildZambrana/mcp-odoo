# Data quality & the migration workbench

Dirty data is the most common reason ERP AI pilots fail and migrations slip.
odoo-mcp ships a read-only data-quality pack plus an upgrade-log analyzer so
an agent can *find* the problems with evidence — and route every fix through
the gated write workflow.

## `data_quality_report`

```json
{ "model": "res.partner", "checks": ["duplicates", "format_anomalies"] }
```

Checks (all read-only, each fails independently):

| Check | What it finds | How |
| --- | --- | --- |
| `duplicates` | Records sharing identifier values (email, vat, ref, default_code, barcode, login, name — or your `key_fields`) | server-side `read_group` per key, groups with count > 1 |
| `missing_required` | Required stored fields with empty values (legacy/imported rows) | `search_count` per required field (capped at 10 fields) |
| `orphaned_references` | many2one values pointing at missing — or unreadable — targets | samples up to `sample_limit` rows, probes target existence |
| `format_anomalies` | Malformed email/phone/vat values | regex heuristics over a sampled slice |

Every issue carries evidence (record ids, values, counts) plus a suggestion.
The report never changes data; remediation goes through
`preview_write` → `validate_write` → `execute_approved_write`.

Notes:
- **Field ACL is the ceiling**: denied fields are neither scanned nor shown;
  the report lists them under `skipped_restricted_fields`.
- `orphaned_references` honestly cannot distinguish a dangling reference from
  a record your user is not allowed to read — confirm with `diagnose_access`
  before deleting anything.
- Large models: run in the background —
  `submit_async_task(operation="data_quality_report", params={"model": ...})`.
- `sample_limit` defaults to 500 (cap 2000) for the sampled checks.

## `analyze_upgrade_log`

Paste the failing slice of an Odoo install/update/upgrade log (up to ~1 MB);
the tool classifies known failure patterns into an OpenUpgrade-style
worklist with per-finding suggestions:

- `needs_script` — code/data must change: xpath no longer matching the parent
  view, missing fields/models/external ids, NOT NULL violations, missing
  dependencies, Odoo 17 `attrs` removal, ORM signature changes.
- `needs_review` — human judgment: access errors, deprecation warnings.
- `no_action` — informational.

Input-driven: it never contacts Odoo, so you can use it on logs from any
environment. Findings are deduplicated and line-numbered.

## Action worklist on existing tools

`scan_addons_source` findings and `upgrade_risk_report` risks now carry the
same `action` field (`no_action` / `needs_review` / `needs_script`) and an
`actions` summary, so a consultant can triage straight from the report.

## The workflow prompt

The `pre_migration_data_quality` prompt chains all of this per model:
data-quality report (async for big DBs) → evidence review with the human →
`diagnose_access` confirmation for unreachable references → a remediation
plan where every write is gated and batch-approved → merged with
`analyze_upgrade_log` findings when logs exist.
