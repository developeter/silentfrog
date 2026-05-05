from __future__ import annotations

from pathlib import Path

import pytest

from silentfrog.remote_sync import (  # type: ignore[reportMissingImports]
    LocalFolderSyncClient,
    RemoteSyncAction,
    RemoteSyncConsentError,
    RemoteSyncItem,
    RemoteSyncProviderError,
    build_download_plan,
    build_upload_plan,
    execute_download_plan,
    execute_upload_plan,
)


def test_upload_plan_is_explicit_and_public_summary_has_no_local_paths(tmp_path: Path) -> None:
    report = tmp_path / "audit report.xlsx"
    report.write_text("report-data", encoding="utf-8")

    plan = build_upload_plan([report], provider="google-drive", kind="excel-report")
    summary = plan.public_summary()

    assert plan.action == RemoteSyncAction.UPLOAD
    assert plan.automatic is False
    assert plan.requires_confirmation is True
    assert "explicit user confirmation" in plan.disclosure
    assert summary["total_bytes"] == len("report-data")
    assert str(tmp_path) not in str(summary)
    assert summary["items"][0]["name"] == "audit-report.xlsx"


def test_upload_requires_user_confirmation(tmp_path: Path) -> None:
    report = tmp_path / "report.xlsx"
    report.write_text("report-data", encoding="utf-8")
    remote = tmp_path / "remote"
    plan = build_upload_plan([report], provider="local-folder")

    with pytest.raises(RemoteSyncConsentError):
        execute_upload_plan(plan, LocalFolderSyncClient(remote))

    assert not remote.exists()


def test_plan_provider_must_match_client_provider(tmp_path: Path) -> None:
    report = tmp_path / "report.xlsx"
    report.write_text("report-data", encoding="utf-8")
    plan = build_upload_plan([report], provider="google-drive")

    with pytest.raises(RemoteSyncProviderError):
        execute_upload_plan(plan, LocalFolderSyncClient(tmp_path / "remote"), confirmed=True)


def test_confirmed_upload_copies_file_and_writes_manifest(tmp_path: Path) -> None:
    report = tmp_path / "report.xlsx"
    report.write_text("report-data", encoding="utf-8")
    remote = tmp_path / "remote"
    plan = build_upload_plan([report], provider="local-folder")

    manifest = execute_upload_plan(plan, LocalFolderSyncClient(remote), confirmed=True)
    manifest_path = manifest.save(tmp_path / "manifest.json")

    assert (remote / "report.xlsx").read_text(encoding="utf-8") == "report-data"
    assert manifest.action == RemoteSyncAction.UPLOAD
    assert manifest.items[0].sha256
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")


def test_download_requires_confirmation_and_restores_selected_items(tmp_path: Path) -> None:
    remote = tmp_path / "remote"
    remote.mkdir()
    source = remote / "report.xlsx"
    source.write_text("report-data", encoding="utf-8")
    client = LocalFolderSyncClient(remote)
    item = client.list_items()[0]
    target_dir = tmp_path / "downloads"
    plan = build_download_plan([item], target_dir, provider="local-folder")

    with pytest.raises(RemoteSyncConsentError):
        execute_download_plan(plan, client)

    manifest = execute_download_plan(plan, client, confirmed=True)

    assert (target_dir / "report.xlsx").read_text(encoding="utf-8") == "report-data"
    assert manifest.action == RemoteSyncAction.DOWNLOAD
    assert manifest.items[0].remote_id == "report.xlsx"


def test_download_plan_keeps_remote_identity_and_sanitizes_target_name(tmp_path: Path) -> None:
    item = RemoteSyncItem(
        remote_id="drive-id-123",
        name="client report?.xlsx",
        kind="excel-report",
        size_bytes=10,
        sha256="abc",
        provider="google-drive",
    )

    plan = build_download_plan([item], tmp_path, provider="google-drive")

    assert plan.transfers[0].remote_id == "drive-id-123"
    assert plan.transfers[0].local_path.name == "client-report-.xlsx"
