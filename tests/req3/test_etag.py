"""ETag / If-None-Match on the product endpoints (Requirement 3). Live: final app with ETAG_ENABLED."""
import gzip
import hashlib
import pytest
from tests.req3 import live

pytestmark = [pytest.mark.req3_phase2, pytest.mark.skipif(not live.BASE, reason='E2E_BASE_URL not set (needs the compose stack)')]


@pytest.fixture(scope='module')
def api():
    return live.Api()


@pytest.fixture
def world(api):
    admin = api.admin(); pid, cat = api.new_product(admin, price='10.00')
    _, user = api.new_user()
    return {'api': api, 'admin': admin, 'pid': pid, 'cat': cat, 'user': user}


def _with(h, **extra):
    return {**h, **extra}


@pytest.mark.parametrize('kind', ['list', 'detail'])
def test_same_etag_gives_304_with_empty_body_and_headers(world, kind):
    c = world['api'].c
    url = f"/products?category={world['cat']}&limit=20" if kind == 'list' else f"/products/{world['pid']}"
    r1 = c.get(url, headers=world['user'])
    etag = r1.headers['etag']
    assert r1.status_code == 200 and etag.startswith('"') and not etag.startswith('W/')
    assert r1.headers['cache-control'] == 'private, no-cache'                      # authenticated endpoint
    assert 'Accept-Encoding' in r1.headers['vary'] and 'Authorization' in r1.headers['vary']
    # strong ETag = hash of the exact response bytes
    assert etag == '"' + hashlib.sha256(r1.content).hexdigest()[:32] + '"'
    r2 = c.get(url, headers=_with(world['user'], **{'If-None-Match': etag}))
    assert r2.status_code == 304 and r2.content == b''
    assert r2.headers['etag'] == etag and r2.headers['cache-control'] == 'private, no-cache'
    for header in (f'"nope", {etag}', '*', 'W/' + etag):                            # several values, star, weak form
        assert c.get(url, headers=_with(world['user'], **{'If-None-Match': header})).status_code == 304, header
    assert c.get(url, headers=_with(world['user'], **{'If-None-Match': '"other"'})).status_code == 200


@pytest.mark.parametrize('kind', ['list', 'detail'])
def test_old_etag_after_admin_edit_returns_200_and_new_etag_then_304(world, kind):
    a, c = world['api'], world['api'].c
    url = f"/products?category={world['cat']}&limit=20" if kind == 'list' else f"/products/{world['pid']}"
    old = c.get(url, headers=world['user']).headers['etag']
    a.edit_price(world['admin'], world['pid'], '99.50')
    r = c.get(url, headers=_with(world['user'], **{'If-None-Match': old}))
    assert r.status_code == 200 and r.headers['etag'] != old and '99.50' in r.text
    r2 = c.get(url, headers=_with(world['user'], **{'If-None-Match': r.headers['etag']}))
    assert r2.status_code == 304


def test_etag_is_computed_on_the_uncompressed_body_with_gzip(world):
    c = world['api'].c
    url = f"/products?category={world['cat']}&limit=20"
    for i in range(3):   # make the page > 1000 bytes so GZip kicks in
        world['api'].new_product(world['admin'], category_id=world['cat'])
    plain = c.get(url, headers=_with(world['user'], **{'Accept-Encoding': 'identity'}))
    zipped = c.get(url, headers=_with(world['user'], **{'Accept-Encoding': 'gzip'}))
    assert zipped.headers.get('content-encoding') == 'gzip' and 'content-encoding' not in plain.headers
    assert zipped.headers['etag'] == plain.headers['etag']                         # same validator for both encodings
    assert plain.headers['etag'] == '"' + hashlib.sha256(plain.content).hexdigest()[:32] + '"'
    assert zipped.content == plain.content                                         # httpx decoded the gzip body
    nm = c.get(url, headers=_with(world['user'], **{'Accept-Encoding': 'gzip', 'If-None-Match': plain.headers['etag']}))
    assert nm.status_code == 304 and nm.content == b''


def test_validators_are_not_added_to_personal_or_write_responses(world):
    c = world['api'].c
    for url in ('/orders', '/auth/me', '/favorites'):
        r = c.get(url, headers=world['user'])
        assert 'etag' not in r.headers and r.headers['cache-control'] == 'no-store', url
