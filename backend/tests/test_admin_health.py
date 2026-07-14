"""
Integration test for GET /api/admin/health's cluster-wide connection count.

engine.pool only reflects connections opened by this process — with 2+ ECS
Fargate tasks behind the ALB in production, each task has its own separate
pool, so the old pool_checked_out/pool_size numbers only showed "this task's
share." This checks the new pg_stat_activity-based cluster_connections /
max_connections fields query real Postgres system views successfully.
"""


def test_health_reports_cluster_wide_connection_count(client):
    resp = client.get("/api/admin/health")
    assert resp.status_code == 200
    body = resp.json()

    assert body["connected"] is True
    assert isinstance(body["cluster_connections"], int)
    assert body["cluster_connections"] >= 1  # at least this test's own connection
    assert isinstance(body["max_connections"], int)
    assert body["max_connections"] > 0
    assert 0 <= body["cluster_usage_pct"] <= 100

    # Per-task pool stats still present alongside the cluster-wide numbers.
    assert "pool_size" in body
    assert "pool_checked_out" in body
    assert "pool_usage_pct" in body
