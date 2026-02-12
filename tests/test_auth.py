"""auth 모듈 테스트"""
import os
import sys
import pytest
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openclaw.auth import UserStore, UserContext, AuthMiddleware, User, DEFAULT_USER


class TestUserContext:
    """UserContext 데이터클래스 테스트"""

    def test_default_user_constants(self):
        """DEFAULT_USER 상수 확인"""
        assert DEFAULT_USER.user_id == "default"
        assert DEFAULT_USER.username == "default"
        assert DEFAULT_USER.role == "admin"
        assert DEFAULT_USER.max_daily_calls == 100

    def test_user_context_frozen(self):
        """UserContext 불변성 확인"""
        ctx = UserContext(user_id="u1", username="test", role="user")
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            ctx.user_id = "changed"

    def test_user_context_creation(self):
        """UserContext 생성 확인"""
        ctx = UserContext(
            user_id="test_id",
            username="testuser",
            role="user",
            max_daily_calls=200
        )
        assert ctx.user_id == "test_id"
        assert ctx.username == "testuser"
        assert ctx.role == "user"
        assert ctx.max_daily_calls == 200


class TestUserStore:
    """UserStore CRUD 테스트"""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test_auth.db")
        s = UserStore(db_path=db_path)
        yield s
        s.close()

    def test_create_user(self, store):
        """사용자 생성"""
        user, api_key = store.create_user("testuser")
        assert user.username == "testuser"
        assert user.role == "user"
        assert api_key.startswith("flux_")
        assert len(api_key) == 69  # flux_ + 64 hex chars
        assert user.api_key_prefix == api_key[:13]  # flux_ + first 8 hex
        assert user.is_active is True
        assert user.max_daily_calls == 100

    def test_create_admin(self, store):
        """관리자 생성"""
        user, _ = store.create_user("admin", role="admin")
        assert user.role == "admin"

    def test_create_readonly(self, store):
        """읽기전용 사용자 생성"""
        user, _ = store.create_user("readonly", role="readonly")
        assert user.role == "readonly"

    def test_create_user_with_display_name(self, store):
        """display_name 포함하여 사용자 생성"""
        user, _ = store.create_user("testuser", display_name="Test User")
        assert user.display_name == "Test User"

    def test_create_user_with_custom_daily_calls(self, store):
        """커스텀 일일 호출 제한으로 사용자 생성"""
        user, _ = store.create_user("testuser", max_daily_calls=500)
        assert user.max_daily_calls == 500

    def test_duplicate_username(self, store):
        """중복 사용자명 거부"""
        store.create_user("dupe")
        with pytest.raises(sqlite3.IntegrityError):
            store.create_user("dupe")

    def test_create_user_empty_username(self, store):
        """빈 사용자명 거부"""
        with pytest.raises(ValueError, match="Username must not be empty"):
            store.create_user("")
        with pytest.raises(ValueError, match="Username must not be empty"):
            store.create_user("   ")

    def test_create_user_invalid_role(self, store):
        """잘못된 역할 거부"""
        with pytest.raises(ValueError, match="Invalid role"):
            store.create_user("testuser", role="superuser")

    def test_get_user(self, store):
        """사용자 조회"""
        user, _ = store.create_user("lookup")
        found = store.get_user(user.id)
        assert found is not None
        assert found.username == "lookup"
        assert found.id == user.id

    def test_get_nonexistent(self, store):
        """존재하지 않는 사용자 조회"""
        result = store.get_user("nonexistent")
        assert result is None

    def test_get_user_by_username(self, store):
        """사용자명으로 사용자 조회"""
        user, _ = store.create_user("lookupname")
        found = store.get_user_by_username("lookupname")
        assert found is not None
        assert found.id == user.id
        assert found.username == "lookupname"

    def test_get_user_by_username_nonexistent(self, store):
        """존재하지 않는 사용자명 조회"""
        result = store.get_user_by_username("nonexistent")
        assert result is None

    def test_authenticate_api_key(self, store):
        """API 키 인증"""
        user, api_key = store.create_user("authtest")
        found = store.authenticate_api_key(api_key)
        assert found is not None
        assert found.id == user.id
        assert found.username == "authtest"

    def test_authenticate_invalid_key(self, store):
        """잘못된 API 키"""
        result = store.authenticate_api_key("flux_invalid_key_000000000000000000000000000000000000000000000000000000000000")
        assert result is None

    def test_authenticate_wrong_format(self, store):
        """잘못된 형식의 키"""
        result = store.authenticate_api_key("not_a_valid_key")
        assert result is None

    def test_authenticate_wrong_prefix(self, store):
        """잘못된 prefix의 키"""
        result = store.authenticate_api_key("wrong_1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        assert result is None

    def test_authenticate_wrong_length(self, store):
        """잘못된 길이의 키"""
        result = store.authenticate_api_key("flux_short")
        assert result is None

    def test_authenticate_empty_key(self, store):
        """빈 키"""
        result = store.authenticate_api_key("")
        assert result is None

    def test_list_users(self, store):
        """사용자 목록"""
        store.create_user("user1")
        store.create_user("user2")
        store.create_user("user3")
        users = store.list_users()
        assert len(users) == 3
        # 최신순 정렬 확인
        assert users[0].username == "user3"

    def test_list_users_limit(self, store):
        """사용자 목록 제한"""
        for i in range(5):
            store.create_user(f"user{i}")
        users = store.list_users(limit=3)
        assert len(users) == 3

    def test_list_users_excludes_inactive(self, store):
        """비활성화된 사용자 제외"""
        user1, _ = store.create_user("active")
        user2, _ = store.create_user("inactive")
        store.deactivate_user(user2.id)

        users = store.list_users()
        assert len(users) == 1
        assert users[0].username == "active"

    def test_deactivate_user(self, store):
        """사용자 비활성화"""
        user, api_key = store.create_user("deactiveme")
        assert store.deactivate_user(user.id)

        # 비활성화된 사용자는 인증 불가
        result = store.authenticate_api_key(api_key)
        assert result is None

        # get_user로는 조회 가능하지만 is_active=False
        retrieved = store.get_user(user.id)
        assert retrieved is not None
        assert retrieved.is_active is False

    def test_deactivate_nonexistent(self, store):
        """존재하지 않는 사용자 비활성화"""
        result = store.deactivate_user("nonexistent")
        assert result is False

    def test_deactivate_already_inactive(self, store):
        """이미 비활성화된 사용자 재비활성화"""
        user, _ = store.create_user("user")
        assert store.deactivate_user(user.id) is True
        assert store.deactivate_user(user.id) is False  # 이미 비활성화됨

    def test_rotate_api_key(self, store):
        """API 키 갱신"""
        user, old_key = store.create_user("rotatetest")
        new_user, new_key = store.rotate_api_key(user.id)

        assert new_user is not None
        assert new_key != old_key
        assert new_key.startswith("flux_")
        assert len(new_key) == 69

        # 이전 키는 더 이상 작동하지 않음
        assert store.authenticate_api_key(old_key) is None

        # 새 키는 작동함
        authenticated = store.authenticate_api_key(new_key)
        assert authenticated is not None
        assert authenticated.id == user.id

    def test_rotate_nonexistent(self, store):
        """존재하지 않는 사용자 키 갱신"""
        user, key = store.rotate_api_key("nonexistent")
        assert user is None
        assert key is None

    def test_rotate_inactive_user(self, store):
        """비활성화된 사용자 키 갱신"""
        user, _ = store.create_user("inactive")
        store.deactivate_user(user.id)

        result_user, result_key = store.rotate_api_key(user.id)
        assert result_user is None
        assert result_key is None

    def test_update_user_display_name(self, store):
        """display_name 업데이트"""
        user, _ = store.create_user("testuser")
        updated = store.update_user(user.id, display_name="New Name")

        assert updated is not None
        assert updated.display_name == "New Name"
        assert updated.username == "testuser"  # 다른 필드는 유지

    def test_update_user_role(self, store):
        """역할 업데이트"""
        user, _ = store.create_user("testuser", role="user")
        updated = store.update_user(user.id, role="admin")

        assert updated is not None
        assert updated.role == "admin"

    def test_update_user_invalid_role(self, store):
        """잘못된 역할로 업데이트"""
        user, _ = store.create_user("testuser")
        with pytest.raises(ValueError, match="Invalid role"):
            store.update_user(user.id, role="invalid")

    def test_update_user_max_daily_calls(self, store):
        """일일 호출 제한 업데이트"""
        user, _ = store.create_user("testuser")
        updated = store.update_user(user.id, max_daily_calls=500)

        assert updated is not None
        assert updated.max_daily_calls == 500

    def test_update_user_multiple_fields(self, store):
        """여러 필드 동시 업데이트"""
        user, _ = store.create_user("testuser")
        updated = store.update_user(
            user.id,
            display_name="Updated Name",
            role="admin",
            max_daily_calls=1000
        )

        assert updated is not None
        assert updated.display_name == "Updated Name"
        assert updated.role == "admin"
        assert updated.max_daily_calls == 1000

    def test_update_user_nonexistent(self, store):
        """존재하지 않는 사용자 업데이트"""
        result = store.update_user("nonexistent", display_name="test")
        assert result is None

    def test_update_user_no_changes(self, store):
        """변경사항 없이 업데이트"""
        user, _ = store.create_user("testuser")
        updated = store.update_user(user.id)

        assert updated is not None
        assert updated.username == user.username

    def test_wal_mode(self, store):
        """WAL 모드 확인"""
        result = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

    def test_foreign_keys_enabled(self, store):
        """외래 키 제약 활성화 확인"""
        result = store._conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1


class TestAuthMiddleware:
    """AuthMiddleware 테스트"""

    @pytest.fixture
    def middleware(self, tmp_path):
        db_path = str(tmp_path / "test_auth_mw.db")
        store = UserStore(db_path=db_path)
        mw = AuthMiddleware(store)
        yield mw
        store.close()

    def test_authenticate_valid_key(self, middleware):
        """유효한 키로 인증"""
        user, api_key = middleware._store.create_user("mwtest")
        ctx = middleware.authenticate(api_key)

        assert ctx is not None
        assert ctx.user_id == user.id
        assert ctx.username == "mwtest"
        assert ctx.role == "user"
        assert ctx.max_daily_calls == 100

    def test_authenticate_invalid_key(self, middleware):
        """잘못된 키로 인증 실패"""
        ctx = middleware.authenticate("invalid_key")
        assert ctx is None

    def test_authenticate_empty_key(self, middleware):
        """빈 키로 인증 실패"""
        ctx = middleware.authenticate("")
        assert ctx is None

    def test_authenticate_deactivated_user(self, middleware):
        """비활성화된 사용자 인증 실패"""
        user, api_key = middleware._store.create_user("deactivated")
        middleware._store.deactivate_user(user.id)

        ctx = middleware.authenticate(api_key)
        assert ctx is None

    def test_authenticate_with_interface(self, middleware):
        """인터페이스 정보 포함 인증"""
        user, api_key = middleware._store.create_user("webuser")
        ctx = middleware.authenticate(api_key, interface="web")

        assert ctx is not None
        assert ctx.user_id == user.id

    def test_authenticate_with_source_ip(self, middleware):
        """IP 정보 포함 인증"""
        user, api_key = middleware._store.create_user("ipuser")
        ctx = middleware.authenticate(api_key, source_ip="192.168.1.1")

        assert ctx is not None
        assert ctx.user_id == user.id

    def test_require_role_admin(self, middleware):
        """관리자 역할 확인"""
        admin_ctx = UserContext(user_id="a", username="admin", role="admin")
        user_ctx = UserContext(user_id="u", username="user", role="user")
        readonly_ctx = UserContext(user_id="r", username="readonly", role="readonly")

        assert middleware.require_role(admin_ctx, "admin") is True
        assert middleware.require_role(user_ctx, "admin") is False
        assert middleware.require_role(readonly_ctx, "admin") is False

    def test_require_role_user(self, middleware):
        """사용자 역할 확인 (admin도 통과)"""
        admin_ctx = UserContext(user_id="a", username="admin", role="admin")
        user_ctx = UserContext(user_id="u", username="user", role="user")
        readonly_ctx = UserContext(user_id="r", username="readonly", role="readonly")

        assert middleware.require_role(admin_ctx, "user") is True
        assert middleware.require_role(user_ctx, "user") is True
        assert middleware.require_role(readonly_ctx, "user") is False

    def test_require_role_readonly(self, middleware):
        """읽기전용 역할 확인 (모든 역할 통과)"""
        admin_ctx = UserContext(user_id="a", username="admin", role="admin")
        user_ctx = UserContext(user_id="u", username="user", role="user")
        readonly_ctx = UserContext(user_id="r", username="readonly", role="readonly")

        assert middleware.require_role(admin_ctx, "readonly") is True
        assert middleware.require_role(user_ctx, "readonly") is True
        assert middleware.require_role(readonly_ctx, "readonly") is True

    def test_require_role_invalid_role(self, middleware):
        """잘못된 역할 요구 (거부)"""
        ctx = UserContext(user_id="u", username="user", role="user")
        # 존재하지 않는 역할 요구 시 False 반환
        assert middleware.require_role(ctx, "superadmin") is False

    def test_check_user_rate_limit_without_core(self, middleware):
        """core 모듈 없이 rate limit 체크 (항상 True)"""
        ctx = UserContext(user_id="u", username="user", role="user")
        # core.check_daily_limit이 없으면 True 반환
        result = middleware.check_user_rate_limit(ctx)
        assert result is True

    def test_middleware_with_audit_logger(self, tmp_path):
        """audit logger 포함 미들웨어"""
        db_path = str(tmp_path / "test_auth_audit.db")
        store = UserStore(db_path=db_path)

        # Mock audit logger
        audit_events = []

        def mock_audit_logger(event, **kwargs):
            audit_events.append({"event": event, "kwargs": kwargs})

        mw = AuthMiddleware(store, audit_logger=mock_audit_logger)

        user, api_key = store.create_user("audituser")
        ctx = mw.authenticate(api_key, interface="cli", source_ip="127.0.0.1")

        assert ctx is not None
        assert len(audit_events) == 1
        assert audit_events[0]["event"] == "auth_success"
        assert audit_events[0]["kwargs"]["username"] == "audituser"

        store.close()

    def test_middleware_audit_on_failure(self, tmp_path):
        """실패 시 audit log 기록"""
        db_path = str(tmp_path / "test_auth_audit_fail.db")
        store = UserStore(db_path=db_path)

        audit_events = []

        def mock_audit_logger(event, **kwargs):
            audit_events.append({"event": event, "kwargs": kwargs})

        mw = AuthMiddleware(store, audit_logger=mock_audit_logger)

        ctx = mw.authenticate("invalid_key", interface="cli")

        assert ctx is None
        assert len(audit_events) == 1
        assert audit_events[0]["event"] == "auth_failure"
        assert audit_events[0]["kwargs"]["reason"] == "invalid_key"

        store.close()


class TestHelperFunctions:
    """헬퍼 함수 테스트"""

    def test_generate_api_key_format(self):
        """API 키 생성 형식 확인"""
        from openclaw.auth import _generate_api_key

        raw_key, key_hash, key_prefix = _generate_api_key()

        assert raw_key.startswith("flux_")
        assert len(raw_key) == 69
        assert len(key_hash) == 64  # SHA-256 hex digest
        assert key_prefix.startswith("flux_")
        assert len(key_prefix) == 13  # flux_ + 8 hex chars

    def test_hash_api_key_consistency(self):
        """API 키 해싱 일관성 확인"""
        from openclaw.auth import _hash_api_key

        test_key = "flux_test_key_1234567890abcdef1234567890abcdef1234567890abcdef1234"
        hash1 = _hash_api_key(test_key)
        hash2 = _hash_api_key(test_key)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest
