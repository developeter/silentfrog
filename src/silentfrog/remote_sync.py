from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

_MANIFEST_VERSION = 1
_DISCLOSURE = (
    "Remote sync is opt-in. The listed files may contain crawl data, exports, "
    "or report history and will be transferred only after explicit user confirmation."
)


class RemoteSyncAction(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


class RemoteSyncConsentError(RuntimeError):
    pass


class RemoteSyncProviderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RemoteSyncItem:
    remote_id: str
    name: str
    kind: str
    size_bytes: int
    sha256: str
    provider: str

    def to_dict(self) -> dict[str, object]:
        return {
            "remote_id": self.remote_id,
            "name": self.name,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "provider": self.provider,
        }


@dataclass(frozen=True, slots=True)
class RemoteSyncTransfer:
    name: str
    kind: str
    local_path: Path
    size_bytes: int
    sha256: str
    remote_id: str = ""

    def manifest_item(self, provider: str) -> RemoteSyncItem:
        return RemoteSyncItem(
            remote_id=self.remote_id or self.name,
            name=self.name,
            kind=self.kind,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            provider=provider,
        )


@dataclass(frozen=True, slots=True)
class RemoteSyncPlan:
    action: RemoteSyncAction
    provider: str
    transfers: tuple[RemoteSyncTransfer, ...]
    requires_confirmation: bool = True
    automatic: bool = False
    disclosure: str = _DISCLOSURE

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.transfers)

    def public_summary(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "provider": self.provider,
            "automatic": self.automatic,
            "requires_confirmation": self.requires_confirmation,
            "total_bytes": self.total_bytes,
            "items": [item.manifest_item(self.provider).to_dict() for item in self.transfers],
            "disclosure": self.disclosure,
        }


@dataclass(frozen=True, slots=True)
class RemoteSyncManifest:
    provider: str
    action: RemoteSyncAction
    created_at: str
    items: tuple[RemoteSyncItem, ...]
    disclosure: str = _DISCLOSURE

    def to_dict(self) -> dict[str, object]:
        return {
            "version": _MANIFEST_VERSION,
            "provider": self.provider,
            "action": self.action.value,
            "created_at": self.created_at,
            "disclosure": self.disclosure,
            "items": [item.to_dict() for item in self.items],
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


class RemoteSyncClient(Protocol):
    provider: str

    def upload(self, transfer: RemoteSyncTransfer) -> RemoteSyncItem:
        raise NotImplementedError

    def download(self, item: RemoteSyncItem, target_path: Path) -> Path:
        raise NotImplementedError

    def list_items(self) -> tuple[RemoteSyncItem, ...]:
        raise NotImplementedError


class LocalFolderSyncClient:
    provider = "local-folder"

    def __init__(self, root: Path) -> None:
        self.root = root

    def upload(self, transfer: RemoteSyncTransfer) -> RemoteSyncItem:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / transfer.name
        shutil.copy2(transfer.local_path, target)
        item = transfer.manifest_item(self.provider)
        return RemoteSyncItem(target.name, item.name, item.kind, item.size_bytes, item.sha256, self.provider)

    def download(self, item: RemoteSyncItem, target_path: Path) -> Path:
        source = self.root / item.remote_id
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
        return target_path

    def list_items(self) -> tuple[RemoteSyncItem, ...]:
        if not self.root.exists():
            return ()
        return tuple(
            _item_from_remote_path(path, self.provider) for path in sorted(self.root.iterdir()) if path.is_file()
        )


def build_upload_plan(
    paths: Iterable[Path],
    *,
    provider: str,
    kind: str = "report",
) -> RemoteSyncPlan:
    transfers = tuple(_upload_transfer(path, kind) for path in paths)
    return RemoteSyncPlan(RemoteSyncAction.UPLOAD, provider, transfers)


def build_download_plan(
    items: Iterable[RemoteSyncItem],
    target_dir: Path,
    *,
    provider: str,
) -> RemoteSyncPlan:
    transfers = tuple(_download_transfer(item, target_dir) for item in items)
    return RemoteSyncPlan(RemoteSyncAction.DOWNLOAD, provider, transfers)


def execute_upload_plan(
    plan: RemoteSyncPlan,
    client: RemoteSyncClient,
    *,
    confirmed: bool = False,
) -> RemoteSyncManifest:
    _require_action(plan, RemoteSyncAction.UPLOAD)
    _require_client_provider(plan, client)
    _require_confirmation(plan, confirmed)
    items = tuple(client.upload(transfer) for transfer in plan.transfers)
    return _manifest(plan, items)


def execute_download_plan(
    plan: RemoteSyncPlan,
    client: RemoteSyncClient,
    *,
    confirmed: bool = False,
) -> RemoteSyncManifest:
    _require_action(plan, RemoteSyncAction.DOWNLOAD)
    _require_client_provider(plan, client)
    _require_confirmation(plan, confirmed)
    items = tuple(_download_item(client, transfer, plan.provider) for transfer in plan.transfers)
    return _manifest(plan, items)


def _upload_transfer(path: Path, kind: str) -> RemoteSyncTransfer:
    if not path.is_file():
        raise FileNotFoundError(path)
    return RemoteSyncTransfer(
        name=_safe_remote_name(path.name),
        kind=kind,
        local_path=path,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
    )


def _download_transfer(item: RemoteSyncItem, target_dir: Path) -> RemoteSyncTransfer:
    return RemoteSyncTransfer(
        name=_safe_remote_name(item.name),
        kind=item.kind,
        local_path=target_dir / _safe_remote_name(item.name),
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        remote_id=item.remote_id,
    )


def _download_item(client: RemoteSyncClient, transfer: RemoteSyncTransfer, provider: str) -> RemoteSyncItem:
    client.download(transfer.manifest_item(provider), transfer.local_path)
    return RemoteSyncItem(
        remote_id=transfer.remote_id or transfer.name,
        name=transfer.name,
        kind=transfer.kind,
        size_bytes=transfer.size_bytes,
        sha256=transfer.sha256,
        provider=provider,
    )


def _require_action(plan: RemoteSyncPlan, action: RemoteSyncAction) -> None:
    if plan.action != action:
        raise ValueError(f"Expected {action.value} plan, got {plan.action.value}")


def _require_confirmation(plan: RemoteSyncPlan, confirmed: bool) -> None:
    if plan.requires_confirmation and not confirmed:
        raise RemoteSyncConsentError("Remote sync requires explicit user confirmation.")


def _require_client_provider(plan: RemoteSyncPlan, client: RemoteSyncClient) -> None:
    if client.provider != plan.provider:
        raise RemoteSyncProviderError(f"Plan provider {plan.provider!r} does not match client {client.provider!r}.")


def _manifest(plan: RemoteSyncPlan, items: tuple[RemoteSyncItem, ...]) -> RemoteSyncManifest:
    return RemoteSyncManifest(
        provider=plan.provider,
        action=plan.action,
        created_at=_utc_timestamp(),
        items=items,
        disclosure=plan.disclosure,
    )


def _item_from_remote_path(path: Path, provider: str) -> RemoteSyncItem:
    return RemoteSyncItem(
        remote_id=path.name,
        name=path.name,
        kind="report",
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        provider=provider,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_remote_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ".-_" else "-" for char in value.strip())
    return cleaned.strip(".-") or "silentfrog-report"


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "LocalFolderSyncClient",
    "RemoteSyncAction",
    "RemoteSyncClient",
    "RemoteSyncConsentError",
    "RemoteSyncProviderError",
    "RemoteSyncItem",
    "RemoteSyncManifest",
    "RemoteSyncPlan",
    "RemoteSyncTransfer",
    "build_download_plan",
    "build_upload_plan",
    "execute_download_plan",
    "execute_upload_plan",
]
