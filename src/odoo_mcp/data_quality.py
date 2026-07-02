"""Data-quality checks over live Odoo records (read-only).

Dirty data is the #1 killer of ERP AI projects and the hidden cost of every
migration, so the checks are evidence-first: every reported issue carries the
record ids / values that triggered it, and remediation is *described*, never
executed — writes stay behind the gated workflow.

Core module (no MCP surface imports). RPC budget is bounded: each check runs a
handful of aggregate/count calls plus at most one ``sample_limit`` fetch, and
every check fails independently (one broken field never kills the report).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from .field_policy import get_field_policy

ALL_CHECKS = (
    "duplicates",
    "missing_required",
    "orphaned_references",
    "format_anomalies",
)

# Identifier-ish fields worth a duplicate scan when the caller doesn't pick.
DEFAULT_KEY_FIELDS = (
    "email",
    "vat",
    "ref",
    "default_code",
    "barcode",
    "login",
    "name",
)

MAX_KEY_FIELDS = 3
MAX_REQUIRED_FIELDS = 10
MAX_RELATION_FIELDS = 5
MAX_EVIDENCE = 10
MAX_REFERENCED_IDS = 1000

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_ALLOWED_RE = re.compile(r"^[0-9+\-().\s/]{6,}$")

SYSTEM_FIELDS = {"id", "create_uid", "write_uid", "create_date", "write_date"}


def _group_count(row: Dict[str, Any], key: str) -> int:
    """read_group count key differs across versions; accept both spellings."""
    for candidate in ("__count", f"{key}_count"):
        value = row.get(candidate)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _m2o_id(value: Any) -> Optional[int]:
    """search_read renders many2one as [id, display]; JSON-2 may return int."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int) and value > 0:
        return value
    return None


def _check_duplicates(
    odoo: Any, model: str, fields_meta: Dict[str, Any], key_fields: List[str]
) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    duplicate_records = 0
    keys_checked: List[str] = []
    for key in key_fields:
        keys_checked.append(key)
        rows = odoo.execute_method(
            model,
            "read_group",
            [[key, "!=", False]],
            [key],
            [key],
        )
        groups = [
            {"field": key, "value": row.get(key), "count": _group_count(row, key)}
            for row in rows or []
            if _group_count(row, key) > 1
        ]
        groups.sort(key=lambda item: -item["count"])
        duplicate_records += sum(item["count"] - 1 for item in groups)
        evidence.extend(groups[:MAX_EVIDENCE])
    return {
        "check": "duplicates",
        "ok": duplicate_records == 0,
        "issue_count": duplicate_records,
        "fields_checked": keys_checked,
        "evidence": evidence[:MAX_EVIDENCE],
        "suggestion": (
            "Merge or archive the duplicated records before trusting AI answers "
            "or migrating; deduplicate on the listed key values first."
        ),
    }


def _check_missing_required(
    odoo: Any, model: str, fields_meta: Dict[str, Any], key_fields: List[str]
) -> Dict[str, Any]:
    required = [
        name
        for name, meta in fields_meta.items()
        if isinstance(meta, dict)
        and meta.get("required")
        and meta.get("store", True)
        and meta.get("type") not in ("one2many", "many2many")
        and name not in SYSTEM_FIELDS
    ][:MAX_REQUIRED_FIELDS]
    evidence = []
    total = 0
    for field in required:
        count = odoo.execute_method(model, "search_count", [[field, "=", False]])
        if isinstance(count, int) and count > 0:
            total += count
            evidence.append({"field": field, "records_missing_value": count})
    return {
        "check": "missing_required",
        "ok": total == 0,
        "issue_count": total,
        "fields_checked": required,
        "evidence": evidence[:MAX_EVIDENCE],
        "suggestion": (
            "Required fields with empty values usually predate a constraint or "
            "were imported raw; fill or archive them — target-version installs "
            "may enforce the constraint harder."
        ),
    }


def _check_orphaned_references(
    odoo: Any, model: str, fields_meta: Dict[str, Any], key_fields: List[str],
    sample_limit: int = 500,
) -> Dict[str, Any]:
    relations = [
        (name, meta.get("relation"))
        for name, meta in fields_meta.items()
        if isinstance(meta, dict)
        and meta.get("type") == "many2one"
        and meta.get("store", True)
        and meta.get("relation")
        and name not in SYSTEM_FIELDS
    ]
    # Required relations break hardest when dangling — check them first.
    relations.sort(
        key=lambda item: not fields_meta.get(item[0], {}).get("required", False)
    )
    relations = relations[:MAX_RELATION_FIELDS]

    evidence: List[Dict[str, Any]] = []
    total = 0
    fields_checked: List[str] = []
    for field, target in relations:
        fields_checked.append(field)
        rows = odoo.search_read(
            model_name=model,
            domain=[[field, "!=", False]],
            fields=["id", field],
            offset=0,
            limit=sample_limit,
            order=None,
        )
        referenced: Dict[int, List[int]] = {}
        for row in rows or []:
            target_id = _m2o_id(row.get(field))
            if target_id is not None:
                referenced.setdefault(target_id, []).append(row.get("id"))
        ids = list(referenced)[:MAX_REFERENCED_IDS]
        if not ids:
            continue
        existing = odoo.execute_method(target, "search", [["id", "in", ids]])
        missing = set(ids) - {int(x) for x in (existing or [])}
        for target_id in list(missing)[:MAX_EVIDENCE]:
            evidence.append(
                {
                    "field": field,
                    "target_model": target,
                    "missing_target_id": target_id,
                    "referencing_record_ids": referenced[target_id][:5],
                }
            )
        total += sum(len(referenced[t]) for t in missing)
    return {
        "check": "orphaned_references",
        "ok": total == 0,
        "issue_count": total,
        "fields_checked": fields_checked,
        "evidence": evidence[:MAX_EVIDENCE],
        "suggestion": (
            "A missing target either means a dangling reference (fix before "
            "migration) or a record your user cannot read (ACL/record rule) — "
            "confirm with diagnose_access before deleting anything."
        ),
    }


def _check_format_anomalies(
    odoo: Any, model: str, fields_meta: Dict[str, Any], key_fields: List[str],
    sample_limit: int = 500,
) -> Dict[str, Any]:
    validators: Dict[str, Callable[[str], bool]] = {
        "email": lambda v: bool(EMAIL_RE.match(v)),
        "email_from": lambda v: bool(EMAIL_RE.match(v)),
        "phone": lambda v: bool(PHONE_ALLOWED_RE.match(v)),
        "mobile": lambda v: bool(PHONE_ALLOWED_RE.match(v)),
        "vat": lambda v: len(re.sub(r"[\s.-]", "", v)) >= 8,
    }
    candidates = [name for name in validators if name in fields_meta]
    if not candidates:
        return {
            "check": "format_anomalies",
            "ok": True,
            "issue_count": 0,
            "fields_checked": [],
            "evidence": [],
            "suggestion": "No email/phone/vat-like fields on this model.",
        }
    rows = odoo.search_read(
        model_name=model,
        domain=["|"] * (len(candidates) - 1)
        + [[name, "!=", False] for name in candidates],
        fields=["id"] + candidates,
        offset=0,
        limit=sample_limit,
        order=None,
    )
    evidence: List[Dict[str, Any]] = []
    total = 0
    for row in rows or []:
        for name in candidates:
            value = row.get(name)
            if isinstance(value, str) and value.strip():
                if not validators[name](value.strip()):
                    total += 1
                    if len(evidence) < MAX_EVIDENCE:
                        evidence.append(
                            {"id": row.get("id"), "field": name, "value": value}
                        )
    return {
        "check": "format_anomalies",
        "ok": total == 0,
        "issue_count": total,
        "fields_checked": candidates,
        "evidence": evidence,
        "suggestion": (
            "Heuristic format checks (broad on purpose): normalize these values "
            "before dedup/migration — bad emails also break mailing features."
        ),
        "sampled_records": len(rows or []),
    }


_CHECK_BUILDERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "duplicates": _check_duplicates,
    "missing_required": _check_missing_required,
    "orphaned_references": _check_orphaned_references,
    "format_anomalies": _check_format_anomalies,
}


def build_data_quality_report(
    odoo: Any,
    instance_name: str,
    model: str,
    checks: Optional[List[str]] = None,
    key_fields: Optional[List[str]] = None,
    sample_limit: int = 500,
) -> Dict[str, Any]:
    """Run the selected read-only data-quality checks against one model."""
    selected = list(checks) if checks else list(ALL_CHECKS)
    unknown = [name for name in selected if name not in _CHECK_BUILDERS]
    if unknown:
        raise ValueError(
            f"Unknown checks {unknown}; available: {', '.join(ALL_CHECKS)}"
        )

    fields_meta = odoo.get_model_fields(model)
    if not isinstance(fields_meta, dict) or "error" in fields_meta:
        raise ValueError(
            f"Could not read fields for {model}: "
            f"{fields_meta.get('error') if isinstance(fields_meta, dict) else fields_meta}"
        )

    # Field ACL is the ceiling for every check: denied fields are neither
    # scanned nor surfaced in evidence.
    policy = get_field_policy()
    restricted = set(
        policy.restricted_fields(instance_name, model, list(fields_meta))
    )
    if restricted:
        fields_meta = {
            name: meta
            for name, meta in fields_meta.items()
            if name not in restricted
        }

    if key_fields:
        keys = [name for name in key_fields if name in fields_meta]
    else:
        keys = [name for name in DEFAULT_KEY_FIELDS if name in fields_meta][
            :MAX_KEY_FIELDS
        ]

    results: List[Dict[str, Any]] = []
    for name in selected:
        builder = _CHECK_BUILDERS[name]
        try:
            if name in ("orphaned_references", "format_anomalies"):
                result = builder(
                    odoo, model, fields_meta, keys, sample_limit=sample_limit
                )
            else:
                result = builder(odoo, model, fields_meta, keys)
        except Exception as exc:  # noqa: BLE001 — checks fail independently
            result = {
                "check": name,
                "ok": False,
                "error": str(exc),
                "issue_count": None,
            }
        results.append(result)

    issue_total = sum(
        r["issue_count"] for r in results if isinstance(r.get("issue_count"), int)
    )
    failed = [r["check"] for r in results if r.get("error")]
    dirty = [r["check"] for r in results if not r.get("ok") and not r.get("error")]
    return {
        "success": True,
        "tool": "data_quality_report",
        "model": model,
        "instance": instance_name,
        "sample_limit": sample_limit,
        "checks_run": selected,
        "skipped_restricted_fields": sorted(restricted),
        "results": results,
        "summary": {
            "total_issues": issue_total,
            "checks_with_issues": dirty,
            "checks_errored": failed,
            "clean": not dirty and not failed,
        },
    }
