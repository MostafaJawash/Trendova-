// Requirement 3 - freshness + browser-like scenarios (separate from main.js, whose profile must stay unchanged).
//
//  ONLY=freshness : an admin updates a product price, then a CUSTOMER reads the product (detail AND the list page
//                   that contains it) right away. Any answer that does not show the new price is a stale read.
//                   Custom counter `stale_reads` MUST be 0 (cache + read replica must never serve an old price).
//  ONLY=browser   : browser-like client. It remembers the ETag per URL and sends If-None-Match on the next visit.
//                   Custom rate `not_modified_ratio` = share of responses that were 304 (needs ETAG_ENABLED).
// Both (default) run one after the other. Test data is created in setup() and named `req3_k6_*`; scripts/req3_cleanup.py
// removes it (it never counts towards seed numbers or benchmark runs).
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://app:8000/api/v1';
const LABEL = __ENV.RUN_LABEL || 'fresh';
const ONLY = __ENV.ONLY || '';
const QUICK = __ENV.QUICK === '1';
const ADMIN_EMAIL = __ENV.ADMIN_EMAIL || 'admin@example.com';
const ADMIN_PASSWORD = __ENV.ADMIN_PASSWORD || 'ChangeMe123!';
const CUSTOMER_PASSWORD = __ENV.CUSTOMER_PASSWORD || 'LoadTest123!';
const WRITERS = 4;                          // fresh-scenario VUs, one product each
const DUR = QUICK ? 15 : 30;
const J = { 'Content-Type': 'application/json' };

export const stale_reads = new Counter('stale_reads');
export const fresh_checks = new Counter('fresh_checks');
export const not_modified_ratio = new Rate('not_modified_ratio');
export const browser_bytes = new Counter('browser_bytes');
export const read_after_write_ms = new Trend('read_after_write_ms', true);

const scenarios = {};
let start = 0;
if (!ONLY || ONLY === 'freshness') {
  scenarios.freshness = { executor: 'constant-vus', exec: 'freshScenario', vus: WRITERS, duration: DUR + 's', startTime: start + 's', gracefulStop: '5s' };
  start += DUR + 3;
}
if (!ONLY || ONLY === 'browser') {
  scenarios.browser = { executor: 'constant-vus', exec: 'browserScenario', vus: QUICK ? 5 : 20, duration: DUR + 's', startTime: start + 's', gracefulStop: '5s' };
}
export const options = {
  scenarios,
  thresholds: { stale_reads: ['count==0'] },   // hard requirement of the freshness proof
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  setupTimeout: '120s',
};

export function setup() {
  const login = (email, password) => {
    const r = http.post(`${BASE_URL}/auth/login`, JSON.stringify({ email, password }), { headers: J });
    if (r.status !== 200) throw new Error(`login ${email}: ${r.status} ${r.body}`);
    return r.json('access_token');
  };
  const admin = login(ADMIN_EMAIL, ADMIN_PASSWORD);
  const customer = login('customer001@loadtest.example', CUSTOMER_PASSWORD);
  const A = { Authorization: `Bearer ${admin}` };
  const suffix = Math.random().toString(36).slice(2, 8);
  const cat = http.post(`${BASE_URL}/categories`, JSON.stringify({ name: `req3_k6_${suffix}`, description: 'req3 k6 freshness' }), { headers: { ...A, ...J } });
  if (cat.status !== 201) throw new Error(`category: ${cat.status} ${cat.body}`);
  const categoryId = cat.json('id');
  const products = [];
  for (let i = 0; i < WRITERS; i++) {
    const r = http.post(`${BASE_URL}/products`, { name: `req3_k6_${suffix}_${i}`, description: 'freshness probe', price: '10.00', category_id: String(categoryId), initial_quantity: '5' }, { headers: A });
    if (r.status !== 201) throw new Error(`product: ${r.status} ${r.body}`);
    products.push(r.json('id'));
  }
  // browser-like URLs: a few list pages and details from the seeded catalog (read-only)
  return { admin, customer, categoryId, products };
}

const H = (t) => ({ Authorization: `Bearer ${t}` });
const money = (n) => (Math.round(n * 100) / 100).toFixed(2);

export function freshScenario(data) {
  const idx = (exec.vu.idInTest - 1) % data.products.length;
  const pid = data.products[idx];
  const price = money(11 + ((exec.vu.iterationInScenario * 7 + idx * 3) % 900) + exec.vu.iterationInScenario / 1000);
  // warm the caches for this product so the update must invalidate something real
  http.get(`${BASE_URL}/products/${pid}`, { headers: H(data.customer) });
  http.get(`${BASE_URL}/products?category=${data.categoryId}&limit=100`, { headers: H(data.customer) });
  const up = http.put(`${BASE_URL}/products/${pid}`, { price }, { headers: H(data.admin), tags: { endpoint: 'fresh_update' } });
  if (!check(up, { 'update 200': (r) => r.status === 200 })) return;
  const t0 = Date.now();
  const d = http.get(`${BASE_URL}/products/${pid}`, { headers: H(data.customer), tags: { endpoint: 'fresh_detail' } });
  const l = http.get(`${BASE_URL}/products?category=${data.categoryId}&limit=100`, { headers: H(data.customer), tags: { endpoint: 'fresh_list' } });
  read_after_write_ms.add(Date.now() - t0);
  fresh_checks.add(2);
  if (d.status !== 200 || parseFloat(d.json('price')) !== parseFloat(price)) stale_reads.add(1);
  const item = l.status === 200 ? l.json('items').find((x) => x.id === pid) : null;
  if (!item || parseFloat(item.price) !== parseFloat(price)) stale_reads.add(1);
}

// ---- browser-like: remember ETag per URL, send If-None-Match ----
const ETAGS = {};
export function browserScenario(data) {
  const hot = [1, 2, 3, 4, 5, 6, 7, 8];
  const urls = [];
  for (const c of hot) urls.push(`/products?category=${c}&limit=20&page=1`);
  for (const p of hot) urls.push(`/products/${p}`);
  const url = urls[(exec.vu.iterationInScenario + exec.vu.idInTest) % urls.length];
  const known = ETAGS[url];
  const headers = { ...H(data.customer) };
  if (known) headers['If-None-Match'] = known;
  const r = http.get(`${BASE_URL}${url}`, { headers, tags: { endpoint: 'browser' } });
  check(r, { 'browser 200/304': (x) => x.status === 200 || x.status === 304 });
  not_modified_ratio.add(r.status === 304);
  browser_bytes.add(r.body ? r.body.length : 0);
  const et = r.headers['Etag'] || r.headers['ETag'];
  if (r.status === 200 && et) ETAGS[url] = et;
}

function m(data, name, key) { const x = data.metrics[name]; return x && x.values ? x.values[key] : null; }
export function handleSummary(data) {
  const out = {
    label: LABEL, only: ONLY || null, quick: QUICK, generated_at: new Date().toISOString(),
    stale_reads: m(data, 'stale_reads', 'count') || 0,
    fresh_checks: m(data, 'fresh_checks', 'count') || 0,
    not_modified_ratio: m(data, 'not_modified_ratio', 'rate'),
    browser_bytes: m(data, 'browser_bytes', 'count'),
    read_after_write_p50_ms: m(data, 'read_after_write_ms', 'med'),
    read_after_write_p99_ms: m(data, 'read_after_write_ms', 'p(99)'),
    http_reqs: m(data, 'http_reqs', 'count'),
    http_req_failed_rate: m(data, 'http_req_failed', 'rate'),
  };
  return { [`/loadtest/results/${LABEL}.json`]: JSON.stringify(out, null, 2) };
}
