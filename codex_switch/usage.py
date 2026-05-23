from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, Optional


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CHATGPT_ACCOUNT_ID_CLAIM = "https://api.openai.com/auth.chatgpt_account_id"


class UsageError(Exception):
    """Usage probing failed without exposing auth material."""


@dataclass(frozen=True)
class UsageSnapshot:
    status: str
    used_percent: Optional[int]
    remaining_percent: Optional[int]
    window_label: Optional[str]
    reset_at: Optional[datetime]
    error: Optional[str] = None
    updated_auth: Optional[Dict[str, Any]] = None


def fetch_usage(auth: Dict[str, Any], timeout: int = 20) -> UsageSnapshot:
    try:
        payload = _request_usage(auth, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            try:
                refreshed_auth = refresh_auth_tokens(auth, timeout)
                payload = _request_usage(refreshed_auth, timeout)
                return replace(parse_usage_payload(payload), updated_auth=refreshed_auth)
            except (UsageError, urllib.error.HTTPError) as refresh_exc:
                code = f" HTTP {refresh_exc.code}" if isinstance(refresh_exc, urllib.error.HTTPError) else ""
            return UsageSnapshot("unknown", None, None, None, None, f"usage token refresh failed{code}")
        if exc.code == 404:
            return UsageSnapshot("unknown", None, None, None, None, f"usage probe HTTP {exc.code}")
        raise UsageError(f"usage probe HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UsageError(f"usage probe failed: {exc.__class__.__name__}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError("usage probe returned invalid JSON") from exc

    return parse_usage_payload(payload)


def refresh_auth_tokens(auth: Dict[str, Any], timeout: int = 20) -> Dict[str, Any]:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise UsageError("auth.json does not contain tokens")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise UsageError("auth.json does not contain refresh_token")

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UsageError(f"token refresh failed: {exc.__class__.__name__}") from exc
    except json.JSONDecodeError as exc:
        raise UsageError("token refresh returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise UsageError("token refresh returned invalid data")

    updated = json.loads(json.dumps(auth))
    updated_tokens = updated.setdefault("tokens", {})
    for key in ("access_token", "refresh_token", "id_token", "account_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            updated_tokens[key] = value
    return updated


def _request_usage(auth: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    token = _access_token(auth)
    headers = {
        "Authorization": f"Bearer {token}",
        "originator": "Codex Desktop",
        "OAI-Product-Sku": "Codex",
    }
    account_id = _chatgpt_account_id(auth)
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    request = urllib.request.Request(USAGE_URL, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise UsageError("usage probe returned invalid data")
    return payload


def parse_usage_payload(payload: Dict[str, Any]) -> UsageSnapshot:
    if not isinstance(payload, dict):
        raise UsageError("usage probe returned invalid data")

    window = _selected_window(payload.get("rate_limit"))
    remaining = None
    used_percent = None
    window_label = None
    reset_at = None
    if window:
        used = _number(window.get("used_percent")) or 0
        used_percent = max(0, min(100, round(used)))
        remaining = max(0, min(100, round(100 - used)))
        window_label = _window_label(window.get("limit_window_seconds"))
        reset_at = _datetime_from_unix(window.get("reset_at"))

    rate_limit = payload.get("rate_limit") if isinstance(payload.get("rate_limit"), dict) else {}
    blocked = (
        payload.get("rate_limit_reached_type") is not None
        or rate_limit.get("limit_reached") is True
        or rate_limit.get("allowed") is False
        or remaining == 0
    )
    return UsageSnapshot(
        "unavailable" if blocked else "available",
        used_percent,
        remaining,
        window_label,
        reset_at,
    )


def _access_token(auth: Dict[str, Any]) -> str:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        raise UsageError("auth.json does not contain tokens")
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        raise UsageError("auth.json does not contain access_token")
    return token


def _chatgpt_account_id(auth: Dict[str, Any]) -> Optional[str]:
    tokens = auth.get("tokens")
    if not isinstance(tokens, dict):
        return None
    for token_name in ("access_token", "id_token"):
        token = tokens.get(token_name)
        if not isinstance(token, str):
            continue
        payload = _jwt_payload(token)
        claim = payload.get(CHATGPT_ACCOUNT_ID_CLAIM)
        if isinstance(claim, str) and claim:
            return claim
    account_id = tokens.get("account_id")
    return account_id if isinstance(account_id, str) and account_id else None


def _jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload_part = parts[1] + ("=" * ((4 - len(parts[1]) % 4) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _selected_window(rate_limit: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(rate_limit, dict):
        return None
    windows = [
        item
        for item in (rate_limit.get("primary_window"), rate_limit.get("secondary_window"))
        if isinstance(item, dict)
    ]
    windows = [item for item in windows if _number(item.get("limit_window_seconds"))]
    if not windows:
        return None
    return sorted(
        windows,
        key=lambda item: (
            _number(item.get("used_percent")) or 0,
            _number(item.get("reset_at")) or 0,
        ),
        reverse=True,
    )[0]


def _window_label(seconds: Any) -> Optional[str]:
    value = _number(seconds)
    if not value:
        return None
    seconds_int = int(value)
    if seconds_int % 604800 == 0:
        return f"{seconds_int // 604800}周"
    if seconds_int % 86400 == 0:
        return f"{seconds_int // 86400}天"
    if seconds_int % 3600 == 0:
        return f"{seconds_int // 3600}小时"
    return f"{seconds_int // 60}分钟"


def _datetime_from_unix(value: Any) -> Optional[datetime]:
    numeric = _number(value)
    if not numeric:
        return None
    return datetime.fromtimestamp(numeric).astimezone()


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None
