from concurrent.futures import ThreadPoolExecutor
import unittest

from go_hotel.observability.metrics import MetricsRegistry


class MetricsRegistryCanaryTests(unittest.TestCase):
    def test_concurrent_inc_does_not_drop_counts(self):
        registry = MetricsRegistry()

        def increment_batch(_):
            for _ in range(250):
                registry.inc("requests_total", status="200")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(increment_batch, range(8)))

        self.assertEqual(
            registry.counter_value("requests_total", status="200"),
            2000.0,
        )

    def test_histogram_retains_recent_samples_and_lifetime_totals(self):
        registry = MetricsRegistry(max_histogram_samples=3)

        for value in (1, 2, 3, 4, 5):
            registry.observe("latency_ms", value, route="/health")

        self.assertEqual(
            registry.histogram_values("latency_ms", route="/health"),
            [3.0, 4.0, 5.0],
        )
        snapshot = registry.snapshot()
        key = registry._key("latency_ms", {"route": "/health"})
        self.assertEqual(snapshot["histogram_totals"][key], (5, 15.0))

    def test_snapshot_and_histogram_values_return_copies(self):
        registry = MetricsRegistry(max_histogram_samples=4)
        registry.inc("requests_total", 2, route="/orders")
        registry.observe("latency_ms", 10, route="/orders")
        registry.observe("latency_ms", 20, route="/orders")
        registry.set("queue_depth", 3, worker="outbox")

        key = registry._key("latency_ms", {"route": "/orders"})
        gauge_key = registry._key("queue_depth", {"worker": "outbox"})
        counter_key = registry._key("requests_total", {"route": "/orders"})

        values = registry.histogram_values("latency_ms", route="/orders")
        values.append(99.0)

        snapshot = registry.snapshot()
        snapshot["counters"][counter_key] = 999.0
        snapshot["histograms"][key].append(77.0)
        snapshot["histogram_totals"][key] = (999, 999.0)
        snapshot["gauges"][gauge_key] = 999.0

        fresh = registry.snapshot()
        self.assertEqual(registry.counter_value("requests_total", route="/orders"), 2.0)
        self.assertEqual(registry.histogram_values("latency_ms", route="/orders"), [10.0, 20.0])
        self.assertEqual(fresh["histogram_totals"][key], (2, 30.0))
        self.assertEqual(fresh["gauges"][gauge_key], 3.0)

    def test_label_sets_are_isolated(self):
        registry = MetricsRegistry(max_histogram_samples=2)
        registry.inc("requests_total", status="200", route="/health")
        registry.inc("requests_total", status="500", route="/orders")
        registry.observe("latency_ms", 11, route="/health")
        registry.observe("latency_ms", 22, route="/orders")

        self.assertEqual(
            registry.counter_value("requests_total", status="200", route="/health"),
            1.0,
        )
        self.assertEqual(
            registry.counter_value("requests_total", status="500", route="/orders"),
            1.0,
        )
        self.assertEqual(
            registry.histogram_values("latency_ms", route="/health"),
            [11.0],
        )
        self.assertEqual(
            registry.histogram_values("latency_ms", route="/orders"),
            [22.0],
        )


if __name__ == "__main__":
    unittest.main()
