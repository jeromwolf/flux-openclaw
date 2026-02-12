"""Tests for webhook.py (WebhookStore and WebhookDispatcher).

Covers:
- WebhookStore: CRUD operations, event matching, delivery recording,
                failure tracking with auto-deactivation
- WebhookDispatcher: HMAC signing, threaded dispatch, delivery with retry
"""
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import pytest
from io import BytesIO
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from webhook import WebhookStore, WebhookDispatcher


# ============================================================
# WebhookStore Tests
# ============================================================

class TestWebhookStoreCreate:
    def test_returns_dict_with_required_keys(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        result = store.create_webhook("user1", "https://example.com/hook", ["chat.completed"])
        assert "id" in result
        assert "url" in result
        assert "events" in result
        assert "secret" in result
        store.close()

    def test_auto_generates_secret(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        result = store.create_webhook("user1", "https://example.com/hook", ["chat.completed"])
        assert isinstance(result["secret"], str)
        assert len(result["secret"]) == 64  # token_hex(32) produces 64 hex chars
        store.close()

    def test_uses_provided_secret(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        result = store.create_webhook("user1", "https://example.com/hook", ["chat.completed"], secret="my-secret")
        assert result["secret"] == "my-secret"
        store.close()

    def test_stored_in_db_and_retrievable(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        created = store.create_webhook("user1", "https://example.com/hook", ["chat.completed"])
        fetched = store.get_webhook(created["id"])
        assert fetched is not None
        assert fetched["url"] == "https://example.com/hook"
        assert fetched["events"] == ["chat.completed"]
        store.close()

    def test_is_active_true_by_default(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        created = store.create_webhook("user1", "https://example.com/hook", [])
        assert created["is_active"] is True
        store.close()

    def test_failure_count_zero_by_default(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        created = store.create_webhook("user1", "https://example.com/hook", [])
        assert created["failure_count"] == 0
        store.close()


class TestWebhookStoreList:
    def test_returns_webhooks_for_user(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://a.com", ["chat.completed"])
        store.create_webhook("user1", "https://b.com", ["chat.error"])
        result = store.list_webhooks("user1")
        assert len(result) == 2
        store.close()

    def test_excludes_other_users(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://a.com", [])
        store.create_webhook("user2", "https://b.com", [])
        result = store.list_webhooks("user1")
        assert len(result) == 1
        assert result[0]["url"] == "https://a.com"
        store.close()

    def test_excludes_inactive(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.delete_webhook(wh["id"], "user1")
        result = store.list_webhooks("user1")
        assert len(result) == 0
        store.close()


class TestWebhookStoreGet:
    def test_returns_webhook_by_id(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        created = store.create_webhook("user1", "https://a.com", ["chat.completed"])
        fetched = store.get_webhook(created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["url"] == "https://a.com"
        store.close()

    def test_returns_none_for_unknown_id(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        assert store.get_webhook("nonexistent-id") is None
        store.close()


class TestWebhookStoreDelete:
    def test_soft_deletes_webhook(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        result = store.delete_webhook(wh["id"], "user1")
        assert result is True
        # Still retrievable via get, but is_active should be False
        fetched = store.get_webhook(wh["id"])
        assert fetched is not None
        assert fetched["is_active"] is False
        store.close()

    def test_returns_false_for_non_owned_webhook(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        result = store.delete_webhook(wh["id"], "user2")
        assert result is False
        store.close()

    def test_deleted_webhook_not_in_list(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.delete_webhook(wh["id"], "user1")
        result = store.list_webhooks("user1")
        assert len(result) == 0
        store.close()

    def test_returns_false_for_already_deleted(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.delete_webhook(wh["id"], "user1")
        result = store.delete_webhook(wh["id"], "user1")
        assert result is False
        store.close()


class TestWebhookStoreGetActive:
    def test_matches_event_type(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://a.com", ["chat.completed"])
        store.create_webhook("user1", "https://b.com", ["chat.error"])
        result = store.get_active_webhooks("chat.completed")
        assert len(result) == 1
        assert result[0]["url"] == "https://a.com"
        store.close()

    def test_empty_events_matches_all(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://catch-all.com", [])
        result = store.get_active_webhooks("any.event.type")
        assert len(result) == 1
        assert result[0]["url"] == "https://catch-all.com"
        store.close()

    def test_excludes_inactive_webhooks(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", ["chat.completed"])
        store.delete_webhook(wh["id"], "user1")
        result = store.get_active_webhooks("chat.completed")
        assert len(result) == 0
        store.close()


class TestWebhookStoreRecordDelivery:
    def test_inserts_delivery_row(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.record_delivery(
            webhook_id=wh["id"],
            event_type="chat.completed",
            payload_json='{"msg":"hello"}',
            response_status=200,
            response_body="OK",
            attempt=1,
        )
        # Verify by querying DB directly
        cursor = store._conn.cursor()
        cursor.execute("SELECT * FROM webhook_deliveries WHERE webhook_id = ?", (wh["id"],))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["response_status"] == 200
        store.close()

    def test_truncates_long_response_body(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        long_body = "x" * 10000
        store.record_delivery(
            webhook_id=wh["id"],
            event_type="chat.completed",
            payload_json="{}",
            response_status=200,
            response_body=long_body,
            attempt=1,
        )
        cursor = store._conn.cursor()
        cursor.execute("SELECT response_body FROM webhook_deliveries WHERE webhook_id = ?", (wh["id"],))
        row = cursor.fetchone()
        assert len(row["response_body"]) == 4096
        store.close()


class TestWebhookStoreFailure:
    def test_increment_failure_increases_count(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.increment_failure(wh["id"])
        fetched = store.get_webhook(wh["id"])
        assert fetched["failure_count"] == 1
        store.close()

    def test_deactivates_when_exceeds_max_retries(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        # max_retries defaults to 3, so 4 increments should deactivate
        for _ in range(4):
            store.increment_failure(wh["id"])
        fetched = store.get_webhook(wh["id"])
        assert fetched["is_active"] is False
        store.close()

    def test_stays_active_at_max_retries(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        # max_retries=3, so exactly 3 failures should keep active
        for _ in range(3):
            store.increment_failure(wh["id"])
        fetched = store.get_webhook(wh["id"])
        assert fetched["failure_count"] == 3
        assert fetched["is_active"] is True
        store.close()

    def test_reset_failure_resets_to_zero(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        wh = store.create_webhook("user1", "https://a.com", [])
        store.increment_failure(wh["id"])
        store.increment_failure(wh["id"])
        store.reset_failure(wh["id"])
        fetched = store.get_webhook(wh["id"])
        assert fetched["failure_count"] == 0
        store.close()


# ============================================================
# WebhookDispatcher Tests
# ============================================================

class TestDispatcherSignPayload:
    def test_returns_sha256_prefix_format(self):
        sig = WebhookDispatcher._sign_payload(b"test payload", "secret123")
        assert sig.startswith("sha256=")

    def test_hmac_sha256_matches_manual_calculation(self):
        payload = b'{"event":"test"}'
        secret = "webhook-secret"
        sig = WebhookDispatcher._sign_payload(payload, secret)
        expected_mac = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        )
        expected = f"sha256={expected_mac.hexdigest()}"
        assert sig == expected

    def test_different_secrets_produce_different_signatures(self):
        payload = b"same data"
        sig1 = WebhookDispatcher._sign_payload(payload, "secret-a")
        sig2 = WebhookDispatcher._sign_payload(payload, "secret-b")
        assert sig1 != sig2


class TestDispatcherDispatch:
    def test_spawns_threads_for_matching_webhooks(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://a.com", ["chat.completed"])
        store.create_webhook("user2", "https://b.com", ["chat.completed"])
        dispatcher = WebhookDispatcher(store)

        with patch.object(threading, "Thread") as MockThread:
            mock_instance = MagicMock()
            MockThread.return_value = mock_instance
            dispatcher.dispatch("chat.completed", {"msg": "hi"})
            assert MockThread.call_count == 2
            assert mock_instance.start.call_count == 2
        store.close()

    def test_no_threads_when_no_matching_webhooks(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        store.create_webhook("user1", "https://a.com", ["chat.error"])
        dispatcher = WebhookDispatcher(store)

        with patch.object(threading, "Thread") as MockThread:
            dispatcher.dispatch("chat.completed", {"msg": "hi"})
            assert MockThread.call_count == 0
        store.close()


class TestDispatcherDeliver:
    def _make_dispatcher(self, tmp_path):
        store = WebhookStore(db_path=str(tmp_path / "wh.db"))
        return store, WebhookDispatcher(store)

    def _make_webhook(self, store, events=None):
        return store.create_webhook("user1", "https://target.com/hook", events or [])

    def _make_mock_response(self, status=200, body=b"OK"):
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.read.return_value = body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_records_delivery_on_success(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)
        mock_urlopen.return_value = self._make_mock_response(200, b"OK")

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        cursor = store._conn.cursor()
        cursor.execute("SELECT * FROM webhook_deliveries WHERE webhook_id = ?", (wh["id"],))
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["response_status"] == 200
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_resets_failure_on_success(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)
        store.increment_failure(wh["id"])  # set failure_count=1
        mock_urlopen.return_value = self._make_mock_response(200, b"OK")

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        fetched = store.get_webhook(wh["id"])
        assert fetched["failure_count"] == 0
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_retries_on_failure(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)

        # Fail 2 times, succeed on 3rd
        mock_urlopen.side_effect = [
            urllib.error.URLError("connection refused"),
            urllib.error.URLError("connection refused"),
            self._make_mock_response(200, b"OK"),
        ]

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        # Should have been called 3 times
        assert mock_urlopen.call_count == 3
        # 2 sleeps for retries (before attempt 2 and 3)
        assert mock_sleep.call_count == 2
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_increments_failure_after_all_retries_exhausted(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)

        # Fail all 3 attempts (max_retries=3)
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        fetched = store.get_webhook(wh["id"])
        assert fetched["failure_count"] == 1
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_handles_http_error(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)

        http_err = urllib.error.HTTPError(
            url="https://target.com/hook",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=BytesIO(b"server error"),
        )
        mock_urlopen.side_effect = http_err

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        cursor = store._conn.cursor()
        cursor.execute("SELECT * FROM webhook_deliveries WHERE webhook_id = ?", (wh["id"],))
        rows = cursor.fetchall()
        # All 3 attempts should be recorded
        assert len(rows) == 3
        for row in rows:
            assert dict(row)["response_status"] == 500
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_exponential_backoff_timing(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)
        mock_urlopen.side_effect = urllib.error.URLError("fail")

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        # Backoff: 1s after attempt 1, 2s after attempt 2, no sleep after last
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # BASE_BACKOFF * 2^0
        mock_sleep.assert_any_call(2)  # BASE_BACKOFF * 2^1
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_sends_correct_headers(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)
        mock_urlopen.return_value = self._make_mock_response(200, b"OK")

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"
        assert req.get_header("X-flux-event") == "chat.completed"
        assert req.get_header("X-flux-signature").startswith("sha256=")
        assert req.get_header("User-agent") == "flux-openclaw-webhook/1.0"
        store.close()

    @patch("webhook.time.sleep")
    @patch("webhook.urllib.request.urlopen")
    def test_records_all_delivery_attempts(self, mock_urlopen, mock_sleep, tmp_path):
        store, dispatcher = self._make_dispatcher(tmp_path)
        wh = self._make_webhook(store)

        # Fail twice, succeed on 3rd
        mock_urlopen.side_effect = [
            urllib.error.URLError("fail"),
            urllib.error.URLError("fail"),
            self._make_mock_response(200, b"OK"),
        ]

        dispatcher._deliver(wh, "chat.completed", {"msg": "hello"})

        cursor = store._conn.cursor()
        cursor.execute(
            "SELECT attempt FROM webhook_deliveries WHERE webhook_id = ? ORDER BY attempt",
            (wh["id"],),
        )
        rows = cursor.fetchall()
        attempts = [dict(r)["attempt"] for r in rows]
        assert attempts == [1, 2, 3]
        store.close()
