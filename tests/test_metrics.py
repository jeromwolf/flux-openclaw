"""Tests for metrics.py -- MetricsCollector, get_metrics, reset_metrics."""
import threading

from metrics import MetricsCollector, get_metrics, reset_metrics


# ---------------------------------------------------------------------------
# MetricsCollector.__init__
# ---------------------------------------------------------------------------

class TestMetricsCollectorInit:
    """Verify fresh collectors have default counters and gauges."""

    def test_default_counters_exist(self):
        mc = MetricsCollector()
        expected = [
            "http_requests_total",
            "http_errors_total",
            "chat_requests_total",
            "chat_tokens_input_total",
            "chat_tokens_output_total",
            "chat_cost_usd_total",
            "webhook_deliveries_total",
            "webhook_failures_total",
            "auth_successes_total",
            "auth_failures_total",
        ]
        for name in expected:
            assert mc.get_counter(name) == 0, f"Counter {name} missing or non-zero"

    def test_default_gauges_exist(self):
        mc = MetricsCollector()
        assert mc.get_gauge("uptime_seconds") == 0
        assert mc.get_gauge("active_users") == 0

    def test_histograms_empty_initially(self):
        mc = MetricsCollector()
        assert mc.get_histogram("anything") == []


# ---------------------------------------------------------------------------
# counter / increment
# ---------------------------------------------------------------------------

class TestCounterOps:

    def test_counter_sets_value(self):
        mc = MetricsCollector()
        mc.counter("my_counter", 42)
        assert mc.get_counter("my_counter") == 42

    def test_counter_overwrites(self):
        mc = MetricsCollector()
        mc.counter("c", 10)
        mc.counter("c", 20)
        assert mc.get_counter("c") == 20

    def test_increment_adds_to_existing(self):
        mc = MetricsCollector()
        mc.counter("c", 5)
        mc.increment("c", 3)
        assert mc.get_counter("c") == 8

    def test_increment_creates_if_missing(self):
        mc = MetricsCollector()
        mc.increment("brand_new", 7)
        assert mc.get_counter("brand_new") == 7

    def test_increment_default_step_is_one(self):
        mc = MetricsCollector()
        mc.counter("c", 0)
        mc.increment("c")
        mc.increment("c")
        assert mc.get_counter("c") == 2


# ---------------------------------------------------------------------------
# gauge
# ---------------------------------------------------------------------------

class TestGaugeOps:

    def test_gauge_sets_value(self):
        mc = MetricsCollector()
        mc.gauge("temp", 36.6)
        assert mc.get_gauge("temp") == 36.6

    def test_gauge_overwrites(self):
        mc = MetricsCollector()
        mc.gauge("g", 1)
        mc.gauge("g", 99)
        assert mc.get_gauge("g") == 99


# ---------------------------------------------------------------------------
# observe / get_histogram
# ---------------------------------------------------------------------------

class TestHistogramOps:

    def test_observe_appends(self):
        mc = MetricsCollector()
        mc.observe("latency", 0.1)
        mc.observe("latency", 0.2)
        assert mc.get_histogram("latency") == [0.1, 0.2]

    def test_get_histogram_returns_copy(self):
        mc = MetricsCollector()
        mc.observe("h", 1.0)
        result = mc.get_histogram("h")
        result.append(999)
        assert mc.get_histogram("h") == [1.0]


# ---------------------------------------------------------------------------
# get_counter / get_gauge / get_histogram -- unknown names
# ---------------------------------------------------------------------------

class TestGetUnknown:

    def test_unknown_counter_returns_zero(self):
        mc = MetricsCollector()
        assert mc.get_counter("does_not_exist") == 0

    def test_unknown_gauge_returns_zero(self):
        mc = MetricsCollector()
        assert mc.get_gauge("does_not_exist") == 0

    def test_unknown_histogram_returns_empty_list(self):
        mc = MetricsCollector()
        assert mc.get_histogram("does_not_exist") == []


# ---------------------------------------------------------------------------
# export_prometheus
# ---------------------------------------------------------------------------

class TestExportPrometheus:

    def test_contains_header(self):
        mc = MetricsCollector()
        text = mc.export_prometheus()
        assert "# flux-openclaw metrics" in text

    def test_counter_format(self):
        mc = MetricsCollector()
        mc.counter("test_counter", 42)
        text = mc.export_prometheus()
        assert "# TYPE test_counter counter" in text
        assert "test_counter 42" in text

    def test_gauge_format(self):
        mc = MetricsCollector()
        mc.gauge("test_gauge", 7.5)
        text = mc.export_prometheus()
        assert "# TYPE test_gauge gauge" in text
        assert "test_gauge 7.5" in text

    def test_histogram_summary_format(self):
        mc = MetricsCollector()
        mc.observe("req_dur", 1.0)
        mc.observe("req_dur", 3.0)
        text = mc.export_prometheus()
        assert "# TYPE req_dur summary" in text
        assert "req_dur_count 2" in text
        assert "req_dur_sum 4.000000" in text
        assert "req_dur_avg 2.000000" in text

    def test_uptime_gauge_updated(self):
        mc = MetricsCollector()
        text = mc.export_prometheus()
        # uptime_seconds should be > 0 (time has passed since __init__)
        for line in text.splitlines():
            if line.startswith("uptime_seconds "):
                val = float(line.split()[1])
                assert val >= 0
                break
        else:
            raise AssertionError("uptime_seconds not found in output")


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

class TestGetStats:

    def test_keys_present(self):
        mc = MetricsCollector()
        stats = mc.get_stats()
        assert "counters" in stats
        assert "gauges" in stats
        assert "histograms" in stats

    def test_histogram_dict_format(self):
        mc = MetricsCollector()
        mc.observe("lat", 2.0)
        mc.observe("lat", 4.0)
        stats = mc.get_stats()
        h = stats["histograms"]["lat"]
        assert h["count"] == 2
        assert h["sum"] == 6.0
        assert h["avg"] == 3.0

    def test_empty_histogram_in_stats(self):
        """Histograms with no observations should not appear."""
        mc = MetricsCollector()
        stats = mc.get_stats()
        assert stats["histograms"] == {}


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_clears_custom_counter(self):
        mc = MetricsCollector()
        mc.counter("custom", 99)
        mc.reset()
        # custom counter should be gone, defaults re-initialised
        assert mc.get_counter("custom") == 0

    def test_reset_re_inits_defaults(self):
        mc = MetricsCollector()
        mc.increment("http_requests_total", 100)
        mc.reset()
        assert mc.get_counter("http_requests_total") == 0

    def test_reset_clears_histograms(self):
        mc = MetricsCollector()
        mc.observe("h", 1.0)
        mc.reset()
        assert mc.get_histogram("h") == []


# ---------------------------------------------------------------------------
# Singleton: get_metrics / reset_metrics
# ---------------------------------------------------------------------------

class TestSingleton:

    def setup_method(self):
        reset_metrics()

    def teardown_method(self):
        reset_metrics()

    def test_get_metrics_returns_same_instance(self):
        a = get_metrics()
        b = get_metrics()
        assert a is b

    def test_reset_metrics_creates_new_instance(self):
        a = get_metrics()
        reset_metrics()
        b = get_metrics()
        assert a is not b

    def test_new_instance_has_defaults(self):
        reset_metrics()
        mc = get_metrics()
        assert mc.get_counter("http_requests_total") == 0


# ---------------------------------------------------------------------------
# Thread safety smoke test
# ---------------------------------------------------------------------------

class TestThreadSafety:

    def test_concurrent_increments(self):
        mc = MetricsCollector()
        mc.counter("ts", 0)
        threads = []
        for _ in range(10):
            t = threading.Thread(target=lambda: [mc.increment("ts") for _ in range(100)])
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        assert mc.get_counter("ts") == 1000
