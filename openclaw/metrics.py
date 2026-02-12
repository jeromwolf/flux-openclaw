"""Prometheus-compatible metrics collection.

In-memory counters and histograms. No external DB needed.
Thread-safe with own threading.Lock.
Process restart resets all metrics.
"""
from __future__ import annotations

import threading
import time
from typing import Optional


class MetricsCollector:
    """In-memory metrics collector with Prometheus text format export."""

    def __init__(self):
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._start_time = time.time()

        # Pre-register standard metrics
        self._init_default_metrics()

    def _init_default_metrics(self):
        """Register default metrics."""
        # Counters
        self.counter("http_requests_total", 0)
        self.counter("http_errors_total", 0)
        self.counter("chat_requests_total", 0)
        self.counter("chat_tokens_input_total", 0)
        self.counter("chat_tokens_output_total", 0)
        self.counter("chat_cost_usd_total", 0)
        self.counter("webhook_deliveries_total", 0)
        self.counter("webhook_failures_total", 0)
        self.counter("auth_successes_total", 0)
        self.counter("auth_failures_total", 0)

        # Gauges
        self.gauge("uptime_seconds", 0)
        self.gauge("active_users", 0)

    def counter(self, name: str, value: float = 0) -> None:
        """Register or set a counter."""
        with self._lock:
            self._counters[name] = value

    def increment(self, name: str, value: float = 1) -> None:
        """Increment a counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        """Set a gauge value."""
        with self._lock:
            self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        """Record a histogram observation."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)

    def get_counter(self, name: str) -> float:
        """Get counter value."""
        with self._lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        """Get gauge value."""
        with self._lock:
            return self._gauges.get(name, 0)

    def get_histogram(self, name: str) -> list[float]:
        """Get histogram values."""
        with self._lock:
            return list(self._histograms.get(name, []))

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format.

        Format per metric:
            # TYPE metric_name counter|gauge|histogram
            metric_name value
        """
        with self._lock:
            self._gauges["uptime_seconds"] = time.time() - self._start_time

            lines = []
            lines.append("# flux-openclaw metrics")
            lines.append("")

            # Counters
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")

            lines.append("")

            # Gauges
            for name, value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name} {value}")

            lines.append("")

            # Histograms (simplified: sum, count, avg)
            for name, values in sorted(self._histograms.items()):
                if values:
                    lines.append(f"# TYPE {name} summary")
                    lines.append(f"{name}_count {len(values)}")
                    lines.append(f"{name}_sum {sum(values):.6f}")
                    lines.append(f"{name}_avg {sum(values)/len(values):.6f}")

            lines.append("")
            return "\n".join(lines)

    def get_stats(self) -> dict:
        """Get all metrics as a dict (for JSON API)."""
        with self._lock:
            self._gauges["uptime_seconds"] = time.time() - self._start_time
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: {
                        "count": len(vals),
                        "sum": sum(vals) if vals else 0,
                        "avg": sum(vals) / len(vals) if vals else 0,
                    }
                    for name, vals in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """Reset all metrics to defaults (for testing)."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._start_time = time.time()
        self._init_default_metrics()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_collector: Optional[MetricsCollector] = None
_collector_lock = threading.Lock()


def get_metrics() -> MetricsCollector:
    """Get the global MetricsCollector singleton."""
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector


def reset_metrics() -> None:
    """Reset the global singleton (for testing)."""
    global _collector
    _collector = None
