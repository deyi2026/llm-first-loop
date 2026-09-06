"""Mirror restart script must probe the public readiness endpoint under browser auth."""

from pathlib import Path


def test_mirror_web_readiness_uses_public_auth_status() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/restart_mirror.sh").read_text(encoding="utf-8")
    assert '"http://$check_host:$check_port/auth/status"' in script
    assert '"http://$WEB_HOST:$WEB_PORT/auth/status"' in script
    assert '"http://$check_host:$check_port/health"' not in script
    assert '"http://$WEB_HOST:$WEB_PORT/health"' not in script
