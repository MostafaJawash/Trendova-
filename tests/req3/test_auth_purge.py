"""Moving the expired-revoked-token purge off the request path must not weaken authentication."""
from datetime import datetime, timedelta, timezone
import jwt
import pytest
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.tokens import RevokedToken, purge_expired
from tests.conftest import make_user

BASE = '/api/v1'
pytestmark = pytest.mark.req3_phase1


def _now():
    return datetime.now(timezone.utc)


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def test_logged_out_token_is_still_rejected(client):
    _, h = make_user(client, 'revoked@example.com')
    assert client.get(BASE + '/auth/me', headers=h).status_code == 200
    assert client.post(BASE + '/auth/logout', headers=h).status_code == 204
    assert client.get(BASE + '/auth/me', headers=h).status_code == 401


def test_revoked_unexpired_token_survives_a_purge(client):
    _, h = make_user(client, 'survive@example.com')
    assert client.post(BASE + '/auth/logout', headers=h).status_code == 204
    with SessionLocal() as db:
        purge_expired(db)  # the token is revoked but not expired: must stay revoked
    assert client.get(BASE + '/auth/me', headers=h).status_code == 401


def test_expired_token_is_rejected_by_its_own_exp(client):
    """No revoked_tokens row exists and no purge ever ran: `exp` alone must reject it."""
    user, _ = make_user(client, 'expired@example.com')
    token = jwt.encode(
        {'sub': str(user['id']), 'role': 'user', 'jti': 'expired-token-1', 'iat': _now() - timedelta(hours=2), 'exp': _now() - timedelta(hours=1)},
        settings.secret_key, algorithm='HS256')
    r = client.get(BASE + '/auth/me', headers={'Authorization': 'Bearer ' + token})
    assert r.status_code == 401
    with SessionLocal() as db:
        assert db.get(RevokedToken, 'expired-token-1') is None


def test_background_purge_deletes_only_expired_revoked_tokens(client):
    with SessionLocal() as db:
        db.add_all([
            RevokedToken(jti='old-1', expires_at=_naive(_now() - timedelta(hours=3))),
            RevokedToken(jti='old-2', expires_at=_naive(_now() - timedelta(seconds=5))),
            RevokedToken(jti='fresh-1', expires_at=_naive(_now() + timedelta(hours=1))),
            RevokedToken(jti='fresh-2', expires_at=_naive(_now() + timedelta(days=1))),
        ])
        db.commit()
        assert purge_expired(db) == 2
        assert {t.jti for t in db.query(RevokedToken).all()} == {'fresh-1', 'fresh-2'}
        assert purge_expired(db) == 0  # idempotent


def test_requests_no_longer_purge_and_use_two_auth_statements(client, sql_counter):
    _, h = make_user(client, 'nopurge@example.com')
    with SessionLocal() as db:
        db.add(RevokedToken(jti='stale-row', expires_at=_naive(_now() - timedelta(hours=1))))
        db.commit()
    before = sql_counter.count
    assert client.get(BASE + '/auth/me', headers=h).status_code == 200
    assert sql_counter.count - before == 2  # revocation lookup + user lookup, no DELETE
    assert not any(s.lstrip().upper().startswith('DELETE') for s in sql_counter.statements)
    with SessionLocal() as db:
        assert db.get(RevokedToken, 'stale-row') is not None  # only the background task deletes
