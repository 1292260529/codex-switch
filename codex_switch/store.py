from __future__ import annotations

import base64
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .usage import UsageError, UsageSnapshot, fetch_usage


VALID_STATUSES = {"available", "unavailable", "unknown"}
TOKEN_FIELDS = {"access_token", "refresh_token", "id_token", "OPENAI_API_KEY"}


class CodexSwitchError(Exception):
    """User-facing error."""


class AccountPool:
    def __init__(
        self,
        codex_home: Optional[Path] = None,
        now: Optional[datetime] = None,
        usage_fetcher: Optional[Callable[[Dict[str, Any]], UsageSnapshot]] = None,
    ) -> None:
        self.codex_home = Path(codex_home or Path.home() / ".codex").expanduser()
        self.pool_dir = self.codex_home / "account-pool"
        self.accounts_dir = self.pool_dir / "accounts"
        self.backups_dir = self.pool_dir / "backups"
        self.accounts_file = self.pool_dir / "accounts.json"
        self.auth_file = self.codex_home / "auth.json"
        self.now = now or datetime.now().astimezone()
        self.usage_fetcher = usage_fetcher or fetch_usage

    def init_dirs(self) -> None:
        for path in (self.pool_dir, self.accounts_dir, self.backups_dir):
            path.mkdir(parents=True, exist_ok=True)
            self._chmod_if_needed(path, 0o700)
        if not self.accounts_file.exists():
            self._write_json_atomic(self.accounts_file, {"current": None, "accounts": []}, mode=0o600)
        else:
            self._chmod_if_needed(self.accounts_file, 0o600)

    def add_account(self, alias: Optional[str], next_refresh: Optional[str] = None, note: str = "") -> str:
        self.init_dirs()
        auth = self._read_auth(self.auth_file)
        usage_snapshot = None
        if next_refresh:
            next_refresh_date = self._parse_date(next_refresh)
        else:
            usage_snapshot = self._fetch_usage_for_add(auth)
            next_refresh_date = usage_snapshot.reset_at.date()
        alias = alias or self._email_from_auth(auth)
        self._validate_alias(alias)
        data = self._load()
        existing = self._find(data, alias)

        account_dir = self.accounts_dir / alias
        account_dir.mkdir(parents=True, exist_ok=True)
        self._chmod_if_needed(account_dir, 0o700)
        self._write_json_atomic(account_dir / "auth.json", auth, mode=0o600)

        account = existing or {
            "alias": alias,
            "last_used_at": None,
        }
        account.update(
            {
                "status": "available",
                "next_refresh_at": next_refresh_date.isoformat(),
                "last_checked_at": None,
                "usage_used_percent": None,
                "usage_remaining_percent": None,
                "usage_window": None,
                "usage_reset_at": None,
                "usage_updated_at": None,
                "usage_error": None,
                "note": note,
            }
        )
        if usage_snapshot:
            self._apply_usage_snapshot(account, usage_snapshot)
        if existing is None:
            data["accounts"].append(account)
        if data.get("current") is None:
            data["current"] = alias
        self._save(data)
        return f"{'updated' if existing else 'added'} {alias}"

    def prepare_add(self) -> str:
        self.init_dirs()
        if not self.auth_file.exists():
            return "auth.json is already absent; login with the new account, then run codex-switch add"

        data = self._load()
        current_auth = self._read_auth(self.auth_file)
        current_alias = self._match_current_auth(data)
        if current_alias:
            self._write_json_atomic(self._account_auth_path(current_alias), current_auth, mode=0o600)
            data["current"] = current_alias
            self._save(data)

        self._backup_current(current_auth)
        self.auth_file.unlink()
        if current_alias:
            return (
                f"prepared login for a new account; preserved current account {current_alias}. "
                "Login with the new account, then run codex-switch add"
            )
        return (
            "prepared login for a new account; backed up the previous auth.json. "
            "Login with the new account, then run codex-switch add"
        )

    def sync_emails(self) -> str:
        self.init_dirs()
        data = self._load()
        renamed: List[str] = []
        existing_aliases = {account["alias"] for account in data["accounts"]}

        for account in data["accounts"]:
            old_alias = account["alias"]
            auth = self._read_auth(self._account_auth_path(old_alias))
            new_alias = self._email_from_auth(auth)
            self._validate_alias(new_alias)
            if new_alias == old_alias:
                continue
            if new_alias in existing_aliases:
                raise CodexSwitchError(f"cannot rename {old_alias} to {new_alias}: account already exists")
            new_path = self._account_auth_path(new_alias).parent
            if new_path.exists():
                raise CodexSwitchError(f"cannot rename {old_alias} to {new_alias}: directory already exists")

            self._account_auth_path(old_alias).parent.rename(new_path)
            existing_aliases.remove(old_alias)
            existing_aliases.add(new_alias)
            account["alias"] = new_alias
            if data.get("current") == old_alias:
                data["current"] = new_alias
            renamed.append(f"{old_alias} -> {new_alias}")

        current_alias = self._match_current_auth(data)
        current_updated = False
        if current_alias and data.get("current") != current_alias:
            data["current"] = current_alias
            current_updated = True

        self._save(data)
        if not renamed and not current_updated:
            return "all accounts already use email aliases"
        lines = []
        if renamed:
            lines.append("renamed accounts:")
            lines.extend(renamed)
        if current_updated:
            lines.append(f"current set to {current_alias}")
        return "\n".join(lines)

    def use_account(self, alias: str, update_usage: bool = True) -> str:
        self.init_dirs()
        data = self._load()
        account = self._require(data, alias)
        target_auth = self._read_auth(self._account_auth_path(alias))
        current_auth = self._read_auth_optional(self.auth_file)
        if current_auth:
            self._backup_current(current_auth)
        self._write_auth_with_optional_rollback(target_auth, current_auth)

        data["current"] = alias
        if update_usage:
            account["last_used_at"] = self._iso_now()
        self._save(data)
        return f"switched to {alias}"

    def auto_switch(self) -> Tuple[bool, str]:
        self.init_dirs()
        original_auth = self._read_auth_optional(self.auth_file)
        data = self._load()
        if not data["accounts"]:
            raise CodexSwitchError("no accounts in pool")

        current_alias = self._match_current_auth(data) or data.get("current")
        refreshed = self._refresh_due_accounts(data["accounts"])
        refreshed += self._refresh_usage_for_accounts(data["accounts"], current_alias=current_alias)
        candidates: List[Dict[str, Any]] = []
        for account in sorted(data["accounts"], key=lambda item: (item["next_refresh_at"], item["alias"])):
            if account["alias"] != current_alias and account["status"] == "available":
                candidates.append(account)

        if not candidates:
            if original_auth:
                self._write_auth_with_rollback(original_auth, original_auth)
            self._save(data)
            return False, "no available non-current accounts\n" + self._format_accounts(data["accounts"])

        selected = sorted(candidates, key=lambda item: (item["next_refresh_at"], item["alias"]))[0]
        target_auth = self._read_auth(self._account_auth_path(selected["alias"]))
        if original_auth:
            self._backup_current(original_auth)
        self._write_auth_with_optional_rollback(target_auth, original_auth)
        selected["last_used_at"] = self._iso_now()
        data["current"] = selected["alias"]
        self._save(data)
        suffix = f" ({refreshed} account refreshes applied)" if refreshed else ""
        return True, f"switched to {selected['alias']}{suffix}"

    def list_accounts(self) -> str:
        self.init_dirs()
        data = self._load()
        if not data["accounts"]:
            return "no accounts"
        current_alias = self._match_current_auth(data) or data.get("current")
        self._refresh_usage_for_accounts(data["accounts"], current_alias=current_alias)
        self._save(data)
        lines = []
        for account in sorted(data["accounts"], key=lambda item: item["alias"]):
            marker = "*" if account["alias"] == current_alias else " "
            usage = self._format_usage(account)
            lines.append(
                f"{marker} {account['alias']:<18} "
                f"status={account['status']:<11} "
                f"usage={usage:<44} "
                f"next_refresh={account['next_refresh_at']} "
                f"last_used={account.get('last_used_at') or '-'} "
                f"note={account.get('note') or '-'}"
            )
        return "\n".join(lines)

    def total_available_percent(self) -> Optional[int]:
        self.init_dirs()
        data = self._load()
        if not data["accounts"]:
            return None
        current_alias = self._match_current_auth(data) or data.get("current")
        self._refresh_usage_for_accounts(data["accounts"], current_alias=current_alias)
        self._save(data)
        total = 0
        found = False
        for account in data["accounts"]:
            if account.get("usage_error"):
                continue
            remaining = account.get("usage_remaining_percent")
            if isinstance(remaining, (int, float)):
                total += round(remaining)
                found = True
        return total if found else None

    def mark(self, alias: str, status: str) -> str:
        if status not in VALID_STATUSES:
            raise CodexSwitchError(f"invalid status: {status}")
        self.init_dirs()
        data = self._load()
        account = self._require(data, alias)
        account["status"] = status
        account["last_checked_at"] = self._iso_now()
        self._save(data)
        return f"marked {alias} {status}"

    def refresh(self, alias: str, next_refresh: str) -> str:
        next_refresh_date = self._parse_date(next_refresh)
        self.init_dirs()
        data = self._load()
        account = self._require(data, alias)
        account["next_refresh_at"] = next_refresh_date.isoformat()
        account["last_checked_at"] = self._iso_now()
        self._save(data)
        return f"updated {alias} next_refresh_at={next_refresh_date.isoformat()}"

    def current(self) -> str:
        self.init_dirs()
        data = self._load()
        matched = self._match_current_auth(data)
        return f"current={matched or 'unmatched'} configured={data.get('current') or '-'}"

    def current_next_refresh(self) -> str:
        self.init_dirs()
        auth = self._read_auth(self.auth_file)
        snapshot = self._fetch_usage_for_add(auth)
        return snapshot.reset_at.date().isoformat()

    def _match_current_auth(self, data: Dict[str, Any]) -> Optional[str]:
        current_auth = self._read_auth_optional(self.auth_file)
        if current_auth is None:
            return None
        digest = self._auth_digest(current_auth)
        matched = None
        for account in data["accounts"]:
            try:
                if self._auth_digest(self._read_auth(self._account_auth_path(account["alias"]))) == digest:
                    matched = account["alias"]
                    break
            except CodexSwitchError:
                continue
        if matched:
            return matched

        try:
            current_email = self._email_from_auth(current_auth)
        except CodexSwitchError:
            return None
        for account in data["accounts"]:
            if account["alias"] == current_email:
                return account["alias"]
        return None

    def _refresh_due_accounts(self, accounts: Iterable[Dict[str, Any]]) -> int:
        refreshed = 0
        for account in accounts:
            if not self._is_due(account):
                continue
            account["status"] = "available"
            account["next_refresh_at"] = self._next_week(account["next_refresh_at"])
            account["last_checked_at"] = self._iso_now()
            refreshed += 1
        return refreshed

    def _refresh_usage_for_accounts(
        self,
        accounts: Iterable[Dict[str, Any]],
        current_alias: Optional[str] = None,
    ) -> int:
        refreshed = 0
        for account in accounts:
            auth_path = self._account_auth_path(account["alias"])
            try:
                snapshot = self.usage_fetcher(self._read_auth(auth_path))
            except (CodexSwitchError, UsageError) as exc:
                account["usage_error"] = str(exc)
                account["usage_updated_at"] = self._iso_now()
                account["last_checked_at"] = self._iso_now()
                continue
            self._apply_usage_snapshot(account, snapshot)
            if snapshot.updated_auth:
                self._write_json_atomic(auth_path, snapshot.updated_auth, mode=0o600)
                if account["alias"] == current_alias:
                    self._write_json_atomic(self.auth_file, snapshot.updated_auth, mode=0o600)
            refreshed += 1
        return refreshed

    def _fetch_usage_for_add(self, auth: Dict[str, Any]) -> UsageSnapshot:
        try:
            snapshot = self.usage_fetcher(auth)
        except (CodexSwitchError, UsageError) as exc:
            raise CodexSwitchError(
                f"failed to find reset date automatically: {exc}; pass --next-refresh YYYY-MM-DD"
            ) from exc
        if snapshot.updated_auth:
            self._write_json_atomic(self.auth_file, snapshot.updated_auth, mode=0o600)
        if not snapshot.reset_at:
            detail = f": {snapshot.error}" if snapshot.error else ""
            raise CodexSwitchError(
                f"failed to find reset date automatically{detail}; pass --next-refresh YYYY-MM-DD"
            )
        return snapshot

    def _apply_usage_snapshot(self, account: Dict[str, Any], snapshot: UsageSnapshot) -> None:
        account["status"] = snapshot.status
        account["usage_used_percent"] = snapshot.used_percent
        account["usage_remaining_percent"] = snapshot.remaining_percent
        account["usage_window"] = snapshot.window_label
        account["usage_reset_at"] = snapshot.reset_at.isoformat(timespec="seconds") if snapshot.reset_at else None
        account["usage_updated_at"] = self._iso_now()
        account["usage_error"] = snapshot.error
        account["last_checked_at"] = self._iso_now()
        if snapshot.reset_at:
            account["next_refresh_at"] = snapshot.reset_at.date().isoformat()

    def _backup_current(self, auth: Dict[str, Any]) -> None:
        self.init_dirs()
        stamp = self.now.strftime("%Y%m%dT%H%M%S%z")
        path = self.backups_dir / f"auth-{stamp}.json"
        suffix = 1
        while path.exists():
            path = self.backups_dir / f"auth-{stamp}-{suffix}.json"
            suffix += 1
        self._write_json_atomic(path, auth, mode=0o600)

    def _write_auth_with_rollback(self, target_auth: Dict[str, Any], rollback_auth: Dict[str, Any]) -> None:
        try:
            self._write_json_atomic(self.auth_file, target_auth, mode=0o600)
            self._read_auth(self.auth_file)
        except Exception as exc:
            self._write_json_atomic(self.auth_file, rollback_auth, mode=0o600)
            raise CodexSwitchError(f"failed to switch auth, rolled back: {exc}") from exc

    def _write_auth_with_optional_rollback(
        self,
        target_auth: Dict[str, Any],
        rollback_auth: Optional[Dict[str, Any]],
    ) -> None:
        if rollback_auth is not None:
            self._write_auth_with_rollback(target_auth, rollback_auth)
            return
        try:
            self._write_json_atomic(self.auth_file, target_auth, mode=0o600)
            self._read_auth(self.auth_file)
        except Exception as exc:
            if self.auth_file.exists():
                self.auth_file.unlink()
            raise CodexSwitchError(f"failed to switch auth: {exc}") from exc

    def _load(self) -> Dict[str, Any]:
        self.init_dirs()
        try:
            with self.accounts_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CodexSwitchError(f"invalid accounts file: {self.accounts_file}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
            raise CodexSwitchError(f"invalid accounts file: {self.accounts_file}")
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        self._write_json_atomic(self.accounts_file, data, mode=0o600)

    def _read_auth(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise CodexSwitchError(f"missing auth file: {path}")
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise CodexSwitchError(f"invalid auth json: {path}") from exc
        if not isinstance(data, dict):
            raise CodexSwitchError(f"invalid auth json: {path}")
        return data

    def _read_auth_optional(self, path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        return self._read_auth(path)

    def _write_json_atomic(self, path: Path, data: Dict[str, Any], mode: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            self._chmod_if_needed(tmp_path, mode)
            os.replace(tmp_path, path)
            self._chmod_if_needed(path, mode)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def _chmod_if_needed(self, path: Path, mode: int) -> None:
        current_mode = os.stat(path).st_mode & 0o777
        if current_mode == mode:
            return
        os.chmod(path, mode)

    def _account_auth_path(self, alias: str) -> Path:
        return self.accounts_dir / alias / "auth.json"

    def _require(self, data: Dict[str, Any], alias: str) -> Dict[str, Any]:
        account = self._find(data, alias)
        if not account:
            raise CodexSwitchError(f"unknown account: {alias}")
        if not self._account_auth_path(alias).exists():
            raise CodexSwitchError(f"missing account auth: {alias}")
        return account

    def _find(self, data: Dict[str, Any], alias: str) -> Optional[Dict[str, Any]]:
        for account in data["accounts"]:
            if account.get("alias") == alias:
                return account
        return None

    def _is_due(self, account: Dict[str, Any]) -> bool:
        return self.now.date() >= self._parse_date(account["next_refresh_at"])

    def _next_week(self, current: str) -> str:
        parsed = self._parse_date(current)
        while parsed <= self.now.date():
            parsed = parsed + timedelta(days=7)
        return parsed.isoformat()

    def _parse_date(self, value: str) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CodexSwitchError(f"invalid date, expected YYYY-MM-DD: {value}") from exc

    def _validate_alias(self, alias: str) -> None:
        if not alias or any(ch in alias for ch in "/\\:"):
            raise CodexSwitchError("alias must not be empty or contain / \\ :")

    def _email_from_auth(self, auth: Dict[str, Any]) -> str:
        tokens = auth.get("tokens")
        if not isinstance(tokens, dict):
            raise CodexSwitchError("auth.json does not contain tokens")
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise CodexSwitchError("auth.json does not contain an id_token email source")
        parts = id_token.split(".")
        if len(parts) < 2:
            raise CodexSwitchError("id_token is not a JWT")
        payload_part = parts[1] + ("=" * ((4 - len(parts[1]) % 4) % 4))
        try:
            payload = json.loads(base64.urlsafe_b64decode(payload_part.encode("ascii")))
        except (ValueError, json.JSONDecodeError) as exc:
            raise CodexSwitchError("failed to decode id_token payload") from exc
        email = payload.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise CodexSwitchError("id_token payload does not contain email")
        return email

    def _iso_now(self) -> str:
        return self.now.isoformat(timespec="seconds")

    def _auth_digest(self, auth: Dict[str, Any]) -> str:
        return json.dumps(auth, sort_keys=True, separators=(",", ":"))

    def _format_accounts(self, accounts: Iterable[Dict[str, Any]]) -> str:
        lines = []
        for account in sorted(accounts, key=lambda item: (item["next_refresh_at"], item["alias"])):
            lines.append(
                f"{account['alias']}: status={account['status']} "
                f"usage={self._format_usage(account)} "
                f"next_refresh={account['next_refresh_at']}"
            )
        return "\n".join(lines)

    def _format_usage(self, account: Dict[str, Any]) -> str:
        error = account.get("usage_error")
        if error:
            return "unknown"
        remaining = account.get("usage_remaining_percent")
        used = account.get("usage_used_percent")
        if remaining is None and used is None:
            return "-"
        window = account.get("usage_window") or "-"
        reset = account.get("usage_reset_at")
        reset_date = "-"
        if isinstance(reset, str) and reset:
            try:
                reset_date = datetime.fromisoformat(reset).date().isoformat()
            except ValueError:
                reset_date = reset[:10]
        used_text = f"{used}%" if used is not None else "-"
        remaining_text = f"{remaining}%" if remaining is not None else "-"
        return f"used={used_text} remaining={remaining_text} {window} reset={reset_date}"
