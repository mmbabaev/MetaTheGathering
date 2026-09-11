"""Static safety contracts for the server deploy entrypoints."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DEPLOY = ROOT / "bot" / "deploy_bot_debug.sh"
WEB_DEPLOY = ROOT / "bot" / "deploy_web_debug.sh"
SYSTEMD_DIR = ROOT / "bot" / "systemd"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deploy_scripts_have_valid_bash_syntax():
    for script in (BOT_DEPLOY, WEB_DEPLOY):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_deploy_scripts_lock_and_clean_up_each_attempt():
    for script in (BOT_DEPLOY, WEB_DEPLOY):
        source = _read(script)

        assert 'REMOTE_LOCK="/tmp/meta-the-gathering-${MODE}-deploy.lock"' in source
        assert "flock -w 900 '$REMOTE_LOCK' bash -s" in source
        assert "trap cleanup EXIT" in source
        assert "trap cleanup_remote EXIT" in source
        assert "REMOTE_FREE_BYTES=" in source
        assert "MIN_FREE_BYTES=$((200 * 1024 * 1024))" in source
        assert "umask 077" in source


def test_deploy_archives_never_include_git_metadata():
    for script in (BOT_DEPLOY, WEB_DEPLOY):
        source = _read(script)

        assert "--exclude='.git'" in source
        assert "--exclude='.git/'" not in source
        assert 'rm -rf "$REMOTE_DIR/.git"' in source


def test_bot_env_upload_is_unique_and_removed_after_failure():
    source = _read(BOT_DEPLOY)

    assert 'REMOTE_ENV="/tmp/.env.deploy-$DEPLOY_ID"' in source
    assert "\"rm -f -- '$REMOTE_ARCHIVE' '$REMOTE_ENV'\"" in source
    assert 'rm -f -- "/tmp/$ARCHIVE_NAME" "$REMOTE_ENV"' in source
    assert 'chmod 600 "$ENV_DEST"' in source
    assert "printf '\\nDATABASE_SCHEMA=\\n'" in source
    assert 'rm -f -- "$ENV_UPLOAD"' in source
    assert "/tmp/.env.deploy\n" not in source


def test_debug_deploy_uses_one_durable_database_schema():
    bot_source = _read(BOT_DEPLOY)
    web_source = _read(WEB_DEPLOY)
    workflow = _read(ROOT / ".github" / "workflows" / "pr.yml")

    assert "PREVIEW_ID" not in workflow
    assert "PREVIEW_ID" not in bot_source
    assert "PREVIEW_ID" not in web_source
    assert "metagatherer_pr_" not in bot_source
    assert 'grep -qx "DATABASE_SCHEMA=" "$ENV_DEST"' in web_source


def test_workflows_serialize_deploys_by_environment():
    expected_groups = {
        ROOT / ".github" / "workflows" / "pr.yml": "metagatherer-debug-deploy",
        ROOT / ".github" / "workflows" / "deploy.yml": "metagatherer-production-deploy",
        ROOT / ".github" / "workflows" / "deploy_web.yml": "metagatherer-production-deploy",
    }

    for path, expected_group in expected_groups.items():
        workflow = path.read_text(encoding="utf-8")

        assert f"group: {expected_group}" in workflow
        assert "cancel-in-progress: false" in workflow


def test_endstep_worker_has_separate_daily_persistent_timers():
    for prefix in ("meta-the-gathering-endstep-worker", "meta-the-gathering-debug-endstep-worker"):
        service = _read(SYSTEMD_DIR / f"{prefix}.service")
        timer = _read(SYSTEMD_DIR / f"{prefix}.timer")

        assert "Type=oneshot" in service
        assert "python -m workers.endstep_leaderboard" in service
        assert "OnCalendar=daily" in timer
        assert "Persistent=true" in timer
        assert f"Unit={prefix}.service" in timer


def test_bot_deploy_installs_and_starts_endstep_worker_timer():
    source = _read(BOT_DEPLOY)

    assert 'ENDSTEP_WORKER_NAME="meta-the-gathering-endstep-worker"' in source
    assert 'ENDSTEP_WORKER_NAME="meta-the-gathering-debug-endstep-worker"' in source
    assert 'sudo cp "$ENDSTEP_WORKER_SERVICE_FILE" /etc/systemd/system/' in source
    assert 'sudo cp "$ENDSTEP_WORKER_TIMER_FILE" /etc/systemd/system/' in source
    assert 'sudo systemctl enable "$ENDSTEP_WORKER_NAME.timer"' in source
    assert 'sudo systemctl restart "$ENDSTEP_WORKER_NAME.timer"' in source
    assert 'sudo systemctl start "$ENDSTEP_WORKER_NAME.service"' in source
