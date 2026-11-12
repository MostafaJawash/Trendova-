"""HTTP-facing product reads: Redis cache-aside, ETag/304 and the opt-in `include_stock` merge (Requirement 3).

Rules (see docs/req3/cache_policy.md):
* only the STATIC part of a product / list page is cached (name, description, price, category ...);
* stock is NEVER cached: it is fetched from the warehouse on every request and merged into the response;
* `is_favorite` is user-specific: never cached, merged per request from ONE query on the PRIMARY;
* cache fills read from the PRIMARY `db` (a lagging replica would store stale data for a whole TTL);
* ETag = hash of the exact bytes sent (computed at fill time for plain list pages, per request when fresh data is merged).
"""
import json
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core import cache, http_cache, redis as rds
from app.core.config import settings
from app.core.database import route_read, SessionReplica
from app.core.errors import AppError
from app.integrations.inventory import gateway as inventory_gateway
from app.integrations.inventory.gateway import InventoryUnavailableError
from app.modules.products import repository as repo, service
from app.modules.products.schemas import ProductPage


def stock_for(ids, mode=None):
    """{product_id: {'quantity','status'}} straight from the warehouse. ONE GetStockBatch call (mode 'batch');
    the per-item path ('naive') exists only as a benchmark/test variant. Same failure behaviour as the detail
    endpoint: gateway error (2 s deadline) -> quantity None / status 'unavailable', the request still succeeds."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    try:
        quantities = inventory_gateway.gateway.get_quantities_naive(ids) if (mode or settings.stock_mode) == 'naive' else inventory_gateway.gateway.get_quantities(ids)
        return {i: {'quantity': quantities.get(i, 0), 'status': 'available'} for i in ids}
    except InventoryUnavailableError:
        return {i: {'quantity': None, 'status': 'unavailable'} for i in ids}


def list_response(request: Request, db, user_id, page, limit, include_stock, filters, stock_mode=None):
    """Cache-aside list page + per-request merge of favorites (and stock when include_stock=true)."""
    lo, hi = filters.get('min_price'), filters.get('max_price')
    if lo is not None and hi is not None and lo > hi:
        raise AppError(422, 'VALIDATION_ERROR', 'minPrice cannot exceed maxPrice')
    use_cache = cache.enabled()
    use_replica = (not use_cache) and bool(filters.get('search')) and SessionReplica is not None

    def build():
        rdb, owned = route_read(user_id, products=True, primary=db) if use_replica else (db, False)
        try:
            result = service.products(rdb, None, page, limit, **dict(filters))   # user_id None: static body, no favorites
        finally:
            if owned:
                rdb.close()
        content = ProductPage.model_validate(result).model_dump(mode='json')
        body = JSONResponse(content).body
        return cache.pack(cache.etag_of(body), [it['id'] for it in content['items']], body)

    status = None
    if use_cache:
        version = cache.list_version()
        if version is None:   # Redis unreachable: serve from the DB, never fail
            cache.stat('bypass'); cache.stat('errors')
            raw, status = build(), 'BYPASS'
        else:
            params = {'page': page, 'limit': limit, **{k: str(v) for k, v in filters.items() if v is not None}}
            key = rds.key(f'products:list:v{version}:{cache.params_hash(params)}')
            raw, status = cache.get_or_fill(key, cache.jitter(settings.cache_list_ttl_seconds), build)
    else:
        raw = build()
    etag, ids, body = cache.unpack(raw)
    favorites = repo.favorite_flags(db, user_id, ids) if ids else set()
    if favorites or include_stock:
        content = json.loads(body)
        stock = stock_for(ids, stock_mode) if include_stock else {}
        for item in content['items']:
            if item['id'] in favorites:
                item['is_favorite'] = True
            if include_stock:
                item['stock'] = stock[item['id']]
        body = JSONResponse(content).body
        etag = cache.etag_of(body)   # the body now holds per-user / fresh data -> its own validator
    return http_cache.respond(request, body, etag, cache_status=status)


def detail_response(request: Request, db, product_id, user_id):
    """Static product part from Redis (key products:detail:{id}); is_favorite and stock are merged fresh every time."""
    status = None

    def build():
        p = repo.get_product(db, product_id)
        if p is None:
            return b''   # not found: never cached
        static = {'id': p.id, 'category_id': p.category_id, 'name': p.name, 'description': p.description, 'price': str(p.price),
                  'image_url': p.image_url, 'category': {'id': p.category.id, 'name': p.category.name} if p.category else None}
        return str(cache.catver()).encode() + b'\n' + json.dumps(static).encode()

    if cache.enabled():
        current_catver = cache.catver()
        raw, status = cache.get_or_fill(rds.key(f'products:detail:{product_id}'), cache.jitter(settings.cache_detail_ttl_seconds), build,
                                        valid=lambda r: int(r.split(b'\n', 1)[0]) == current_catver)
    else:
        raw = build()
    if not raw:
        raise AppError(404, 'NOT_FOUND', 'Product not found')
    static = json.loads(raw.split(b'\n', 1)[1])
    out = {k: static[k] for k in ('id', 'category_id', 'name', 'description', 'price', 'image_url')}
    out['is_favorite'] = product_id in repo.favorite_flags(db, user_id, [product_id])
    out['category'] = static['category']
    try:   # fresh stock on EVERY request (Requirement 2 race-condition guarantee depends on it)
        out['stock'] = {'quantity': inventory_gateway.gateway.get_quantity(product_id), 'status': 'available'}
    except InventoryUnavailableError:
        out['stock'] = {'quantity': None, 'status': 'unavailable'}
    body = JSONResponse(out).body
    return http_cache.respond(request, body, cache.etag_of(body), cache_status=status)
