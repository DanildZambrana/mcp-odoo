# Agent Skills for odoo-mcp

Business-workflow playbooks that pair with the odoo-mcp server — the
[MCP + Skills hybrid](https://github.com/tuanle96/mcp-odoo#readme): MCP
provides the safe tool layer (gated writes, field ACL, bounded reads),
these skills provide the judgment layer (pacing, evidence rules, human
checkpoints). They follow the open
[Agent Skills](https://agentskills.io) format (`SKILL.md` with YAML
frontmatter) supported by Claude Code, Codex, Cursor, Gemini CLI, and
other skills-compatible agents.

| Skill | What it drives | Key odoo-mcp tools |
| --- | --- | --- |
| [odoo-data-quality-gate](odoo-data-quality-gate/SKILL.md) | Evidence-first data audit + gated remediation | `data_quality_report`, `diagnose_access`, write gate |
| [odoo-migration-copilot](odoo-migration-copilot/SKILL.md) | Version-upgrade worklist (16→19/20), log triage, JSON-2 prep | `scan_addons_source`, `analyze_upgrade_log`, `upgrade_risk_report`, `lookup_model_history`, `generate_json2_payload` |
| [odoo-month-end-close](odoo-month-end-close/SKILL.md) | Month-end close with human sign-off per posting | `accounting_health_summary`, `receivable_payable_aging`, `aggregate_records`, write gate, `chatter_post` |
| [odoo-agency-fleet-review](odoo-agency-fleet-review/SKILL.md) | Multi-client fleet status for agencies/partners | `list_instances`, `*_across_instances`, async tasks |

## Install

**Claude Code** — copy the skill folders into your project or user skills
directory:

```bash
git clone https://github.com/tuanle96/mcp-odoo
cp -r mcp-odoo/skills/odoo-* ~/.claude/skills/
```

Then make sure the odoo-mcp server itself is connected
(`uvx odoo-mcp --setup` prints the snippet). Invoke naturally ("check data
quality before our migration") or explicitly (`/odoo-data-quality-gate`).

**Other skills-compatible clients** — point the client's skills directory
at the same folders; each skill is a self-contained `SKILL.md`.

## Design rules these skills follow

- Every number shown to the human comes from a tool result — no guessed
  figures.
- Writes only through `preview_write` → `validate_write` →
  `execute_approved_write`, one approved batch at a time.
- `redacted_fields` and cross-instance opt-outs are policy, never errors
  to work around.

Want a skill for your vertical? They're plain Markdown — PRs welcome
(see [CONTRIBUTING.md](../CONTRIBUTING.md)), or ship your own alongside a
[tool plugin](../docs/plugins.md).
