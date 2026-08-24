from __future__ import annotations

import unittest

try:
    from flask import Flask, jsonify
except ModuleNotFoundError:  # 本地轻量检查环境可不安装 Web 依赖
    Flask = None
    jsonify = None
from outlook_web.services.performance_metrics import (
    get_performance_snapshot,
    normalize_metric_name,
    record_ai_call,
    record_client_metrics,
    record_server_request,
    reset_performance_metrics,
)


class PerformanceMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_performance_metrics()

    def tearDown(self) -> None:
        reset_performance_metrics()

    def test_snapshot_aggregates_each_chain_and_detects_bottlenecks(self) -> None:
        record_server_request(
            route="/api/emails/<int:account_id>",
            method="GET",
            status=200,
            duration_ms=1200,
        )
        record_server_request(
            route="/api/emails/<int:account_id>",
            method="GET",
            status=502,
            duration_ms=3200,
        )
        accepted = record_client_metrics(
            [
                {
                    "kind": "api",
                    "name": "/api/emails/123?folder=inbox",
                    "duration_ms": 3900,
                    "status": 200,
                    "success": True,
                },
                {
                    "kind": "page",
                    "name": "/emails/123",
                    "duration_ms": 4200,
                    "status": 200,
                    "success": True,
                },
            ]
        )
        record_ai_call(success=False, duration_ms=7000, model="test-model")

        self.assertEqual(accepted, 2)
        snapshot = get_performance_snapshot()
        self.assertEqual(snapshot["summary"]["backend_api"]["count"], 2)
        self.assertEqual(snapshot["summary"]["backend_api"]["error_rate"], 50.0)
        self.assertEqual(snapshot["summary"]["mail"]["p95_ms"], 3900.0)
        self.assertEqual(snapshot["summary"]["page"]["p95_ms"], 4200.0)
        self.assertEqual(snapshot["summary"]["ai"]["p95_ms"], 7000.0)
        self.assertEqual(snapshot["client_endpoints"][0]["name"], "/api/emails/:id")
        layers = {item["layer"] for item in snapshot["bottlenecks"]}
        self.assertTrue({"后端", "前端", "邮件链路", "AI/外部服务"}.issubset(layers))

    def test_client_payload_is_bounded_and_rejects_invalid_metrics(self) -> None:
        metrics = [
            {"kind": "unknown", "name": "/bad", "duration_ms": 12},
            {"kind": "api", "name": "/bad", "duration_ms": -1},
            {"kind": "api", "name": "/ok", "duration_ms": 25, "status": 200},
        ]
        self.assertEqual(record_client_metrics(metrics), 1)
        self.assertEqual(get_performance_snapshot()["summary"]["frontend_api"]["count"], 1)

    def test_metric_name_removes_queries_and_dynamic_segments(self) -> None:
        self.assertEqual(
            normalize_metric_name("/api/emails/person@example.com?folder=inbox"),
            "/api/emails/:id",
        )
        self.assertEqual(normalize_metric_name("/api/items/123"), "/api/items/:id")
        self.assertEqual(
            normalize_metric_name("/api/emails/customer-slug/private-message"),
            "/api/emails/:id/:id",
        )
        self.assertEqual(normalize_metric_name("/mailbox/alice"), "/mailbox/:id")

    def test_snapshot_excludes_self_observation_routes(self) -> None:
        for route in ("/api/performance/client", "/api/overview/performance"):
            record_server_request(
                route=route,
                method="GET",
                status=200,
                duration_ms=25,
                trace_id="self-observation",
            )
        self.assertEqual(get_performance_snapshot()["summary"]["backend_api"]["count"], 0)

    def test_frontend_overhead_uses_unique_trace_and_matching_endpoint(self) -> None:
        for index in range(3):
            trace_id = f"matched-{index}"
            record_server_request(
                route="/api/emails/<string:account_id>",
                method="GET",
                status=200,
                duration_ms=200,
                trace_id=trace_id,
            )
            record_client_metrics(
                [
                    {
                        "kind": "api",
                        "name": f"/api/emails/customer-{index}",
                        "duration_ms": 900,
                        "status": 200,
                        "success": True,
                        "trace_id": trace_id,
                    }
                ]
            )

        record_server_request(
            route="/api/accounts/<string:account_id>",
            method="GET",
            status=200,
            duration_ms=100,
            trace_id="wrong-endpoint",
        )
        record_client_metrics(
            [
                {
                    "kind": "api",
                    "name": "/api/emails/customer-x",
                    "duration_ms": 5000,
                    "status": 200,
                    "success": True,
                    "trace_id": "wrong-endpoint",
                }
            ]
        )

        snapshot = get_performance_snapshot()
        overhead = snapshot["summary"]["frontend_overhead"]
        self.assertEqual(overhead["count"], 3)
        self.assertEqual(overhead["p95_ms"], 700.0)
        findings = [item for item in snapshot["bottlenecks"] if item["layer"] == "前端/网络"]
        self.assertEqual(len(findings), 1)
        self.assertIn("3 条唯一 trace", findings[0]["evidence"])


@unittest.skipIf(Flask is None, "Flask is not installed")
class PerformanceMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        from outlook_web.middleware.trace import attach_trace_id_and_normalize_errors, ensure_trace_id

        reset_performance_metrics()
        app = Flask(__name__)
        app.before_request(ensure_trace_id)
        app.after_request(attach_trace_id_and_normalize_errors)

        @app.get("/api/items/<int:item_id>")
        def get_item(item_id: int):
            return jsonify({"success": True, "id": item_id})

        self.client = app.test_client()

    def tearDown(self) -> None:
        reset_performance_metrics()

    def test_response_exposes_timing_and_records_route_template(self) -> None:
        response = self.client.get("/api/items/42", headers={"X-Trace-Id": "trace-test"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Trace-Id"], "trace-test")
        self.assertIn("X-Response-Time-Ms", response.headers)
        self.assertIn("app;dur=", response.headers["Server-Timing"])
        endpoints = get_performance_snapshot()["endpoints"]
        self.assertEqual(endpoints[0]["name"], "/api/items/:id")


if __name__ == "__main__":
    unittest.main()
