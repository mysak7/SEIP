"""
DynamoDB client and low-level query helpers for seip-mcp.

Tables
------
EVENTS_TABLE  (default: dev-security-events)
  Base:   PK=event_id (S),  SK=timestamp (N, epoch seconds)
  GSI 1:  status-index          PK=status (S),     SK=timestamp (N)   INCLUDE [message, Message, semantic_at]
  GSI 2:  analyzed_at-index     PK=item_type (S),  SK=analyzed_at (S) ALL
  GSI 3:  item_type-timestamp-index  PK=item_type (S), SK=timestamp (N)  KEYS_ONLY

PATTERNS_TABLE (default: dev-seip-patterns)
  Base:   PK=hash (S)
  GSI 1:  timeline-index  PK=pk (S, always "PATTERN"), SK=created_at (S) ALL
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

EVENTS_TABLE   = os.environ.get("DYNAMODB_TABLE",  "dev-security-events")
PATTERNS_TABLE = os.environ.get("PATTERNS_TABLE",  "dev-seip-patterns")
AWS_REGION     = os.environ.get("AWS_REGION",      "eu-central-1")

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_events   = _dynamodb.Table(EVENTS_TABLE)
_patterns = _dynamodb.Table(PATTERNS_TABLE)

DEFAULT_LIMIT = 50
MAX_LIMIT     = 200

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def iso_to_epoch(iso: str) -> int:
    """Parse an ISO-8601 string to epoch seconds (integer)."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def epoch_to_iso(epoch: int | float) -> str:
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pagination token helpers
# ---------------------------------------------------------------------------

def encode_token(last_evaluated_key: dict) -> str:
    """Encode a DynamoDB LastEvaluatedKey to a URL-safe base64 string."""
    return base64.urlsafe_b64encode(
        json.dumps(last_evaluated_key, default=str).encode()
    ).decode()


def decode_token(token: str) -> dict:
    """Decode a pagination token back to an ExclusiveStartKey dict."""
    raw = json.loads(base64.urlsafe_b64decode(token.encode()))
    # DynamoDB number attributes must be Decimal
    return _restore_decimals(raw)


def _restore_decimals(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _restore_decimals(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_restore_decimals(v) for v in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _serialise(obj: Any) -> Any:
    """Convert Decimal and bytes to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialise(v) for v in obj]
    if isinstance(obj, Decimal):
        n = float(obj)
        return int(n) if n == int(n) else n
    if isinstance(obj, (bytes, bytearray)):
        return "<binary blob>"
    return obj


def _clean(item: dict, exclude: set[str] | None = None) -> dict:
    """Serialise an item and drop specified keys (e.g. binary embeddings)."""
    out = _serialise(item)
    if exclude:
        for k in exclude:
            out.pop(k, None)
    return out


# ---------------------------------------------------------------------------
# Events queries
# ---------------------------------------------------------------------------

def query_events_by_status(
    status: str,
    start_epoch: int,
    end_epoch: int,
    limit: int = DEFAULT_LIMIT,
    next_token: str | None = None,
) -> dict:
    """
    Query status-index.
    Returns INCLUDE projection: event_id, timestamp, message, Message, semantic_at.
    """
    kwargs: dict = {
        "IndexName": "status-index",
        "KeyConditionExpression": (
            Key("status").eq(status)
            & Key("timestamp").between(start_epoch, end_epoch)
        ),
        "ScanIndexForward": False,
        "Limit": min(limit, MAX_LIMIT),
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = decode_token(next_token)

    resp = _events.query(**kwargs)
    items = [_clean(i) for i in resp.get("Items", [])]
    token = encode_token(resp["LastEvaluatedKey"]) if "LastEvaluatedKey" in resp else None
    return {"items": items, "count": len(items), "next_token": token}


def query_analyzed_events(
    start_analyzed_at: str,
    end_analyzed_at: str,
    limit: int = DEFAULT_LIMIT,
    next_token: str | None = None,
) -> dict:
    """
    Query analyzed_at-index (ALL projection), newest-first.
    Returns full event including analysis, severity, eid, host, etc.
    """
    kwargs: dict = {
        "IndexName": "analyzed_at-index",
        "KeyConditionExpression": (
            Key("item_type").eq("event")
            & Key("analyzed_at").between(start_analyzed_at, end_analyzed_at)
        ),
        "ScanIndexForward": False,
        "Limit": min(limit, MAX_LIMIT),
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = decode_token(next_token)

    resp = _events.query(**kwargs)
    items = [_clean(i) for i in resp.get("Items", [])]
    token = encode_token(resp["LastEvaluatedKey"]) if "LastEvaluatedKey" in resp else None
    return {"items": items, "count": len(items), "next_token": token}


def query_events_by_severity(
    severity: str,
    start_analyzed_at: str,
    end_analyzed_at: str,
    limit: int = DEFAULT_LIMIT,
    next_token: str | None = None,
) -> dict:
    """
    Query analyzed_at-index + FilterExpression on severity.
    Still a Query (not Scan) — DynamoDB filters post-retrieval but reads stay targeted.
    """
    kwargs: dict = {
        "IndexName": "analyzed_at-index",
        "KeyConditionExpression": (
            Key("item_type").eq("event")
            & Key("analyzed_at").between(start_analyzed_at, end_analyzed_at)
        ),
        "FilterExpression": Attr("severity").eq(severity),
        "ScanIndexForward": False,
        "Limit": min(limit, MAX_LIMIT),
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = decode_token(next_token)

    resp = _events.query(**kwargs)
    items = [_clean(i) for i in resp.get("Items", [])]
    token = encode_token(resp["LastEvaluatedKey"]) if "LastEvaluatedKey" in resp else None
    return {"items": items, "count": len(items), "next_token": token}


def query_events_by_event_code(
    event_code: int,
    start_analyzed_at: str,
    end_analyzed_at: str,
    limit: int = DEFAULT_LIMIT,
    next_token: str | None = None,
) -> dict:
    """
    Query analyzed_at-index + FilterExpression on eid (Windows Event ID).
    """
    kwargs: dict = {
        "IndexName": "analyzed_at-index",
        "KeyConditionExpression": (
            Key("item_type").eq("event")
            & Key("analyzed_at").between(start_analyzed_at, end_analyzed_at)
        ),
        "FilterExpression": Attr("eid").eq(event_code),
        "ScanIndexForward": False,
        "Limit": min(limit, MAX_LIMIT),
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = decode_token(next_token)

    resp = _events.query(**kwargs)
    items = [_clean(i) for i in resp.get("Items", [])]
    token = encode_token(resp["LastEvaluatedKey"]) if "LastEvaluatedKey" in resp else None
    return {"items": items, "count": len(items), "next_token": token}


def get_event_by_id(event_id: str, timestamp: int) -> dict | None:
    """GetItem on base table. Returns full event or None."""
    resp = _events.get_item(Key={"event_id": event_id, "timestamp": timestamp})
    item = resp.get("Item")
    return _clean(item) if item else None


# ---------------------------------------------------------------------------
# Patterns queries
# ---------------------------------------------------------------------------

def query_recent_patterns(
    since: str = "2024-01-01T00:00:00+00:00",
    until: str | None = None,
    limit: int = DEFAULT_LIMIT,
    next_token: str | None = None,
) -> dict:
    """
    Query timeline-index (pk="PATTERN"), newest-first.
    Excludes binary embedding blobs from output.
    """
    end = until or datetime.now(timezone.utc).isoformat()
    kwargs: dict = {
        "IndexName": "timeline-index",
        "KeyConditionExpression": (
            Key("pk").eq("PATTERN") & Key("created_at").between(since, end)
        ),
        "ScanIndexForward": False,
        "Limit": min(limit, MAX_LIMIT),
    }
    if next_token:
        kwargs["ExclusiveStartKey"] = decode_token(next_token)

    resp = _patterns.query(**kwargs)
    items = [_clean(i, exclude={"embedding"}) for i in resp.get("Items", [])]
    token = encode_token(resp["LastEvaluatedKey"]) if "LastEvaluatedKey" in resp else None
    return {"items": items, "count": len(items), "next_token": token}


def query_pattern_by_id(pattern_id: int) -> dict | None:
    """
    Query timeline-index + FilterExpression on pattern_id (numeric).
    Returns the first match or None.
    """
    resp = _patterns.query(
        IndexName="timeline-index",
        KeyConditionExpression=Key("pk").eq("PATTERN"),
        FilterExpression=Attr("pattern_id").eq(pattern_id),
        Limit=MAX_LIMIT,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return _clean(items[0], exclude={"embedding"})


def get_pattern_by_hash(hash_value: str) -> dict | None:
    """GetItem on patterns table by SHA-256 hash. Returns full pattern or None."""
    resp = _patterns.get_item(Key={"hash": hash_value})
    item = resp.get("Item")
    return _clean(item, exclude={"embedding"}) if item else None


def get_pipeline_stats() -> dict | None:
    """
    Fetch cumulative pipeline stats from the __pipeline_stats counter item
    in the patterns table (written by seip-deep-mind).
    """
    resp = _patterns.get_item(
        Key={"hash": "__pipeline_stats"},
        ProjectionExpression="total_processed, exact_hits, semantic_hits, "
                             "semantic_rejected, llm_ok, llm_errors",
    )
    item = resp.get("Item")
    if not item:
        return None
    stats = _clean(item)
    total = stats.get("total_processed", 0) or 0
    hits  = (stats.get("exact_hits", 0) or 0) + (stats.get("semantic_hits", 0) or 0)
    stats["cache_hit_rate_pct"] = round(hits / total * 100, 1) if total > 0 else 0.0
    return stats
