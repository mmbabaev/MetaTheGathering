from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "pr.yml",
    ROOT / ".github" / "workflows" / "deploy.yml",
    ROOT / ".github" / "workflows" / "deploy_web.yml",
    ROOT / ".github" / "workflows" / "pauper_deploy.yml",
)


def test_all_deploy_jobs_are_disabled_by_default():
    for workflow_path in WORKFLOWS:
        workflow = workflow_path.read_text(encoding="utf-8")
        if workflow_path.name == "pr.yml":
            assert "vars.DEPLOY_ENABLED == 'true'" in workflow
        else:
            assert "if: vars.DEPLOY_ENABLED == 'true'" in workflow


def test_pr_tests_are_not_guarded_by_deploy_pause():
    workflow = (ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")

    test_job = workflow.split("  deploy-debug:", 1)[0]
    assert "name: Run tests" in test_job
    assert "DEPLOY_ENABLED" not in test_job


def test_local_server_uses_debug_env_and_guards_database_and_token():
    server = (ROOT / "server.sh").read_text(encoding="utf-8")

    assert 'local env_file="$SCRIPT_DIR/bot/.env.debug"' in server
    assert "BOT_ENV=debug nohup" in server
    assert 'export TELEGRAM_PROXY_URL=""' in server
    assert "debug DATABASE_URL must point to local" in server
    assert "uses the production Telegram token" in server
