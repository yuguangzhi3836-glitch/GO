import json
import logging
import sys
import unittest
from datetime import datetime
from unittest import mock

from go_hotel.observability.logging import JsonFormatter
from go_hotel.observability.metrics import MetricsRegistry, metrics
from go_hotel.observability import slo as slo_module


class JsonFormatterTests(unittest.TestCase):
    def make_record(self, msg="hello %s", args=("world",), exc_info=None, **extra):
        record = logging.LogRecord(
            name="observability.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=args,
            exc_info=exc_info,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_format_renders_compact_json_with_rendered_message(self):
        rendered = JsonFormatter().format(self.make_record())
        payload = json.loads(rendered)

        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["logger"], "observability.test")
        self.assertEqual(payload["message"], "hello world")
        self.assertIn("ts", payload)
        datetime.fromisoformat(payload["ts"])
        self.assertNotIn(": ", rendered)
        self.assertNotIn(", ", rendered)
        self.assertEqual(set(payload), {"ts", "level", "logger", "message"})

    def test_optional_context_fields_only_appear_when_present(self):
        record = self.make_record(
            request_id="req-1",
            trace_id="trace-1",
            span_id="span-1",
            actor_id="actor-1",
            supplier_id="supplier-1",
            path="/health",
            method="GET",
            status_code=200,
            duration_ms=12.5,
            event_type="http.request",
        )
        payload = json.loads(JsonFormatter().format(record))

        self.assertEqual(payload["request_id"], "req-1")
        self.assertEqual(payload["trace_id"], "trace-1")
        self.assertEqual(payload["span_id"], "span-1")
        self.assertEqual(payload["actor_id"], "actor-1")
        self.assertEqual(payload["supplier_id"], "supplier-1")
        self.assertEqual(payload["path"], "/health")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["status_code"], 200)
        self.assertEqual(payload["duration_ms"], 12.5)
        self.assertEqual(payload["event_type"], "http.request")

        payload_without_context = json.loads(JsonFormatter().format(self.make_record()))
        for key in (
            "request_id",
            "trace_id",
            "span_id",
            "actor_id",
            "supplier_id",
            "path",
            "method",
            "status_code",
            "duration_ms",
            "event_type",
        ):
            self.assertNotIn(key, payload_without_context)

    def test_format_includes_exception_traceback_when_present(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record = self.make_record(msg="failed", args=(), exc_info=sys.exc_info())

        payload = json.loads(JsonFormatter().format(record))

        self.assertIn("exception", payload)
        self.assertIn("Traceback", payload["exception"])
        self.assertIn("RuntimeError: boom", payload["exception"])


class MetricsRegistryTests(unittest.TestCase):
    def test_counter_histogram_and_gauge_are_reflected_in_readers_and_snapshot(self):
        registry = MetricsRegistry(max_histogram_samples=4)

        registry.inc("go_requests_total", 2, service="api", region="hk")
        registry.inc("go_requests_total", 3, region="hk", service="api")
        registry.inc("go_requests_total", 7, service="api", region="sg")
        registry.observe("go_request_latency_ms", 12, service="api")
        registry.observe("go_request_latency_ms", 30.5, service="api")
        registry.set("go_inflight_requests", 4, service="api")

        self.assertEqual(
            registry.counter_value("go_requests_total", service="api", region="hk"),
            5,
        )
        self.assertEqual(
            registry.counter_value("go_requests_total", region="sg", service="api"),
            7,
        )
        self.assertEqual(
            registry.histogram_values("go_request_latency_ms", service="api"),
            [12.0, 30.5],
        )

        snapshot = registry.snapshot()
        self.assertEqual(
            snapshot["histograms"][
                ("go_request_latency_ms", (("service", "api"),))
            ],
            [12.0, 30.5],
        )
        self.assertEqual(
            snapshot["histogram_totals"][
                ("go_request_latency_ms", (("service", "api"),))
            ],
            (2, 42.5),
        )
        self.assertEqual(
            snapshot["gauges"][("go_inflight_requests", (("service", "api"),))],
            4.0,
        )

    def test_label_identity_tracks_distinct_sets_and_ignores_label_order(self):
        registry = MetricsRegistry()

        registry.inc("go_events_total", 1, service="api", region="hk")
        registry.inc("go_events_total", 2, region="hk", service="api")
        registry.inc("go_events_total", 9, service="api", region="sg")
        registry.observe("go_duration_ms", 10, phase="search", service="api")
        registry.observe("go_duration_ms", 20, service="api", phase="search")
        registry.observe("go_duration_ms", 99, service="api", phase="book")

        self.assertEqual(
            registry.counter_value("go_events_total", region="hk", service="api"),
            3,
        )
        self.assertEqual(
            registry.counter_value("go_events_total", service="api", region="sg"),
            9,
        )
        self.assertEqual(
            registry.histogram_values("go_duration_ms", service="api", phase="search"),
            [10.0, 20.0],
        )
        self.assertEqual(
            registry.histogram_values("go_duration_ms", phase="book", service="api"),
            [99.0],
        )

    def test_histogram_retention_is_bounded_but_totals_keep_growing(self):
        registry = MetricsRegistry(max_histogram_samples=3)

        for value in (1, 2, 3, 4, 5):
            registry.observe("go_queue_wait_ms", value, queue="jobs")

        self.assertEqual(
            registry.histogram_values("go_queue_wait_ms", queue="jobs"),
            [3.0, 4.0, 5.0],
        )
        snapshot = registry.snapshot()
        self.assertEqual(
            snapshot["histogram_totals"][
                ("go_queue_wait_ms", (("queue", "jobs"),))
            ],
            (5, 15.0),
        )

    def test_invalid_histogram_capacity_raises_value_error(self):
        for value in (0, -1, 1.5, "3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    MetricsRegistry(max_histogram_samples=value)

    def test_prometheus_renders_counter_gauge_and_histogram_lines(self):
        registry = MetricsRegistry(max_histogram_samples=5)
        registry.inc("go_requests_total", 3, region="hk", service="api")
        registry.set("go_inflight_requests", 2, service="api")
        registry.observe("go_request_latency_ms", 10, region="hk", service="api")
        registry.observe("go_request_latency_ms", 40, service="api", region="hk")

        rendered = registry.prometheus().strip().splitlines()

        self.assertIn('go_requests_total{region="hk",service="api"} 3.0', rendered)
        self.assertIn('go_inflight_requests{service="api"} 2.0', rendered)
        self.assertIn(
            'go_request_latency_ms_count{region="hk",service="api"} 2',
            rendered,
        )
        self.assertIn(
            'go_request_latency_ms_sum{region="hk",service="api"} 50.0',
            rendered,
        )
        self.assertIn(
            'go_request_latency_ms_retained_samples{region="hk",service="api"} 2',
            rendered,
        )
        self.assertIn(
            "# HELP go_request_latency_ms_p95 P95 of the most recent up to 5 observations per label set.",
            rendered,
        )
        self.assertIn(
            'go_request_latency_ms_p95{region="hk",service="api"} 40.0',
            rendered,
        )


class CurrentSloStatusTests(unittest.TestCase):
    def test_returns_declared_slos_with_current_shared_registry_values(self):
        baseline_total = metrics.counter_value("go_http_requests_total")
        baseline_errors = metrics.counter_value("go_http_requests_5xx_total")

        metrics.inc("go_http_requests_total", 10)
        metrics.inc("go_http_requests_5xx_total", 2)

        expected_total = metrics.counter_value("go_http_requests_total")
        expected_errors = metrics.counter_value("go_http_requests_5xx_total")
        expected_availability = 1 - (expected_errors / expected_total)

        statuses = slo_module.current_slo_status()
        by_key = {entry["key"]: entry for entry in statuses}

        self.assertEqual(len(statuses), len(slo_module.SLOS))
        for declared in slo_module.SLOS:
            self.assertIn(declared.key, by_key)
            self.assertEqual(by_key[declared.key]["target"], declared.target)
            self.assertEqual(by_key[declared.key]["window"], declared.window)
            self.assertEqual(by_key[declared.key]["description"], declared.description)

        api_status = by_key["api_availability"]
        self.assertEqual(api_status["current"], expected_availability)
        self.assertEqual(
            api_status["status"],
            "PASS" if expected_availability >= by_key["api_availability"]["target"] else "BREACH",
        )

        for declared in slo_module.SLOS:
            if declared.key != "api_availability":
                self.assertIsNone(by_key[declared.key]["current"])
                self.assertEqual(
                    by_key[declared.key]["status"],
                    "INSUFFICIENT_WINDOW_DATA",
                )

        self.assertGreaterEqual(expected_total, baseline_total + 10)
        self.assertGreaterEqual(expected_errors, baseline_errors + 2)

    def test_api_availability_is_one_when_total_is_zero_and_status_uses_declared_target(self):
        fresh_metrics = MetricsRegistry()
        api_slo = next(slo for slo in slo_module.SLOS if slo.key == "api_availability")

        with mock.patch.object(slo_module, "metrics", fresh_metrics):
            zero_total_status = {
                entry["key"]: entry for entry in slo_module.current_slo_status()
            }["api_availability"]
            self.assertEqual(zero_total_status["current"], 1.0)
            self.assertEqual(
                zero_total_status["status"],
                "PASS" if 1.0 >= api_slo.target else "BREACH",
            )

            fresh_metrics.inc("go_http_requests_total", 100)
            fresh_metrics.inc("go_http_requests_5xx_total", 1)
            pass_status = {
                entry["key"]: entry for entry in slo_module.current_slo_status()
            }["api_availability"]
            self.assertEqual(
                pass_status["status"],
                "PASS" if pass_status["current"] >= api_slo.target else "BREACH",
            )

            fresh_metrics.inc("go_http_requests_total", 1000)
            fresh_metrics.inc("go_http_requests_5xx_total", 20)
            breach_status = {
                entry["key"]: entry for entry in slo_module.current_slo_status()
            }["api_availability"]
            self.assertEqual(
                breach_status["status"],
                "PASS" if breach_status["current"] >= api_slo.target else "BREACH",
            )
            self.assertEqual(breach_status["status"], "BREACH")


if __name__ == "__main__":
    unittest.main()
