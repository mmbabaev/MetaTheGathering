"""Static safety contracts for the server deploy entrypoints."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DEPLOY = ROOT / "bot" / "deploy_bot_debug.sh"
WEB_DEPLOY = ROOT / "bot" / "deploy_web_debug.sh"
PAUPER_DEPLOY = ROOT / "bot" / "deploy_pauper_sim.sh"
SSH_PREFLIGHT = ROOT / "bot" / "setup_ssh_known_hosts.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deploy_scripts_have_valid_bash_syntax():
    for script in (BOT_DEPLOY, WEB_DEPLOY, PAUPER_DEPLOY, SSH_PREFLIGHT):
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


def test_deploy_scripts_use_shared_host_and_bounded_ssh_options():
    for script in (BOT_DEPLOY, WEB_DEPLOY, PAUPER_DEPLOY):
        source = _read(script)

        assert 'SERVER_USER="${SERVER_USER:-mbabaev}"' in source
        assert 'SERVER_HOST="${SERVER_HOST:-158.160.9.28}"' in source
        assert 'REMOTE_DIR="/home/${SERVER_USER}/MetaTheGathering/' in source
        assert "ConnectTimeout=30" in source
        assert "ConnectionAttempts=3" in source
        assert '"${SSH_OPTS[@]}"' in source


def test_ssh_preflight_has_bounded_retries_and_validates_host():
    source = _read(SSH_PREFLIGHT)

    assert 'SERVER_HOST="${SERVER_HOST:-}"' in source
    assert "ssh-keyscan -T 5 -H" in source
    assert "for attempt in 1 2 3" in source
    assert "sleep 5" in source
    assert 'cat "$known_hosts_file" >>"$HOME/.ssh/known_hosts"' in source


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
        ROOT / ".github" / "workflows" / "pauper_deploy.yml": "pauper-sim-deploy",
    }

    for path, expected_group in expected_groups.items():
        workflow = path.read_text(encoding="utf-8")

        assert f"group: {expected_group}" in workflow
        assert "cancel-in-progress: false" in workflow


def test_workflows_use_shared_ssh_preflight_and_secret_host():
    workflow_paths = (
        ROOT / ".github" / "workflows" / "pr.yml",
        ROOT / ".github" / "workflows" / "deploy.yml",
        ROOT / ".github" / "workflows" / "deploy_web.yml",
        ROOT / ".github" / "workflows" / "pauper_deploy.yml",
    )

    for path in workflow_paths:
        workflow = _read(path)

        assert "timeout-minutes:" in workflow
        assert "bash bot/setup_ssh_known_hosts.sh" in workflow
        assert "SERVER_HOST: ${{ secrets.SERVER_HOST }}" in workflow
        assert "SERVER_USER: ${{ secrets.SERVER_USER }}" in workflow


def test_pull_request_deploy_skips_docs_only_changes():
    workflow = _read(ROOT / ".github" / "workflows" / "pr.yml")

    assert "dorny/paths-filter@v3" in workflow
    assert "needs: [test, changes]" in workflow
    assert "needs.changes.outputs.deploy == 'true'" in workflow


def test_bot_deploy_removes_legacy_endstep_systemd_timer():
    source = _read(BOT_DEPLOY)

    assert 'LEGACY_ENDSTEP_WORKER_NAME="meta-the-gathering-endstep-worker"' in source
    assert 'LEGACY_ENDSTEP_WORKER_NAME="meta-the-gathering-debug-endstep-worker"' in source
    assert 'sudo systemctl disable --now "$LEGACY_ENDSTEP_WORKER_NAME.timer"' in source
    assert 'sudo rm -f "/etc/systemd/system/$LEGACY_ENDSTEP_WORKER_NAME.timer"' in source
    assert 'sudo rm -f "/etc/systemd/system/$LEGACY_ENDSTEP_WORKER_NAME.service"' in source
    assert "ENDSTEP_WORKER_SERVICE_FILE" not in source
    assert "ENDSTEP_WORKER_TIMER_FILE" not in source
