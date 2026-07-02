"""Reads/writes for the monitoring tables (generation_runs, api_calls).

Kept separate from the device/account repo. All SQL is parameterized. api_calls
is high-churn, so inserts opportunistically prune old rows to bound the table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .db import get_connection

_API_CALLS_KEEP = 20_000          # hard cap on retained api_calls rows
_PRUNE_EVERY = 200                # prune roughly once per this many inserts
_insert_count = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Generation runs
# --------------------------------------------------------------------------- #
def record_generation_run(**f: object) -> None:
    cols = ("device_id", "account_id", "date", "trigger", "ok", "duration_ms",
            "retries", "image_calls", "text_calls", "search_calls", "text_tokens",
            "cost_usd", "provider", "phase", "error",
            "image_file", "event_caption", "image_prompt")
    values = [f.get(c) for c in cols]
    placeholders = ", ".join("?" for _ in cols) + ", ?"
    with get_connection() as conn:
        conn.execute(
            f"INSERT INTO generation_runs ({', '.join(cols)}, created_at) "
            f"VALUES ({placeholders})",
            values + [_now()],
        )


# Cap on how many day-rows a chart series returns (a year of daily bars).
_MAX_DAYS = 366


def _date_conds(col: str, start: str | None, end: str | None) -> tuple[list, list]:
    """Inclusive date-window conditions comparing the YYYY-MM-DD prefix of an ISO
    timestamp column. Dates are UTC, matching how timestamps are stored."""
    conds, params = [], []
    if start:
        conds.append(f"substr({col}, 1, 10) >= ?"); params.append(start)
    if end:
        conds.append(f"substr({col}, 1, 10) <= ?"); params.append(end)
    return conds, params


def _gen_conds(start, end, device_id, account_id) -> tuple[list, list]:
    conds, params = _date_conds("created_at", start, end)
    if device_id:
        conds.append("device_id = ?"); params.append(device_id)
    if account_id:
        conds.append("account_id = ?"); params.append(account_id)
    return conds, params


def _test_cond(test, test_account_ids, test_device_ids, has_account: bool) -> tuple[list, list]:
    """Condition restricting rows to test (test=True) or real (test=False) traffic.
    A row is 'test' when its device or account is flagged. Uses a CASE so a NULL
    account_id can't three-value the row out. test=None adds no condition."""
    if test is None:
        return [], []
    accts = list(test_account_ids or [])
    devs = list(test_device_ids or [])
    whens, params = [], []
    if devs:
        whens.append(f"device_id IN ({','.join('?' * len(devs))})"); params += devs
    if has_account and accts:
        whens.append(f"account_id IN ({','.join('?' * len(accts))})"); params += accts
    expr = f"(CASE WHEN {' OR '.join(whens)} THEN 1 ELSE 0 END)" if whens else "0"
    return [f"{expr} = {1 if test else 0}"], params


def list_generation_runs(limit: int = 100, device_id: str | None = None,
                         only_failed: bool = False, start: str | None = None,
                         end: str | None = None, account_id: str | None = None,
                         test=None, test_account_ids=None, test_device_ids=None) -> list[dict]:
    conds, params = _gen_conds(start, end, device_id, account_id)
    if only_failed:
        conds.append("ok = 0")
    tc, tp = _test_cond(test, test_account_ids, test_device_ids, has_account=True)
    conds += tc; params += tp
    clause = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM generation_runs {clause} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


def generation_stats(start: str | None = None, end: str | None = None,
                     device_id: str | None = None, account_id: str | None = None,
                     test=None, test_account_ids=None, test_device_ids=None) -> dict:
    """Totals + per-day series over the given date window (all-time if unset).
    Both the totals and the series honor the window, so they never disagree."""
    conds, params = _gen_conds(start, end, device_id, account_id)
    tc, tp = _test_cond(test, test_account_ids, test_device_ids, has_account=True)
    conds += tc; params += tp
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_connection() as conn:
        totals = conn.execute(
            f"""SELECT COUNT(*) AS runs, SUM(ok) AS ok, SUM(cost_usd) AS cost,
                       SUM(retries) AS retries, AVG(duration_ms) AS avg_ms,
                       SUM(image_calls) AS images, SUM(text_calls) AS texts,
                       SUM(search_calls) AS searches, SUM(text_tokens) AS tokens
                FROM generation_runs {where}""",
            params,
        ).fetchone()
        by_day = conn.execute(
            f"""SELECT substr(created_at, 1, 10) AS day,
                       COUNT(*) AS runs, SUM(ok) AS ok, SUM(cost_usd) AS cost
                FROM generation_runs {where}
                GROUP BY day ORDER BY day DESC LIMIT ?""",
            params + [_MAX_DAYS],
        ).fetchall()
    return {"totals": dict(totals), "by_day": [dict(r) for r in by_day][::-1]}


# --------------------------------------------------------------------------- #
# API calls
# --------------------------------------------------------------------------- #
def record_api_call(method: str, path: str, kind: str, device_id: str | None,
                    status: int, ms: int) -> None:
    global _insert_count
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO api_calls (ts, method, path, kind, device_id, status, ms)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (_now(), method, path, kind, device_id, status, ms),
        )
        _insert_count += 1
        if _insert_count % _PRUNE_EVERY == 0:
            conn.execute(
                """DELETE FROM api_calls WHERE id <= (
                       SELECT MAX(id) - ? FROM api_calls)""",
                (_API_CALLS_KEEP,),
            )


def list_api_calls(limit: int = 200, start: str | None = None,
                   end: str | None = None, device_id: str | None = None,
                   test=None, test_device_ids=None) -> list[dict]:
    conds, params = _date_conds("ts", start, end)
    if device_id:
        conds.append("device_id = ?"); params.append(device_id)
    tc, tp = _test_cond(test, None, test_device_ids, has_account=False)
    conds += tc; params += tp
    clause = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM api_calls {clause} ORDER BY id DESC LIMIT ?", params + [limit]
        ).fetchall()
        return [dict(r) for r in rows]


def api_call_stats(start: str | None = None, end: str | None = None,
                   device_id: str | None = None, test=None, test_device_ids=None) -> dict:
    conds, params = _date_conds("ts", start, end)
    if device_id:
        conds.append("device_id = ?"); params.append(device_id)
    tc, tp = _test_cond(test, None, test_device_ids, has_account=False)
    conds += tc; params += tp
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_connection() as conn:
        totals = conn.execute(
            f"""SELECT COUNT(*) AS calls,
                       SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors,
                       AVG(ms) AS avg_ms
                FROM api_calls {where}""",
            params,
        ).fetchone()
        by_day = conn.execute(
            f"""SELECT substr(ts, 1, 10) AS day, COUNT(*) AS calls,
                       SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) AS errors
                FROM api_calls {where} GROUP BY day ORDER BY day DESC LIMIT ?""",
            params + [_MAX_DAYS],
        ).fetchall()
        by_kind = conn.execute(
            f"""SELECT kind, COUNT(*) AS calls FROM api_calls {where}
                GROUP BY kind ORDER BY calls DESC""",
            params,
        ).fetchall()
    return {
        "totals": dict(totals),
        "by_day": [dict(r) for r in by_day][::-1],
        "by_kind": [dict(r) for r in by_kind],
    }
