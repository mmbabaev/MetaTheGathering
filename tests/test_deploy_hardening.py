"""Static safety contracts for the server deploy entrypoints."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DEPLOY = ROOT / "bot" / "deploy_bot_debug.sh"
WEB_DEPLOY = ROOT / "bot" / "deploy_web_debug.sh"


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


def test_bot_env_upload_is_unique_and_removed_after_failure():
    source = _read(BOT_DEPLOY)

    assert 'REMOTE_ENV="/tmp/.env.deploy-$DEPLOY_ID"' in source
    assert "\"rm -f -- '$REMOTE_ARCHIVE' '$REMOTE_ENV'\"" in source
    assert 'rm -f -- "/tmp/$ARCHIVE_NAME" "$REMOTE_ENV"' in source
    assert 'chmod 600 "$ENV_DEST"' in source
    assert 'DATABASE_SCHEMA="metagatherer_pr_${PREVIEW_ID}"' in source
    assert 'rm -f -- "$ENV_UPLOAD"' in source
    assert "/tmp/.env.deploy\n" not in source


def test_debug_deploy_requires_and_propagates_pr_preview_id():
    bot_source = _read(BOT_DEPLOY)
    web_source = _read(WEB_DEPLOY)
    workflow = _read(ROOT / ".github" / "workflows" / "pr.yml")

    assert "PREVIEW_ID: ${{ github.event.pull_request.number }}" in workflow
    assert workflow.count("PREVIEW_ID: ${{ github.event.pull_request.number }}") == 1
    assert "${PREVIEW_ID:-}" in bot_source
    assert "${PREVIEW_ID:-}" in web_source
    assert "DATABASE_SCHEMA=$EXPECTED_DATABASE_SCHEMA" in web_source


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


def test_pr_deploy_does_not_upload_the_same_repository_twice():
    workflow = _read(ROOT / ".github" / "workflows" / "pr.yml")
    bot_source = _read(BOT_DEPLOY)

    assert workflow.count("bash bot/deploy_bot_debug.sh") == 1
    assert "bash bot/deploy_web_debug.sh" not in workflow
    assert 'SYSTEMD_WEB_SERVICE_FILE="$REMOTE_DIR/bot/systemd/meta-the-gathering-debug-web.service"' in bot_source
    assert 'sudo systemctl restart "$WEB_SERVICE_NAME"' in bot_source
