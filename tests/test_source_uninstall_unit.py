from __future__ import annotations

from pathlib import Path

from tools.source_install import UninstallTargets
from tools.source_uninstall import run_uninstall


def _make_targets(tmp_path: Path) -> UninstallTargets:
    root = tmp_path / "repo"
    root.mkdir()
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    user_data = tmp_path / "AppData" / "Silentfrog"
    user_data.mkdir(parents=True)
    venv = root / ".venv"
    venv.mkdir()
    (venv / "marker").write_text("x", encoding="utf-8")
    launchers = (
        root / "run_silentfrog.sh",
        root / "install_silentfrog.sh",
        root / "uninstall_silentfrog.sh",
    )
    for path in launchers:
        path.write_text("placeholder\n", encoding="utf-8")
    (desktop / "Silentfrog.command").write_text("placeholder\n", encoding="utf-8")
    (user_data / "crawl_history").mkdir()
    (user_data / "crawl_history" / "history.json").write_text("{}", encoding="utf-8")
    return UninstallTargets(
        root=root,
        venv_dir=venv,
        desktop_lnk=desktop / "Silentfrog.lnk",
        desktop_command=desktop / "Silentfrog.command",
        launcher_scripts=launchers,
        user_data_dir=user_data,
    )


def test_uninstall_removes_venv_and_launchers(tmp_path: Path) -> None:
    targets = _make_targets(tmp_path)
    outcome = run_uninstall(targets, purge=False)
    assert not targets.venv_dir.exists()
    assert not targets.desktop_command.exists()
    for path in targets.launcher_scripts:
        assert not path.exists()
    assert targets.user_data_dir.exists(), "user data must be preserved without --purge"
    assert targets.venv_dir in outcome.removed
    assert targets.desktop_lnk in outcome.skipped


def test_uninstall_purge_removes_user_data(tmp_path: Path) -> None:
    targets = _make_targets(tmp_path)
    outcome = run_uninstall(targets, purge=True)
    assert not targets.user_data_dir.exists()
    assert targets.user_data_dir in outcome.removed


def test_uninstall_preserves_unrelated_nltk_dir(tmp_path: Path) -> None:
    targets = _make_targets(tmp_path)
    nltk_data = tmp_path / "nltk_data"
    nltk_data.mkdir()
    (nltk_data / "tokenizers").mkdir()
    run_uninstall(targets, purge=True)
    assert nltk_data.exists()
    assert (nltk_data / "tokenizers").exists()


def test_uninstall_skips_current_script(tmp_path: Path) -> None:
    targets = _make_targets(tmp_path)
    current = targets.launcher_scripts[2]
    outcome = run_uninstall(targets, current_script=current, purge=False)
    assert current.exists(), "the script running the uninstall must remain on disk"
    assert current not in outcome.removed
    for other in (targets.launcher_scripts[0], targets.launcher_scripts[1]):
        assert not other.exists()


def test_uninstall_outcome_is_idempotent(tmp_path: Path) -> None:
    targets = _make_targets(tmp_path)
    run_uninstall(targets, purge=True)
    second = run_uninstall(targets, purge=True)
    assert second.removed == ()
    expected_skipped = {
        targets.venv_dir,
        targets.desktop_lnk,
        targets.desktop_command,
        *targets.launcher_scripts,
        targets.user_data_dir,
    }
    assert set(second.skipped) == expected_skipped
