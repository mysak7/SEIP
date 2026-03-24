"""
seip-mcp — Model Context Protocol server for SEIP security event logs.

Transports:
  stdio  — for local Claude Code / Claude Desktop (default)
  http   — for Docker/EC2 deployment, connect via SSH port-forward

All tools issue targeted DynamoDB Query or GetItem operations — no Scan.
Pagination is handled via opaque next_token strings (base64-encoded ExclusiveStartKey).

Usage:
  python server.py                  # stdio transport
  python server.py --http [PORT]    # HTTP transport (default port 8765)
  MCP_TRANSPORT=http python server.py  # same, via env var
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

import dynamodb as db

mcp = FastMCP(
    "seip-mcp",
    instructions=(
        "Security Event Intelligence Platform MCP server. "
        "Query Windows security event logs and LLM-generated analysis stored in DynamoDB. "
        "All queries are targeted (no table scans). "
        "Use next_token to paginate through large result sets. "
        "Timestamps follow ISO 8601 (e.g. 2026-03-24T07:00:00Z)."
    ),
)

_NOW = lambda: datetime.now(timezone.utc).isoformat()
_DAY_AGO = lambda: datetime.now(timezone.utc).replace(
    hour=0, minute=0, second=0, microsecond=0
).isoformat()


# ---------------------------------------------------------------------------
# Tool 1 — events by processing status
# ---------------------------------------------------------------------------

@mcp.tool()
def get_events_by_status(
    status: str,
    start_time: str,
    end_time: str,
    limit: int = 50,
    next_token: str | None = None,
) -> dict:
    """
    Retrieve security events by pipeline processing status within a time window.

    status      : "pending" (not yet analyzed), "analyzed", or "error"
    start_time  : ISO 8601 timestamp (e.g. "2026-03-24T00:00:00Z")
    end_time    : ISO 8601 timestamp
    limit       : Max events to return (1–200, default 50)
    next_token  : Pagination cursor from a previous call

    Returns event_id, timestamp, message excerpt, and semantic_at for each event.
    Use this tool to monitor pipeline health or find unprocessed events.

    DynamoDB: Query on status-index (PK=status, SK=timestamp range).
    """
    start_epoch = db.iso_to_epoch(start_time)
    end_epoch   = db.iso_to_epoch(end_time)
    result = db.query_events_by_status(status, start_epoch, end_epoch, limit, next_token)
    # Add human-readable timestamp to each item
    for item in result["items"]:
        if "timestamp" in item:
            item["timestamp_iso"] = db.epoch_to_iso(item["timestamp"])
    return result


# ---------------------------------------------------------------------------
# Tool 2 — analyzed events (full detail, sorted by analysis time)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_analyzed_events(
    start_time: str,
    end_time: str,
    limit: int = 50,
    next_token: str | None = None,
) -> dict:
    """
    Retrieve fully analyzed security events sorted by when they were analyzed (newest first).

    start_time  : ISO 8601 lower bound for analyzed_at
    end_time    : ISO 8601 upper bound for analyzed_at
    limit       : Max events to return (1–200, default 50)
    next_token  : Pagination cursor from a previous call

    Returns full event data including: eid (Windows Event ID), host, severity (1–10),
    analysis (LLM text), fp_source (exact/semantic/llm), matched_pattern_id, model_id.

    DynamoDB: Query on analyzed_at-index (ALL projection, PK=item_type="event").
    """
    result = db.query_analyzed_events(start_time, end_time, limit, next_token)
    return result


# ---------------------------------------------------------------------------
# Tool 3 — events filtered by severity level
# ---------------------------------------------------------------------------

@mcp.tool()
def get_events_by_severity(
    severity: int,
    start_time: str,
    end_time: str,
    limit: int = 50,
    next_token: str | None = None,
) -> dict:
    """
    Hunt for security events at a specific severity level within a time window.

    severity    : Integer 1–10 (1=informational, 6=medium, 8=high, 10=critical)
    start_time  : ISO 8601 lower bound for analyzed_at
    end_time    : ISO 8601 upper bound for analyzed_at
    limit       : Max events to return (1–200, default 50)
    next_token  : Pagination cursor from a previous call

    Returns full analyzed event including LLM analysis text and host details.
    Useful for: threat hunting, escalation, finding HIGH or CRITICAL alerts.

    DynamoDB: Query on analyzed_at-index + server-side FilterExpression on severity.
    Note: Limit applies before filter — increase limit if results are sparse.
    """
    result = db.query_events_by_severity(str(severity), start_time, end_time, limit, next_token)
    return result


# ---------------------------------------------------------------------------
# Tool 4 — events filtered by Windows Event ID (eid)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_events_by_event_code(
    event_code: int,
    start_time: str,
    end_time: str,
    limit: int = 50,
    next_token: str | None = None,
) -> dict:
    """
    Find security events with a specific Windows Event ID within a time window.

    event_code  : Windows Event ID integer, e.g.:
                    1    = Sysmon Process Create
                    4624 = Logon Success
                    4648 = Explicit Credential Logon
                    4673 = Privileged Service Called
                    4688 = Process Creation (Security log)
    start_time  : ISO 8601 lower bound for analyzed_at
    end_time    : ISO 8601 upper bound for analyzed_at
    limit       : Max events to return (1–200, default 50)
    next_token  : Pagination cursor from a previous call

    Returns full analyzed event data including LLM analysis.

    DynamoDB: Query on analyzed_at-index + server-side FilterExpression on eid.
    Note: Limit applies before filter — increase limit if results are sparse.
    """
    result = db.query_events_by_event_code(event_code, start_time, end_time, limit, next_token)
    return result


# ---------------------------------------------------------------------------
# Tool 5 — single event by primary key
# ---------------------------------------------------------------------------

@mcp.tool()
def get_event_by_id(
    event_id: str,
    timestamp: int,
) -> dict:
    """
    Retrieve a single security event by its primary key.

    event_id    : UUID string (from event_id field)
    timestamp   : Epoch seconds integer (from timestamp field)

    Returns the complete event record including raw message and LLM analysis.
    Use this for deep-dive investigation after finding an event_id in another query.

    DynamoDB: GetItem on base table (exact key lookup, most efficient operation).
    """
    item = db.get_event_by_id(event_id, timestamp)
    if item is None:
        return {"error": f"Event not found: event_id={event_id} timestamp={timestamp}"}
    if "timestamp" in item:
        item["timestamp_iso"] = db.epoch_to_iso(item["timestamp"])
    return item


# ---------------------------------------------------------------------------
# Tool 6 — recent detected patterns
# ---------------------------------------------------------------------------

@mcp.tool()
def get_recent_patterns(
    since: str = "2026-01-01T00:00:00Z",
    until: str | None = None,
    limit: int = 50,
    next_token: str | None = None,
) -> dict:
    """
    Retrieve recently learned security patterns (newest first).

    since       : ISO 8601 lower bound for created_at (default: 2026-01-01)
    until       : ISO 8601 upper bound for created_at (default: now)
    limit       : Max patterns to return (1–200, default 50)
    next_token  : Pagination cursor from a previous call

    Returns: pattern_id, title, severity, hit_count, model_id, created_at,
             last_used_at, analysis_preview (full LLM analysis text), key_entities.
    Binary embedding vectors are excluded.

    DynamoDB: Query on timeline-index (PK=pk="PATTERN", SK=created_at range).
    """
    result = db.query_recent_patterns(since=since, until=until, limit=limit, next_token=next_token)
    return result


# ---------------------------------------------------------------------------
# Tool 7 — pattern details by numeric ID
# ---------------------------------------------------------------------------

@mcp.tool()
def get_pattern_by_id(pattern_id: int) -> dict:
    """
    Get full details of a security pattern by its numeric pattern ID.

    pattern_id  : Integer pattern ID (seen as matched_pattern_id in event records)

    Returns complete pattern analysis including: title, severity, key_entities,
    hit_count, model_id, full LLM analysis text, created_at, last_used_at.

    Use this when you see a matched_pattern_id in an event and want to understand
    what recurring attack pattern or behaviour it represents.

    DynamoDB: Query on timeline-index + FilterExpression on pattern_id.
    """
    item = db.query_pattern_by_id(pattern_id)
    if item is None:
        return {"error": f"Pattern not found: pattern_id={pattern_id}"}
    return item


# ---------------------------------------------------------------------------
# Tool 8 — pattern by SHA-256 hash
# ---------------------------------------------------------------------------

@mcp.tool()
def get_pattern_by_hash(hash_value: str) -> dict:
    """
    Get a security pattern by its SHA-256 fingerprint hash.

    hash_value  : 64-character hex SHA-256 hash of the normalised event message

    Returns complete pattern record (same fields as get_pattern_by_id).
    Use this when you have a hash value from an event's fp_hash field.

    DynamoDB: GetItem on patterns table (exact PK lookup).
    """
    item = db.get_pattern_by_hash(hash_value)
    if item is None:
        return {"error": f"Pattern not found: hash={hash_value}"}
    return item


# ---------------------------------------------------------------------------
# Tool 9 — pipeline health stats
# ---------------------------------------------------------------------------

@mcp.tool()
def get_pipeline_stats() -> dict:
    """
    Get cumulative processing statistics for the seip-deep-mind analysis pipeline.

    Returns:
      total_processed    : Total events processed since last reset
      exact_hits         : Events resolved by exact SHA-256 cache match (no LLM call)
      semantic_hits      : Events resolved by semantic similarity match (no LLM call)
      semantic_rejected  : Semantic matches rejected due to missing key entities
      llm_ok             : Fresh LLM analyses performed
      llm_errors         : Failed LLM calls
      cache_hit_rate_pct : (exact + semantic) / total * 100

    DynamoDB: GetItem for __pipeline_stats counter in patterns table.
    """
    stats = db.get_pipeline_stats()
    if stats is None:
        return {"error": "Pipeline stats not found — deep-mind may not have run yet."}
    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    use_http = (
        (len(sys.argv) > 1 and sys.argv[1] == "--http")
        or os.environ.get("MCP_TRANSPORT", "stdio") == "http"
    )
    if use_http:
        port = int(
            sys.argv[2] if len(sys.argv) > 2
            else os.environ.get("MCP_PORT", "8765")
        )
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")
