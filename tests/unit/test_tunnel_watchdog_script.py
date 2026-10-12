from pathlib import Path


def test_tunnel_watchdog_matches_only_prometheus_sample_row():
    """HELP/TYPE metadata must never be parsed as the HA connection value."""
    root = Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "tunnel-watchdog.sh").read_text(encoding="utf-8")

    assert '$1 == "cloudflared_tunnel_ha_connections"' in text
    assert "awk '/cloudflared_tunnel_ha_connections/" not in text
