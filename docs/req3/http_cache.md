# HTTP cache: ETag / 304 (Requirement 3)

Implemented as an explicit helper, `app/core/http_cache.py::respond`, called by the product list and product detail
endpoints. It is **not** a global middleware, so an order, a profile or a write response can never receive a validator by accident.
Flag: `ETAG_ENABLED`.

## Headers

| | |
|---|---|
| `ETag` | strong: `"` + first 32 hex of SHA-256 of the **exact response body bytes** + `"` |
| `Cache-Control` | `private, no-cache` for authenticated endpoints (all current product endpoints need a bearer token); the helper also supports `public, no-cache` for public endpoints |
| `Vary` | `Accept-Encoding, Authorization` (authenticated) / `Accept-Encoding` (public) |
| `X-Cache` | `HIT`/`MISS`/`BYPASS` (server cache, see `cache_policy.md`) |

`no-cache` means "you may store it, but ask me every time". The client repeats the request with `If-None-Match: "<etag>"`;
the server answers **304 Not Modified with an empty body** (still carrying `ETag` and `Cache-Control`) when the body would be identical.
`If-None-Match` handling follows RFC 9110 weak comparison: several values (`"a", "b"`), `*`, and the `W/"..."` form all work.

## Where the ETag comes from

* **List page:** computed **once, at cache fill**, and stored in Redis together with the body (`etag \n ids \n body`). A HIT costs no hashing.
* If the page has to be personalised (the user has favourites on it) or enriched (`include_stock=true`), the body differs from the cached
  one, so its own ETag = hash of the bytes actually sent.
* **Detail:** the response always contains fresh stock and the user's `is_favorite`, so the ETag is the hash of the final bytes of
  each request. A 304 therefore proves that *the whole response including the stock* is unchanged: stock is never served stale through a 304.
  (This saves bandwidth; the server still does the work of building the response.)

## GZip

`GZipMiddleware` (responses ≥ 1000 bytes when the client sends `Accept-Encoding: gzip`) wraps the app. The ETag is the hash of the
**uncompressed** body and is identical with or without compression; the 304 path has no body, so nothing is compressed.
Verified by `tests/req3/test_etag.py::test_etag_is_computed_on_the_uncompressed_body_with_gzip` and by hand:

```bash
curl -si -H "Authorization: Bearer $T" -H "Accept-Encoding: gzip" "http://localhost:8000/api/v1/products?category=3&limit=20" --compressed -o /dev/null -D -
curl -si -H "Authorization: Bearer $T" "http://localhost:8000/api/v1/products?category=3&limit=20" -o /dev/null -D -
```

## Sequence

```
1. GET /products/42                         -> 200  ETag: "a1b2..."  Cache-Control: private, no-cache  (body N bytes)
2. GET /products/42  If-None-Match: "a1b2..." -> 304  ETag: "a1b2..."  (0 body bytes)
3. admin: PUT /products/42  price=...        -> 200   (DB commit, then cache invalidation)
4. GET /products/42  If-None-Match: "a1b2..." -> 200  ETag: "c3d4..."  (new price, new body)   <- the old validator no longer matches
5. GET /products/42  If-None-Match: "c3d4..." -> 304
```

Tests: `tests/req3/test_etag.py` (same ETag → 304; old ETag after an admin edit → 200 + new ETag; new ETag → 304; `*`, weak, multi-value;
gzip; no ETag on `/orders`, `/auth/me`, `/favorites`). k6: `loadtest/k6/freshness.js` scenario `browser` remembers the ETag per URL and reports
`not_modified_ratio`.
