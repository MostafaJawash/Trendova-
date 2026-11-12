# دليل دراسة اختبارات المتطلب الثالث (Requirement 3)

> **تنبيه صدق (مهم):** كُتب هذا الدليل **بقراءة الكود والوثائق فقط**. لم يُشغَّل أي أمر أثناء كتابته (لا pytest ولا docker ولا k6 ولا سكربتات).
> لذلك حقل **"الخرج المتوقع"** في كل اختبار هو *"متوقع من قراءة الكود، لم يُشغَّل"*. الأرقام الحقيقية الوحيدة المذكورة هي التي وُجدت أصلًا في ملفات محفوظة،
> ومع كل رقم اسم الملف: `docs/req3/REPORT_AR.md`، `docs/req3/optimization_log.md`، `loadtest/results/*.json`.
> عدد الاختبارات مأخوذ من **عدّ `def test_` وحالات `parametrize` في الشيفرة** (وقورن مع `TESTS_MAP_AR.md`: متطابق، انظر القسم E).
> الرمز `C` في الأوامر يعني: `docker compose --profile test run --rm --no-deps tester`.

---

## A. مقدمة

المتطلب الثالث (الشرائح) يطلب: **(1)** بيانات بحجم واقعي، **(2)** تحليل EXPLAIN للاستعلامات البطيئة وإصلاحها بالفهارس، **(3)** إزالة N+1،
**(4)** قراءة من replica مع ضمان أن "المستخدم يرى ما أنشأه للتو" (read-your-writes)، **(5)** Redis cache مع TTL وحذف/إبطال عند التعديل (وما لا يُخزَّن)،
**(6)** ETag و304، **(7)** اختبار حمل k6 قبل/بعد مع p50/p95/p99، **(8)** "تعديل المنتج يظهر فورًا" رغم الـ cache والـ replica.

| متطلب الشريحة | الاختبارات / السكربتات التي تثبته |
|---|---|
| بيانات بحجم واقعي | `scripts/seed.py` (ليس اختبارًا)، خطوة 0 في `demo_req3.py`، فحص `realistic data volume` في `run_phase1/2.py` |
| EXPLAIN + استعلامات أسرع | `test_n_plus_one.py` (6 اختبارات الخطط الحية)، `scripts/explain_hot.py`، `optimization_log.md` |
| لا N+1 | `test_n_plus_one.py` (4 اختبارات عدّ الاستعلامات)، `test_get_stock_batch.py` (N نداء gRPC ← 1) |
| عدم كسر الاستجابات أثناء التحسين | `test_response_snapshots.py`، `test_keyset.py`، `test_auth_purge.py` |
| قراءة من replica + read-your-writes | `test_replica.py` |
| Redis cache (TTL، إبطال، ما لا يُخزَّن، fail-open، stampede) | `test_cache.py` |
| ETag / 304 | `test_etag.py`، سيناريو `browser` في `loadtest/k6/freshness.js` |
| k6 قبل/بعد مع p50/p95/p99 | `loadtest/k6/main.js`، `scripts/ab_runner.py`، `scripts/bench_final.py` |
| تعديل المنتج يظهر فورًا | `test_freshness.py`، سيناريو `freshness` في `freshness.js` (`stale_reads = 0`) |
| مسار الطلب الكامل عبر خدمة Go الحقيقية | `test_grpc_e2e.py` |

---

## B. كيف تشغّل

> **هذه الأوامر لم تُنفَّذ أثناء كتابة هذا الدليل.**

### حاوية `tester` ولماذا وُجدت
اختبارات المتطلب الثالث "حيّة": تكلّم المكدّس الفعلي (التطبيق، MySQL، الـ replica، Redis، خدمة المخزون Go). بعضها **يوقف** Redis أو الـ replica أو خدمة المخزون ثم يعيد تشغيلها.
الحاوية `tester` (معرّفة في `docker-compose.yml`، profile اسمه `test`، صورتها `Dockerfile.test`) هي صورة التطبيق + **docker CLI** + مقبس docker، فيستطيع الاختبار تنفيذ `docker stop/start`.
الاختبارات داخلها ترى الخدمات بأسمائها (`http://app:8000/api/v1`، `db`، `redis`). **الصورة تحتوي شيفرة التطبيق**، لذلك بعد أي تعديل في `app/` يجب إعادة بنائها (القسم G).

```bash
# إعادة بناء صورة الاختبار (بعد كل تعديل في app/)
docker compose --profile test build tester

# ملف واحد
C tests/req3/test_etag.py -v          # C = docker compose --profile test run --rm --no-deps tester
# مثال كامل:
docker compose --profile test run --rm --no-deps tester tests/req3/test_etag.py -v

# اختبار واحد
docker compose --profile test run --rm --no-deps tester "tests/req3/test_etag.py::test_validators_are_not_added_to_personal_or_write_responses" -v

# حالة واحدة من اختبار parametrized
docker compose --profile test run --rm --no-deps tester "tests/req3/test_keyset.py::test_cursor_walk_equals_offset_pages[sort_by=price&order=asc]" -v

# مرحلة كاملة بالـ marker
docker compose --profile test run --rm --no-deps tester tests -m req3_phase1 -q
docker compose --profile test run --rm --no-deps tester tests -m req3_phase2 -q

# كل اختبارات المتطلب 3
docker compose --profile test run --rm --no-deps tester tests -m "req3_phase1 or req3_phase2" -q -rs

# أو بأمر واحد يشمل تشغيل المكدّس والـ seed واختبار k6 سريع
python scripts/run_phase1.py
python scripts/run_phase2.py
```

**الزمن:** لا أكتب أزمنة لأنها لم تُقرأ من ملف محفوظ لكل ملف على حدة. (الموجود محفوظًا في `docs/req3/STATE.md`: تشغيل `run_phase1.py` وصفته بـ 153 s و`run_phase2.py` بـ 194 s.)

### ما الذي يحتاجه كل نوع
| النوع | الشرط |
|---|---|
| وحدات (sqlite + مخزون وهمي): `test_auth_purge`، `test_response_snapshots`، `test_keyset`، الاختبارات الأربعة الأولى في `test_n_plus_one` | لا شيء (تعمل داخل الحاوية وحدها) |
| حيّة | المتغير `E2E_BASE_URL` (تضبطه حاوية `tester` تلقائيًا = `http://app:8000/api/v1`) وكل الخدمات تعمل |
| خطط EXPLAIN الحية (6 اختبارات في `test_n_plus_one`) | `REQ3_DB_URL` (تضبطه `tester`) وقاعدة بيانات مزروعة بـ seed |
| `test_replica.py::test_no_connection_pool_exhaustion_when_the_replica_is_off` | الحاوية `app-v1` (flags كلها off): `python scripts/ab_build.py up` أو `docker compose --profile ab up -d app-v1`؛ وإلا يُتخطّى (SKIPPED) |
| `test_replica.py` و`test_cache.py` و`test_get_stock_batch.py` (جزء التوقيف) | صلاحية docker socket داخل `tester` (موجودة) |

### كيف تقرأ خرج pytest
* `.` أو `PASSED` (مع `-v`): نجح. `F` أو `FAILED`: فشل، وتحتها أسطر تبدأ بـ **`E `** تبيّن الـ assertion وقيمتيها (المتوقع والفعلي). اقرأ أسطر `E` أولًا.
* `s` أو `SKIPPED`: تخطّي، وبـ `-rs` يُطبع السبب (مثلًا `E2E_BASE_URL not set` أو `app-v1 (flags off) is not running`). التخطّي ليس نجاحًا: يعني أنك لم تثبت شيئًا.
* السطر الأخير: `N passed, M failed, K skipped in T s`.

---

## C. الاختبارات ملفًا ملفًا

(markers: كل ملف يحمل `req3_phase1` أو `req3_phase2`. المرحلة 1 = قاعدة البيانات/N+1/gRPC؛ المرحلة 2 = replica/cache/ETag/freshness.)

### C1. `tests/req3/test_auth_purge.py` — 5 اختبارات — phase1 — وحدات (sqlite)

**السياق:** كانت الاستعلام `DELETE` على جدول `revoked_tokens` ينفَّذ في كل طلب مصادق عليه. نقلناه إلى مهمة خلفية. هذه الاختبارات تثبت أن الأمان لم يضعف.
fixtures: `client` (TestClient على sqlite) و`sql_counter` (عدّاد الاستعلامات نفسه الذي يُظهره التطبيق في `X-DB-Query-Count`).

#### C1.1 `test_logged_out_token_is_still_rejected`
* **الفكرة:** بعد تسجيل الخروج يبقى الرمز مرفوضًا.
* **شو بيقيس:** أن `is_revoked` ما زال يعمل بعد إلغاء حذف الصفوف من مسار الطلب.
* **كيف بيشتغل:** 1) يُنشئ مستخدمًا ويأخذ token. 2) `GET /auth/me` ← 200. 3) `POST /auth/logout` ← 204. 4) `GET /auth/me` ← يجب 401.
* **الخرج المتوقع (متوقع من قراءة الكود، لم يُشغَّل):** `PASSED`.
* **لو فشل:** رمز مسجَّل الخروج يبقى صالحًا = ثغرة أمنية.
* **علاقته بالمتطلب:** شرط لاستعمال replica (إزالة الكتابة من مسار القراءة) دون كسر الأمان.
* **أمر التشغيل:** `C "tests/req3/test_auth_purge.py::test_logged_out_token_is_still_rejected" -v`

#### C1.2 `test_revoked_unexpired_token_survives_a_purge`
* **الفكرة:** التنظيف لا يمسّ الرموز الملغاة التي لم تنتهِ.
* **كيف بيشتغل:** 1) مستخدم + logout (204). 2) يستدعي `purge_expired(db)` مباشرة. 3) `GET /auth/me` ← 401.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** التنظيف يحذف رمزًا ملغى فيعود صالحًا.
* **أمر:** `C "tests/req3/test_auth_purge.py::test_revoked_unexpired_token_survives_a_purge" -v`

#### C1.3 `test_expired_token_is_rejected_by_its_own_exp`
* **الفكرة:** الرمز المنتهي يُرفض بسبب حقل `exp` نفسه دون أي صف في `revoked_tokens`.
* **كيف بيشتغل:** 1) يبني JWT يدويًا بـ `exp` قبل ساعة. 2) `GET /auth/me` ← 401. 3) يتأكد أن `db.get(RevokedToken,'expired-token-1')` هو `None` (لا صف).
* **الخرج المتوقع:** `PASSED`. **لو فشل:** يعني أن الأمان كان يعتمد على الحذف وليس على `exp`.
* **أمر:** `C "tests/req3/test_auth_purge.py::test_expired_token_is_rejected_by_its_own_exp" -v`

#### C1.4 `test_background_purge_deletes_only_expired_revoked_tokens`
* **الفكرة:** المهمة الخلفية تحذف المنتهي فقط.
* **كيف بيشتغل:** 1) يضيف 4 صفوف: اثنان منتهيان (قبل 3 ساعات، قبل 5 ثوانٍ) واثنان صالحان (بعد ساعة، بعد يوم). 2) `purge_expired` يعيد **2**. 3) يبقى `{'fresh-1','fresh-2'}`. 4) استدعاء ثانٍ يعيد **0** (idempotent).
* **الخرج المتوقع:** `PASSED`. **لو فشل:** حذف خاطئ أو تنظيف غير مستقر.
* **أمر:** `C "tests/req3/test_auth_purge.py::test_background_purge_deletes_only_expired_revoked_tokens" -v`

#### C1.5 `test_requests_no_longer_purge_and_use_two_auth_statements`
* **الفكرة:** الطلب العادي لم يعد يكتب، ويستعمل استعلامين فقط للمصادقة.
* **كيف بيشتغل:** 1) صف منتهٍ قديم في الجدول. 2) `GET /auth/me`. 3) يتحقق أن فرق عدّاد الاستعلامات = **2** (فحص الإلغاء + جلب المستخدم). 4) لا يوجد أي `DELETE` بين الاستعلامات. 5) الصف القديم ما زال موجودًا (فقط المهمة الخلفية تحذف).
* **الخرج المتوقع:** `PASSED`. **لو فشل:** عادت كتابة إلى مسار GET (لا يصلح للـ replica) أو زادت الاستعلامات.
* **أمر:** `C "tests/req3/test_auth_purge.py::test_requests_no_longer_purge_and_use_two_auth_statements" -v`

---

### C2. `tests/req3/test_grpc_e2e.py` — 1 اختبار — phase1 — حي (يحتاج `E2E_BASE_URL`)

بدون `E2E_BASE_URL` يُتخطّى (`SKIPPED`، السبب: `E2E_BASE_URL not set (needs the running compose stack)`).

#### C2.1 `test_order_flows_through_the_go_inventory_service`
* **الفكرة:** مسار الطلب الحقيقي عبر خدمة Go (gRPC) وPostgres، وهو ما لا يغطيه المخزون الوهمي.
* **شو بيقيس:** `SetStock`، `GetQuantity`، `Reserve` (نجاح ورفض)، `Release` عند الإلغاء.
* **كيف بيشتغل:** 1) اسم فريد `req3_test_<8 hex>`؛ admin ينشئ منتجًا بمخزون **5**. 2) يسجّل مستخدمًا. 3) المخزون = `{quantity: 5, status: available}`. 4) طلب كمية **2** ← 201، المخزون **3**. 5) طلب كمية **4** ← 409 `INSUFFICIENT_STOCK`، المخزون ما زال **3**. 6) admin يلغي الطلب ← 200، المخزون يعود **5**. 7) `finally`: حذف ناعم للمنتج.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** كسر في عقد المتطلب 2 (عدم البيع الزائد) أو في التكامل مع Go.
* **علاقته بالمتطلب:** يحمي ضمان المتطلب 2 أثناء كل تحسينات المتطلب 3.
* **أمر:** `C tests/req3/test_grpc_e2e.py -v`

---

### C3. `tests/req3/test_response_snapshots.py` — 3 اختبارات — phase1 — وحدات

**فكرة الملف:** لقطات ذهبية (golden files) في `tests/req3/snapshots/` (69 ملفًا) وُلِّدت من الشيفرة **قبل** أي تغيير في الاستعلامات. بعد كل تحسين يجب أن يبقى جسم JSON **نفسه** (الحقول، **ترتيب المفاتيح**، ترتيب العناصر، الأعداد، علامة `is_favorite` لكل مستخدم). الاستثناء الوحيد: الحقل الإضافي `next_cursor` (يُهمَل). الطوابع الزمنية و`reservation_id` تُقنَّع.
fixture `world`: 3 فئات، 24 منتجًا (منتج واحد غير فعّال)، مستخدمان بمفضلات مختلفة، admin، وعدة طلبات متعددة البنود. تجديد اللقطات عمدًا فقط: `UPDATE_SNAPSHOTS=1`.

#### C3.1 `test_product_list_bodies_are_stable`
* **الفكرة:** قوائم المنتجات لم تتغير بعد التحسينات.
* **كيف بيشتغل:** 15 حالة قائمة (افتراضي، limit 5 صفحة 2، صفحة جزئية، بعد الأخيرة، فئة، ترتيب سعر/اسم تصاعدي/تنازلي، نطاق سعر، 3 حالات بحث، بحث+فئة) × 3 مستخدمين (a, b, admin) = **45** مقارنة ملفات.
* **الخرج المتوقع:** `PASSED`. إن اختلف شيء: `AssertionError: list bodies changed: <أسماء>`.
* **لو فشل:** تحسين (فهرس، keyset، cache) غيّر النتيجة: خطأ وظيفي.
* **علاقته:** "لا نكسر السلوك" أثناء التحسين. **أمر:** `C "tests/req3/test_response_snapshots.py::test_product_list_bodies_are_stable" -v`

#### C3.2 `test_product_detail_bodies_are_stable`
* **كيف بيشتغل:** 5 منتجات (فهارس 0,1,3,4,9) × 3 مستخدمين = **15** مقارنة؛ ثم يتأكد أن المنتج المحذوف ناعمًا (فهرس 7) يعطي **404**.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** تغيّر شكل التفاصيل (مثلًا فُقد `stock` أو ترتيب الحقول).
* **أمر:** `C "tests/req3/test_response_snapshots.py::test_product_detail_bodies_are_stable" -v`

#### C3.3 `test_my_orders_bodies_are_stable`
* **كيف بيشتغل:** 6 حالات للمستخدم a (افتراضي، limit 2 صفحات 1-3، حالة pending، حالة cancelled) + b الافتراضي + admin كل الطلبات (limit 3) + admin بفلتر `user_id` = **9** لقطات.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** `selectinload` أو العدّ غيّرا الترتيب/العدد.
* **أمر:** `C "tests/req3/test_response_snapshots.py::test_my_orders_bodies_are_stable" -v`

---

### C4. `tests/req3/test_n_plus_one.py` — 10 اختبارات — phase1

**الجزء الأول (4 وحدات، sqlite):** fixture `busy_world`: **36** منتجًا، مستخدم لديه **20** مفضلة و**14** طلبًا × 3 بنود. يعدّ الاستعلامات بنفس عدّاد `X-DB-Query-Count`.

#### C4.1 `test_list_query_count_is_constant_in_page_size`
* **الفكرة:** عدد الاستعلامات لا يكبر مع حجم الصفحة (لا N+1).
* **كيف بيشتغل:** يطلب `/products?limit=` بالقيم 1 و5 و20 و36؛ يجمع عدد الاستعلامات لكل منها؛ يتأكد أن مجموعة القيم فيها عنصر واحد.
* **الخرج المتوقع:** `PASSED`؛ عند الفشل: `list statements grow with limit: {1: .., 5: .., ...}`.
* **لو فشل:** استعلام لكل صف = N+1.
* **علاقته:** شريحة N+1. **أمر:** `C "tests/req3/test_n_plus_one.py::test_list_query_count_is_constant_in_page_size" -v`
* **رقم حقيقي محفوظ:** `docs/req3/optimization_log.md` (المدخل 4): الاستعلامات لكل طلب قائمة 4 ← 5، ثابتة مع limit.

#### C4.2 `test_my_orders_query_count_is_constant_in_page_size`
* **كيف بيشتغل:** نفسه على `/orders?limit=` بالقيم 1 و5 و10 و14 (مع `selectinload` لبنود الطلبات).
* **الخرج المتوقع:** `PASSED`. **لو فشل:** بنود الطلبات تُحمَّل طلبًا طلبًا.
* **أمر:** `C "tests/req3/test_n_plus_one.py::test_my_orders_query_count_is_constant_in_page_size" -v`

#### C4.3 `test_detail_query_count_is_constant`
* **كيف بيشتغل:** يطلب تفاصيل 6 منتجات مختلفة ويقارن عدد الاستعلامات: يجب أن يتساوى.
* **الخرج المتوقع:** `PASSED`. **أمر:** `C "tests/req3/test_n_plus_one.py::test_detail_query_count_is_constant" -v`

#### C4.4 `test_list_issues_one_favorites_query_not_one_per_row`
* **الفكرة:** المفضلات تُجلب باستعلام `IN` واحد للصفحة كلها.
* **كيف بيشتغل:** يطلب `limit=36`؛ يعدّ العبارات التي تحتوي `FROM favorites`؛ يجب أن تكون **1**.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** عاد استعلام لكل منتج.
* **أمر:** `C "tests/req3/test_n_plus_one.py::test_list_issues_one_favorites_query_not_one_per_row" -v`

**الجزء الثاني (6 حيّة، تحتاج `REQ3_DB_URL`؛ بدونه SKIPPED بسبب `REQ3_DB_URL not set ...`):** تحليل EXPLAIN ANALYZE **لـ SQL الذي يولّده التطبيق فعلًا**
(الدالة `_plans` تشغّل دوال الخدمة على MySQL المزروع، تلتقط كل SELECT، وتنفّذ عليه `EXPLAIN ANALYZE`). لكل استعلام صفحة (غير `count`): يرفض **`Table scan`** (مسح كامل) ويرفض **`Sort:`/filesort**، ويشترط أن **أقصى صفوف فعلية مفحوصة ≤ حدّ**.
(سبب كتابتها بهذه الطريقة: اختبار سابق بـ SQL مكتوب يدويًا كان سينجح بينما SQL التطبيق لا يستعمل الفهرس بسبب `IS true`، انظر `optimization_log.md` المدخل 5.)

| الاختبار | ما يشغّله (مستخدم 1001 = الأكثر طلبات) | حدّ الصفوف |
|---|---|---:|
| `test_category_page_plan` | `products(page 1, limit 20, category 3)` | 100 |
| `test_newest_page_plan` | `products(page 1, limit 20)` | 100 |
| `test_search_page_plan_uses_index_order` | بحث `wireless` | 2000 |
| `test_keyset_deep_page_plan_examines_only_the_page` | يجلب `next_cursor` من الصفحة 899 ثم صفحة بالـ cursor | 100 |
| `test_my_orders_page_plan` | `list_orders(user 1001, page 1, limit 10)` | 100 |
| `test_detail_plan_is_a_primary_key_lookup` | `product(12345)`؛ يتأكد فقط من عدم وجود Table scan | — |

* **الخرج المتوقع (لم يُشغَّل):** `PASSED` لكل منها؛ عند الفشل رسالة تحتوي `full scan:` أو `filesort:` أو `examined N rows (limit M):` مع الـ SQL والخطة.
* **لو فشل:** استعلام ساخن فقد الفهرس (مثلًا عاد شرط `IS true` أو حُذف فهرس مركّب) فيعود مسحًا كاملًا.
* **علاقته:** شريحة EXPLAIN. **أرقام حقيقية محفوظة** (`optimization_log.md` المدخلان 5 و9): صفحة الفئة 14.8 ms ← 0.115 ms، "الأحدث" 53.1 ms ← 0.087 ms، صفحة keyset 44.2 ms ← 0.086 ms.
* **أمر لواحد منها:** `C "tests/req3/test_n_plus_one.py::test_category_page_plan" -v`

---

### C5. `tests/req3/test_keyset.py` — 9 اختبارات — phase1 — وحدات

**fixture `catalog`:** 23 منتجًا بأسعار وأسماء متكررة عمدًا (تعادلات)، ثلاثة منتجات لكل لحظة `created_at` (يُعاد كتابتها عبر الـ ORM لأن sqlite يخزّن الطابع بلا كسور).
keyset = ترقيم بـ cursor (موضع آخر صف) بدل `OFFSET`، واستعماله اختياري (`page` يعمل كما كان).

#### C5.1 `test_cursor_walk_equals_offset_pages` (6 حالات)
* **الفكرة:** المشي بالـ cursor يعطي **نفس** العناصر ونفس الترتيب كصفحات `page=`.
* **الحالات (parametrize):** `''` (الافتراضي created_at desc)، `sort_by=price&order=asc`، `sort_by=price&order=desc`، `sort_by=name&order=asc`، `sort_by=name&order=desc`، `sort_by=created_at&order=asc`.
* **كيف بيشتغل:** 1) يجمع صفحات `limit=5` بـ `page` 1..7. 2) يمشي بـ `next_cursor` حتى ينتهي (حد أقصى 20 صفحة). 3) يتحقق أن القائمتين متساويتان، وطولهما **23**، وبلا تكرار (23 معرّفًا مختلفًا).
* **الخرج المتوقع:** `6 × PASSED`. **لو فشل:** تخطي أو تكرار عناصر عند التعادلات = نتائج خاطئة للمستخدم.
* **أمر لحالة:** `C "tests/req3/test_keyset.py::test_cursor_walk_equals_offset_pages[sort_by=name&order=asc]" -v`
* **رقم حقيقي محفوظ:** `optimization_log.md` المدخل 9 (وملف `loadtest/results/chg_e_keyset.json`): الصفحة العميقة p50 97.6 ms (OFFSET) ← 31.9 ms (cursor).

#### C5.2 `test_page_parameter_still_works_and_cursor_wins`
* **كيف بيشتغل:** 1) الصفحة الأولى (limit 5) تعطي `next_cursor`. 2) الصفحة 2 بـ `page=2`. 3) الطلب `page=9&cursor=<c>` يجب أن يعطي **نفس عناصر الصفحة 2** (الـ `page` يُهمَل مع cursor). 4) `total` = 23 في الحالتين.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** كسر توافق الواجهة القديمة. **أمر:** `C "tests/req3/test_keyset.py::test_page_parameter_still_works_and_cursor_wins" -v`

#### C5.3 `test_last_page_has_no_next_cursor`
* **كيف بيشتغل:** `limit=5&page=5` يعيد **3** عناصر و`next_cursor` = `None`.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** عميل يظل يطلب صفحات فارغة. **أمر:** `C "tests/req3/test_keyset.py::test_last_page_has_no_next_cursor" -v`

#### C5.4 `test_bad_cursor_and_cursor_for_another_sort_are_rejected`
* **كيف بيشتغل:** 1) `cursor=not-a-cursor` و`cursor=e30` ← **422** وكود الخطأ `INVALID_CURSOR`. 2) cursor صادر لـ `price asc` يُستعمل مع الترتيب الافتراضي ← **422**.
* **الخرج المتوقع:** `PASSED`. **لو فشل:** cursor مزوّر يسبب 500 أو نتائج غريبة. **أمر:** `C "tests/req3/test_keyset.py::test_bad_cursor_and_cursor_for_another_sort_are_rejected" -v`

---

### C6. `tests/req3/test_get_stock_batch.py` — 10 اختبارات — phase1 — حي (خدمة Go الحقيقية)

يُتخطّى كله بدون `E2E_BASE_URL`. معرّفات المنتجات المؤقتة ≥ **9,000,000,000** (لا تتصادم مع منتجات seed) وتُحذف من Postgres في النهاية. fixture `ids` ينشئ **7** معرّفات مخزونها `10+n`.
`GetStockBatch` = نداء gRPC واحد لعدة منتجات (استعلام SQL واحد `WHERE product_id = ANY($1)`)، بدل N نداءً منفردًا.

#### C6.1 `test_batch_equals_n_single_calls`
* **الفكرة:** النتيجة الدفعية تساوي نتيجة N نداءً منفردًا. **كيف:** `get_quantities(ids)` مقابل `{id: get_quantity(id)}` للمعرّفات السبعة. **متوقع:** `PASSED`. **لو فشل:** أرقام مخزون خاطئة.
* **أمر:** `C "tests/req3/test_get_stock_batch.py::test_batch_equals_n_single_calls" -v`

#### C6.2 `test_one_rpc_instead_of_n`
* **كيف:** يبدأ عدّاد النداءات `start_rpc_count()`؛ `get_quantities` ← **1** نداء؛ `get_quantities_naive` ← **7** (= عدد المعرّفات). **متوقع:** `PASSED`. **لو فشل:** لم يتحقق إلغاء الـ N+1 بين الخدمتين.
* **أمر:** `C "tests/req3/test_get_stock_batch.py::test_one_rpc_instead_of_n" -v`
* **رقم حقيقي محفوظ:** `optimization_log.md` المدخل 11: نداءات gRPC 10/50/100 ← 1/1/1؛ زمن p50 عند 50 عنصرًا 97.2 ← 26.0 ms وعند 100 عنصر 147.4 ← 32.3 ms (ملفات `loadtest/results/stock_naive_vs_batch_*.json`).

#### C6.3 `test_empty_list_returns_empty`
* **كيف:** `get_quantities([])` يعيد `{}`. **متوقع:** `PASSED`. **معنى الفشل:** خطأ على قائمة فارغة. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_empty_list_returns_empty" -v`

#### C6.4 `test_unknown_id_is_defined_behaviour`
* **كيف:** 1) `get_quantities([ids[0], unknown])` يعطي `unknown → 0` (كالنداء المنفرد). 2) النداء الخام `GetStockBatch` يعيد عنصرين: `(ids[0], found=True)` و`(unknown, found=False)`.
* **متوقع:** `PASSED`. **لو فشل:** سلوك غير محدد للمعرّف المجهول. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_unknown_id_is_defined_behaviour" -v`

#### C6.5 `test_duplicates_collapse_and_order_is_first_seen`
* **كيف:** الطلب `[ids[2], ids[0], ids[2]]` يعيد معرّفين فقط بالترتيب `[ids[2], ids[0]]`. **متوقع:** `PASSED`. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_duplicates_collapse_and_order_is_first_seen" -v`

#### C6.6 `test_max_batch_size_guard`
* **كيف:** **500** معرّفًا ← يعيد 500 عنصر؛ **501** معرّفًا ← `grpc.RpcError` بالرمز `INVALID_ARGUMENT`. **متوقع:** `PASSED`. **لو فشل:** لا حدّ يحمي الخدمة من `ANY(...)` غير محدودة.
* **أمر:** `C "tests/req3/test_get_stock_batch.py::test_max_batch_size_guard" -v`

#### C6.7 `test_client_chunks_large_requests`
* **كيف:** 450 معرّفًا مع `inventory_batch_max=200` ← **3** نداءات (200+200+50) والنتيجة 450 عنصرًا. **متوقع:** `PASSED`. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_client_chunks_large_requests" -v`

#### C6.8 `test_invalid_id_rejected`
* **كيف:** المعرّف `-5` ← `INVALID_ARGUMENT`. **متوقع:** `PASSED`. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_invalid_id_rejected" -v`

#### C6.9 `test_inventory_service_down_same_failure_behaviour_and_restored`
* **الفكرة:** عند توقف خدمة المخزون يفشل النداء المنفرد والدفعي بالطريقة نفسها، والـ API يبقى 200.
* **كيف:** 1) admin ينشئ منتجًا + مستخدم. 2) `container_stopped('inventory-service')` (يوقفها ويعيدها **دائمًا** في `finally`). 3) `get_quantity` و`get_quantities` يرميان `InventoryUnavailableError`، والمجموع أقل من **6 ثوانٍ** (مهلة 2 ث). 4) `GET /products?include_stock=true&limit=5` ← 200 وكل عنصر `stock == {quantity: None, status: 'unavailable'}`. 5) بعد الإعادة النتيجة تعود صحيحة.
* **متوقع:** `PASSED`. **لو فشل:** تعطل المخزون يُسقط الموقع (500) أو يعلّق الطلب. **أمر:** `C "tests/req3/test_get_stock_batch.py::test_inventory_service_down_same_failure_behaviour_and_restored" -v`

#### C6.10 `test_include_stock_is_opt_in_and_matches_detail`
* **كيف:** منتج بمخزون **7**. القائمة العادية لا تحتوي `stock`؛ القائمة بـ `include_stock=true` تحتوي `{quantity: 7, status: available}`؛ وتفاصيل المنتج تعطي المخزون نفسه.
* **متوقع:** `PASSED`. **لو فشل:** تغيّر سلوك الواجهة الافتراضي (كسر توافق). **أمر:** `C "tests/req3/test_get_stock_batch.py::test_include_stock_is_opt_in_and_matches_detail" -v`

---

### C7. `tests/req3/test_replica.py` — 8 اختبارات — phase2 — حي

`RYW = 5` (نافذة read-your-writes بالثواني). helper `source_delay(n)` ينفّذ `STOP REPLICA SQL_THREAD; CHANGE REPLICATION SOURCE TO SOURCE_DELAY=n; START REPLICA SQL_THREAD` ويعيده إلى **0** في `finally`.

#### C7.1 `test_replication_is_running_and_replica_is_read_only`
* **كيف:** `SHOW REPLICA STATUS`: `Replica_IO_Running` و`Replica_SQL_Running` = `Yes`، و`Seconds_Behind_Source` رقم؛ و`@@read_only, @@super_read_only` = `1 1`.
* **متوقع:** `PASSED`. **لو فشل:** النسخ متوقف أو الـ replica قابل للكتابة. **أمر:** `C "tests/req3/test_replica.py::test_replication_is_running_and_replica_is_read_only" -v`

#### C7.2 `test_writes_never_reach_the_replica_directly`
* **كيف:** 1) `CREATE TABLE req3_should_fail` على الـ replica ← رسالة تحتوي `read-only`. 2) `@@server_uuid` الخاص بالـ replica **غير موجود** داخل `@@gtid_executed` (يعني لم تُنفَّذ عليه أي معاملة محلية؛ كل الـ GTIDs من الـ primary).
* **متوقع:** `PASSED`. **لو فشل:** كتابة وصلت للـ replica = تباعد بيانات. **علاقته:** "الكتابة للـ primary فقط". **أمر:** `C "tests/req3/test_replica.py::test_writes_never_reach_the_replica_directly" -v`

#### C7.3 `test_app_reads_go_to_the_replica_when_no_marker`
* **كيف:** 1) مستخدم جديد (بلا علامة). 2) يقرأ عدّاد `Com_select` على الـ replica. 3) 3 طلبات `GET /orders`. 4) العدّاد يزيد **3 على الأقل**.
* **متوقع:** `PASSED`. **لو فشل:** التوجيه إلى الـ replica لا يعمل (كل شيء على الـ primary). **أمر:** `C "tests/req3/test_replica.py::test_app_reads_go_to_the_replica_when_no_marker" -v`

#### C7.4 `test_replica_down_is_still_served_from_the_primary`
* **كيف:** 1) `container_stopped('db-replica')`. 2) 3 طلبات `/orders` (الأول يفتح circuit breaker، البقية تتجاوز الـ replica) كلها 200. 3) `GET /products?search=lamp&limit=5` ← 200. 4) `GET /dashboard/stats` (admin) ← 200. 5) بعد الإعادة ينتظر أن يلحق الـ replica (`wait_replica_caught_up`).
* **متوقع:** `PASSED`. **لو فشل:** تعطل الـ replica يُسقط الموقع. **أمر:** `C "tests/req3/test_replica.py::test_replica_down_is_still_served_from_the_primary" -v`

#### C7.5 `test_redis_down_is_still_served_from_the_primary`
* **كيف:** `container_stopped('redis')`؛ 3 طلبات `/orders` ← 200؛ `GET /products?limit=5` ← 200 (القراءات التي لا تستطيع إثبات حداثة الـ replica تذهب للـ primary).
* **متوقع:** `PASSED`. **أمر:** `C "tests/req3/test_replica.py::test_redis_down_is_still_served_from_the_primary" -v`

#### C7.6 `test_read_your_writes_under_replica_lag`
* **الفكرة:** الاختبار المركزي لـ read-your-writes: يجعل التأخر حقيقيًا ثم يقارن قارئين.
* **كيف بيشتغل:** 1) admin ينشئ منتجًا (مخزون 10) + مستخدم جديد. 2) `sleep(RYW+1)` = **6 ثوانٍ** لتنتهي علامات الكتابات السابقة. 3) `source_delay(3)`: تأخير **3 ثوانٍ**. 4) المستخدم ينشئ طلبًا. 5) نفس المستخدم يقرأ `/orders` فورًا: يجب أن يرى طلبه فقط (العلامة ← primary). 6) **قارئ بلا علامة** (admin يقرأ `/orders?user_id=<uid>` من الـ replica): يجب أن `total == 0` (لم يصله الطلب بعد: **هذا هو إثبات أن التأخر حقيقي**). 7) `sleep(4)` ثم القارئ نفسه يرى `total == 1`. 8) `finally`: التأخير يعود 0.
* **متوقع:** `PASSED`. **لو فشل:** إما أن الكاتب لا يرى كتابته (خلل RYW) أو أن الـ replica لا يتأخر فعلًا (الاختبار لا يثبت شيئًا).
* **علاقته:** شريحة "المستخدم يرى ما أنشأه للتو". **أمر:** `C "tests/req3/test_replica.py::test_read_your_writes_under_replica_lag" -v`
* **رقم حقيقي محفوظ:** `docs/req3/replica.md` و`loadtest/results/replica_lag.json`: أقصى تأخر مقاس **1 s** (دقة 1 s) تحت 5 طلبات/ث وتحت اندفاع 17.5 طلب/ث.

#### C7.7 `test_no_connection_pool_exhaustion_when_the_replica_is_off`
* **الفكرة:** حارس لخطأ حقيقي كشفه الـ benchmark (انظر F11): بدون replica كان كل طلب يفتح اتصالًا **ثانيًا** بالـ primary بينما الأول ما زال محجوزًا ← تجمّد الـ pool (15 اتصالًا) حتى `pool_timeout` = 30 ث.
* **كيف:** يعمل على `app-v1` (كل الـ flags مطفأة): إن لم تكن تعمل ← **SKIPPED** (`app-v1 (flags off) is not running: ...`). يسجّل `customer001@loadtest.example`، ثم **40** طلب `/orders?limit=10` **متزامنة** (40 thread، أكثر من 15 اتصالًا). يشترط: كلها 200 والزمن الكلي **< 25 ثانية**.
* **متوقع:** `PASSED` (أو `SKIPPED` إن لم يعمل app-v1). **لو فشل:** عاد خطأ الـ pool (طلبات تنتظر 30 ث ثم 500).
* **أمر:** `C "tests/req3/test_replica.py::test_no_connection_pool_exhaustion_when_the_replica_is_off" -v -rs`

#### C7.8 `test_no_connection_pool_exhaustion_when_the_replica_is_down`
* **كيف:** على التطبيق النهائي: يوقف الـ replica؛ طلب واحد يفتح الـ breaker؛ ثم **40** طلب `/orders` متزامنة: كلها 200 في أقل من **25 ث**؛ ثم ينتظر لحاق الـ replica.
* **متوقع:** `PASSED`. **لو فشل:** الرجوع للـ primary يعيد مشكلة الاتصال المزدوج. **أمر:** `C "tests/req3/test_replica.py::test_no_connection_pool_exhaustion_when_the_replica_is_down" -v`

---

### C8. `tests/req3/test_cache.py` — 8 اختبارات — phase2 — حي

الـ fixture `api` (عميل httpx)؛ المنتجات والفئات المؤقتة بأسماء `req3_test_<hex>`. ترويسة `X-Cache` تأخذ `HIT` أو `MISS` أو `BYPASS`.

#### C8.1 `test_first_miss_then_hit_then_miss_after_update`
* **كيف:** 1) فئة جديدة + منتج بسعر 10.00 (مفتاح قائمة جديد). 2) أول GET للقائمة `MISS` والثاني `HIT` والجسمان متطابقان. 3) تعديل السعر إلى 11.00 ← GET التالي `MISS` وفيه السعر `11.00`. 4) التفاصيل: الثاني `HIT`. 5) تعديل إلى 12.00 ← التفاصيل التالية `MISS` بسعر `12.00`.
* **متوقع:** `PASSED`. **لو فشل:** الـ cache لا يعمل أو لا يُبطَل بعد التعديل (بيانات قديمة). **علاقته:** "cache مع إبطال عند التعديل". **أمر:** `C "tests/req3/test_cache.py::test_first_miss_then_hit_then_miss_after_update" -v`

#### C8.2 `test_stock_is_never_served_from_cache`
* **كيف:** منتج بمخزون 5؛ التفاصيل مرتين (الثانية `HIT` ومخزون 5)؛ طلب كمية 2؛ التفاصيل: لا تزال `HIT` (الجزء الثابت من Redis) لكن `stock == {quantity: 3, status: available}`؛ ثم إلغاء الطلب (تنظيف).
* **متوقع:** `PASSED`. **لو فشل:** كسر ضمان المتطلب 2 (عرض مخزون قديم). **أمر:** `C "tests/req3/test_cache.py::test_stock_is_never_served_from_cache" -v`

#### C8.3 `test_redis_down_requests_still_succeed_and_recover`
* **كيف:** `container_stopped('redis')`: القائمة والتفاصيل 200 مع `X-Cache: BYPASS`؛ بعد الإعادة `sleep(2.5)` (نافذة circuit breaker 2 ث) ثم الطلب التالي `MISS` أو `HIT`.
* **متوقع:** `PASSED`. **لو فشل:** تعطل Redis يُسقط الموقع. **أمر:** `C "tests/req3/test_cache.py::test_redis_down_requests_still_succeed_and_recover" -v`

#### C8.4 `test_ttl_is_jittered_around_the_configured_values`
* **كيف:** بعد طلب قائمة وتفاصيل، `redis-cli ttl trendova:products:detail:<id>` يجب أن يكون بين **270 و330** (300 ث ±10%)، وكل مفاتيح `trendova:products:list:*` لها TTL بين 1 و **66** (60 ث ±10%).
* **متوقع:** `PASSED`. **لو فشل:** TTL غير مضبوط (انتهاء متزامن للمفاتيح أو بقاء طويل). **أمر:** `C "tests/req3/test_cache.py::test_ttl_is_jittered_around_the_configured_values" -v`

#### C8.5 `test_list_uses_a_version_namespace_and_failed_update_does_not_invalidate`
* **كيف:** يقرأ `trendova:products:ver` (v0). تعديل بسعر `-1` ← 400/422 والـ ver **لم يتغيّر**. تعديل صحيح (3.00) ← ver = v0+1 (زيادة واحدة لكل تغيير ناجح). (سطر أخير يتحقق من شكل اسم المفتاح بتعبير نمطي ثابت.)
* **متوقع:** `PASSED`. **لو فشل:** إبطال قبل الـ commit أو عند فشله. **علاقته:** "نُبطل بعد نجاح الـ commit فقط". **أمر:** `C "tests/req3/test_cache.py::test_list_uses_a_version_namespace_and_failed_update_does_not_invalidate" -v`

#### C8.6 `test_app_never_uses_keys_or_scan`
* **كيف:** اختبار ساكن: يقرأ كل ملفات `app/**/*.py` (عدا generated) ويشترط ألا يظهر `.keys(` ولا `scan` ولا `scan_iter`. **متوقع:** `PASSED`. **لو فشل:** أمر O(N) على Redis قد يجمّد الخادم. **أمر:** `C "tests/req3/test_cache.py::test_app_never_uses_keys_or_scan" -v`

#### C8.7 `test_redis_is_bounded_lru`
* **كيف:** `CONFIG GET maxmemory` = 256×1024×1024 و`maxmemory-policy` = `allkeys-lru`. **متوقع:** `PASSED`. **لو فشل:** ذاكرة Redis غير محدودة. **أمر:** `C "tests/req3/test_cache.py::test_redis_is_bounded_lru" -v`

#### C8.8 `test_stampede_one_fill_for_many_concurrent_cold_requests`
* **الفكرة:** عشرون طلبًا باردًا متزامنًا لنفس المفتاح تسبب **ملء قاعدة بيانات واحدًا فقط**.
* **كيف:** 1) فئة جديدة (مفتاح بارد). 2) `POST /internal/cache-stats/reset`. 3) **20** thread تطلب القائمة نفسها معًا. 4) كلها 200. 5) `GET /internal/cache-stats` ← `fills == 1`. (الفائز يأخذ قفل `SET NX PX 5000` ويملأ؛ البقية تنتظر ≤ 600 ms ثم تقرأ النتيجة.)
* **متوقع:** `PASSED`. **لو فشل:** كل طلب بارد يضرب MySQL (stampede). **أمر:** `C "tests/req3/test_cache.py::test_stampede_one_fill_for_many_concurrent_cold_requests" -v`

---

### C9. `tests/req3/test_etag.py` — 6 اختبارات — phase2 — حي

fixture `world`: admin + منتج بسعر 10.00 + مستخدم. ETag قوي = `"` + أول 32 خانة hex من SHA-256 لبايتات الجسم + `"`.

#### C9.1 `test_same_etag_gives_304_with_empty_body_and_headers` (حالتان: `list` و`detail`)
* **كيف:** 1) GET أول: 200، ETag ليس `W/`، `Cache-Control: private, no-cache`، `Vary` يحتوي `Accept-Encoding` و`Authorization`، والـ ETag = SHA-256[:32] لبايتات الجسم. 2) نفس الطلب مع `If-None-Match: <etag>` ← **304** وجسم فارغ مع ETag وCache-Control. 3) ثلاث صيغ أخرى تعطي 304: `"nope", <etag>` (عدة قيم)، `*`، `W/<etag>`. 4) `"other"` ← 200.
* **متوقع:** `2 × PASSED`. **لو فشل:** لا توفير لعرض النطاق، أو 304 خاطئ يخفي تغييرًا.
* **علاقته:** شريحة ETag/304. **أمر لحالة:** `C "tests/req3/test_etag.py::test_same_etag_gives_304_with_empty_body_and_headers[detail]" -v`

#### C9.2 `test_old_etag_after_admin_edit_returns_200_and_new_etag_then_304` (حالتان)
* **كيف:** 1) يأخذ ETag. 2) admin يعدّل السعر إلى **99.50**. 3) الطلب بالـ ETag **القديم** ← **200** وETag جديد مختلف والسعر `99.50` في الجسم. 4) الطلب بالـ ETag **الجديد** ← **304**.
* **متوقع:** `2 × PASSED`. **لو فشل:** العميل يتمسك بنسخة قديمة بعد التعديل. **أمر:** `C "tests/req3/test_etag.py::test_old_etag_after_admin_edit_returns_200_and_new_etag_then_304[list]" -v`

#### C9.3 `test_etag_is_computed_on_the_uncompressed_body_with_gzip`
* **كيف:** 1) يضيف 3 منتجات للفئة ليتجاوز الجسم 1000 بايت. 2) طلب بـ `Accept-Encoding: identity` وطلب بـ `gzip`. 3) الثاني `Content-Encoding: gzip` والأول بلا. 4) **نفس ETag** للاثنين وهو SHA-256 للجسم غير المضغوط. 5) الجسم المفكوك متساوٍ. 6) gzip مع `If-None-Match` ← 304 وجسم فارغ.
* **متوقع:** `PASSED`. **لو فشل:** ETag يختلف حسب الضغط فلا يتطابق أبدًا. **أمر:** `C "tests/req3/test_etag.py::test_etag_is_computed_on_the_uncompressed_body_with_gzip" -v`

#### C9.4 `test_validators_are_not_added_to_personal_or_write_responses`
* **كيف:** `/orders` و`/auth/me` و`/favorites`: لا ترويسة `etag` وقيمة `cache-control` = `no-store`. **متوقع:** `PASSED`. **لو فشل:** استجابة شخصية قد تُخزَّن في متصفح/وسيط. **أمر:** `C "tests/req3/test_etag.py::test_validators_are_not_added_to_personal_or_write_responses" -v`

---

### C10. `tests/req3/test_freshness.py` — 4 اختبارات — phase2 — حي

هذه **الجملة المفتاحية** للمتطلب: تعديل المنتج يظهر فورًا رغم الـ cache والـ replica المتأخر.

#### C10.1 `test_admin_edit_is_visible_immediately_in_list_and_detail_despite_cache_and_lagging_replica`
* **كيف:** 1) منتج بسعر 10.00 وفئة جديدة. 2) `source_delay(3)` (replica متأخر **3 ثوانٍ**). 3) القائمة `MISS` ثم `HIT`؛ التفاصيل `HIT`. 4) ثلاث تعديلات للسعر (**21.00**، **22.00**، **23.00**)، وبعد كل واحد يقرأ العميل التفاصيل والقائمة فورًا: السعر الجديد دائمًا. 5) إعادة تسمية المنتج `req3_test_renamed_zzq` ثم `search=renamed_zzq` يجد المنتج فورًا (علامة `ryw:products` تحوّل البحث للـ primary).
* **متوقع:** `PASSED`. **لو فشل:** بيانات قديمة تُعرض للعملاء بعد تعديل المدير. **أمر:** `C "tests/req3/test_freshness.py::test_admin_edit_is_visible_immediately_in_list_and_detail_despite_cache_and_lagging_replica" -v`
* **رقم حقيقي محفوظ:** `REPORT_AR.md` (جدول freshness): `stale_reads = 0` على **528** فحصًا في k6.

#### C10.2 `test_reservation_through_the_order_flow_shows_reduced_stock_immediately`
* **كيف:** منتج بمخزون **9**؛ replica متأخر 3 ث؛ التفاصيل `HIT`؛ طلب كمية 4 ← المخزون **5** فورًا؛ `include_stock=true` يعطي 5؛ طلب كمية 5 ← المخزون **0**؛ طلب إضافي كمية 1 ← **409**.
* **متوقع:** `PASSED`. **لو فشل:** كسر ضمان عدم البيع الزائد. **أمر:** `C "tests/req3/test_freshness.py::test_reservation_through_the_order_flow_shows_reduced_stock_immediately" -v`

#### C10.3 `test_category_rename_is_visible_in_cached_detail_immediately`
* **كيف:** التفاصيل مخزّنة (`HIT`)؛ تغيير اسم الفئة (`PUT /categories/<id>`) ← التفاصيل التالية تعرض الاسم الجديد (آلية `catver`: كل التفاصيل المخزّنة تُرفض بعد تغيير فئة). **متوقع:** `PASSED`. **أمر:** `C "tests/req3/test_freshness.py::test_category_rename_is_visible_in_cached_detail_immediately" -v`

#### C10.4 `test_favorites_are_per_user_even_with_a_shared_cache`
* **كيف:** مستخدمان يخزّنان القائمة نفسها؛ الأول يضيف المنتج للمفضلة؛ القائمة: `is_favorite` = `True` للأول و`False` للثاني؛ وكذلك التفاصيل. **متوقع:** `PASSED`. **لو فشل:** تسريب بيانات مستخدم لآخر عبر cache مشترك. **أمر:** `C "tests/req3/test_freshness.py::test_favorites_are_per_user_even_with_a_shared_cache" -v`

---

### ملاحظة: اختبارات المتطلبين 1 و2 (شبكة الأمان القديمة، خارج المتطلب 3)
`tests/test_api.py` (15 دالة)، `tests/test_grpc_inventory_gateway.py` (4 دوال = 5 حالات لأن الأولى parametrized بحالتين)، `tests/test_inventory_integration.py` (1): **21 حالة بالعدّ من الشيفرة**.
أمر: `C tests -m "not req3_phase1 and not req3_phase2" -v`. تتخطى `tests/conftest.py` تلقائيًا الاختبارات التي تفحص المخزون الوهمي حين `INVENTORY_MODE=grpc`. نتيجتها: **NOT VERIFIED** (لم تُشغَّل الآن). (في `STATE.md` أن 18 نجحت في جلسة سابقة قبل إضافات لاحقة؛ هذا ليس تحققًا حاليًا.)

---

## D. الإثباتات التي ليست pytest

### D1. `loadtest/k6/main.js` — البروفايل الثابت لاختبار الحمل
* **الفكرة:** نفس الحمل تمامًا قبل وبعد كل تغيير (الملف **لا يُعدَّل** بين المقارنات؛ التحكم عبر متغيرات بيئة فقط: `RUN_LABEL`, `ONLY`, `QUICK`, `DEEP_PAGE_MODE`, وللعرض: `CUSTOMERS`, `WARMUP_S`, `SCEN_S`, `MIXED_S`, `GAP_S` ولقيمها الافتراضية هي البروفايل الأصلي).
* **شو بيقيس:** زمن الاستجابة وسعة كل نقطة نهاية.
* **كيف بيشتغل:** warm-up (20 ث) ثم سيناريو معزول لكل نقطة نهاية بالتتابع (30 ث لكل منها، 20 مستخدمًا في حلقة مغلقة): `list` (تصفية فئة + 15% طلبات صفحة عميقة `list_deep` على الصفحة 900)، `detail`، `search`، `my_orders` (50 عميلًا)، ثم `create_order` بمعدل مفتوح **5/ث** (لقياس كلفة الكتابة)، ثم `mixed` (60 ث، 30 مستخدمًا: 40% قائمة، 30% تفاصيل، 10% بحث، 10% طلباتي، 10% إنشاء طلب). في `setup()` يسجّل دخول العملاء (customer001..050@loadtest.example). يُكتب الملخص إلى `loadtest/results/<label>.json`: لكل نقطة `count, req_per_s, avg/p50/p90/p95/p99/max, error_rate`.
* **معنى المقاييس:** p50 = الطلب العادي؛ p95 = 5% من الطلبات أبطأ منه؛ p99 = 1% أبطأ منه (الذيل). في الحلقة المغلقة: متوسط الزمن ≈ عدد المستخدمين ÷ req/s (قانون Little).
* **الخرج المتوقع (لم يُشغَّل الآن):** جدول بالأعمدة السابقة. **لو فشل:** ملف النتائج لا يُكتب (يخرج `bench.py` برسالة `k6 produced no results file`).
* **أمر:** `python scripts/bench.py --label x --only list` (أو `--only detail|search|my_orders|create_order|mixed`، أو بلا `--only` للبروفايل كله).
* **أرقام حقيقية محفوظة:** `docs/req3/REPORT_AR.md` (الجدول الرئيسي من `loadtest/results/final_*.json`): `search` من 14.40 إلى 44.53 req/s (p50 1385.4 ← 410.1 ms)، `list` 29.21 ← 42.70 req/s، `list_deep` 5.23 ← 7.65، `detail` 47.20 ← 44.33، `my_orders` 34.32 ← 25.09، `mixed_total` 30.34 ← 36.51.

### D2. `loadtest/k6/freshness.js` — الحداثة وسيناريو المتصفح
* **الفكرة:** سيناريوان منفصلان عن `main.js` (حتى لا يتغير بروفايله): `freshness` و`browser`.
* **freshness:** 4 مستخدمين افتراضيين، لكل منهم منتج في فئة `req3_k6_*`. كل دورة: يسخّن الـ cache بقراءة التفاصيل والقائمة، admin يغيّر السعر، ثم عميل يقرأ التفاصيل **والقائمة** فورًا؛ أي إجابة بغير السعر الجديد تزيد العدّاد **`stale_reads`**. شرط النجاح (threshold): `stale_reads == 0`. يقيس أيضًا `read_after_write_ms`.
* **browser:** عميل يشبه المتصفح يحفظ ETag لكل URL (16 رابطًا: 8 قوائم و8 تفاصيل) ويرسل `If-None-Match`؛ المقياس `not_modified_ratio` = نسبة استجابات 304.
* **الخرج المتوقع (لم يُشغَّل الآن):** JSON فيه `stale_reads, fresh_checks, not_modified_ratio, browser_bytes, read_after_write_p50_ms, http_req_failed_rate`.
* **لو فشل (`stale_reads > 0`):** يظهر الـ cache أو الـ replica أسعارًا قديمة بعد التعديل.
* **أمر (من `ab_runner`):** `python -c "import sys;sys.path.insert(0,'scripts');import ab_runner;ab_runner.run_k6('x','app',script='freshness.js')"` (أو يعمل ضمن `python scripts/bench_final.py`). (الأمر الأول لم يُشغَّل الآن.)
* **أرقام حقيقية محفوظة:** `REPORT_AR.md` (جدول freshness، من `loadtest/results/final_freshness.json`): `stale_reads = 0`، **528** فحصًا، `not_modified_ratio` **80.1%**، زمن القراءة بعد الكتابة p50 **174.0 ms** / p99 **262.6 ms**، فشل HTTP **0.00%**.

### D3. `scripts/explain_hot.py` — خطط EXPLAIN للاستعلامات الساخنة
* **الفكرة:** يعمل **داخل حاوية التطبيق**، يستدعي دوال الخدمة خلف النقاط الساخنة، يلتقط كل SELECT يولّده الـ ORM ويشغّل `EXPLAIN ANALYZE` عليه. يمكن تشغيله على أي صورة (قبل = صورة baseline، بعد = الصورة الحالية).
* **كيف تقرأ الناتج:** لكل سيناريو: `wall` (زمن الاستدعاء)، عدد عبارات SELECT، ولكل عبارة: **time ms**، **rows** (أقصى صفوف فحصها MySQL فعليًا)، `scan=YES` (مسح كامل للجدول) أو `no`، `sort=YES` (filesort) أو `no`. الأفضل: `scan=no sort=no` وrows صغيرة (20 بدل 20000).
* **السيناريوهات:** صفحة فئة، أحدث صفحة، صفحة عميقة 900 (offset)، صفحة keyset، بحث `wireless`، طلباتي لأكثر مستخدم، تفاصيل 12345، ولوحة الإحصاءات (تُتخطّى بـ `SKIP_DASHBOARD=1` لأنها بطيئة).
* **الخرج المتوقع (لم يُشغَّل الآن):** جدول نصي كما سبق + ملف `loadtest/results/explain_<LABEL>.json`.
* **أمر:** `docker compose run --rm --no-deps -v ./scripts:/app/scripts -v ./loadtest/results:/app/loadtest/results -e LABEL=after --entrypoint python app scripts/explain_hot.py`
* **أرقام حقيقية محفوظة:** `optimization_log.md` المدخل 5 (من `explain_a_after.json` و`explain_f_after.json`): صفحة الفئة 14.8 ms (sort) ← 0.115 ms؛ "الأحدث" 53.1 ms (مسح كامل + sort) ← 0.087 ms؛ بحث 132 ms ← 0.78 ms؛ والمدخل 9: صفحة عميقة OFFSET 44.2 ms ← keyset 0.086 ms. والمدخل 8: لوحة الإحصاءات 13–20 ثانية بسبب `top_products` (14.5–30.8 s).

### D4. `scripts/ab_endpoint.py` و`scripts/ab_runner.py` — لماذا المقارنة المتناوبة (interleaved A/B)؟
* **المشكلة:** على هذا الجهاز تشغيلان منفصلان بالزمن لنفس الشيفرة أعطيا 127 ثم 66 req/s (مذكور في `STATE.md` القديم و`optimization_log.md`). أي مقارنة "قبل ثم بعد" مفصولة بالزمن **غير صالحة**.
* **الحل:** نشغّل النسختين **بالتناوب** داخل جلسة واحدة (A,B,B,A أو V0,V1,...,V0,V1,...) فتتعرضان لنفس حالة الجهاز، مع تشغيل **control** (النسخة النهائية نفسها) في أول الجلسة وآخرها لقياس الانجراف.
* **`ab_endpoint.py`:** عميل واحد متتابع، كتل من N طلبًا تتناوب بين حاويتين (مثلًا `prev` على 8020 و`app` على 8000) لثلاث جولات؛ يطبع p50/p95 لكل نسخة ولكل جولة وعدد SELECT لكل طلب (من عدّاد MySQL `Com_select`)، وحكمًا: **`within noise`** إن كان الفرق بين النسختين ≤ الفرق بين جولات **النسخة نفسها**؛ وإلا `A faster`/`B faster`.
* **معنى "within noise":** الفرق أصغر من التذبذب الطبيعي بين تشغيلين متماثلين، فلا نعلن تحسنًا ولا تراجعًا.
* **`ab_runner.py`:** يشغّل k6 الكامل على حاويات المتغيرات (V0 الأصل مع الفهارس الأصلية، V1 فهارس+إصلاحات، V2 +replica، V3 +Redis cache، V4 +ETag)، يبدّل الفهارس، ينتظر لحاق الـ replica، يأخذ لقطات `docker stats` ويحفظ `loadtest/results/<prefix>_<variant>_r<round>.json` وملف `<prefix>_session.json`.
* **الخرج المتوقع (لم يُشغَّل الآن):** سطر لكل تشغيل مثل `final_V4_r1  270s  list=.../s p50=...ms ...`.
* **أمر:** `python scripts/ab_runner.py --prefix final --variants V0,V1,V2,V3,V4 --rounds 2 --control V4` (≈ساعة) و`python scripts/ab_endpoint.py --name x --path "/products?limit=20" --a 8020 --b 8000`.
* **أرقام حقيقية محفوظة:** `REPORT_AR.md` (جدول الدلالة من `final_*.json`): `search` +209.3% فوق الضجيج (44.0%)، `list` +46.2% (ضجيج 34.6%)، `list_deep` +46.1% (36.5%)؛ `detail` −6.1%، `my_orders` −26.9%، `mixed_total` +20.4% (ضجيج 23.8%) = **within noise**. الانجراف: control بداية 36.00 ← نهاية 36.68 req/s (+1.9%)، وجولتان من V3: 42.43 و33.42 req/s.
* **أرقام per-change المحفوظة:** `optimization_log.md` (ملفات `chg_*.json`): (f) القائمة p50 34.1 ← 16.0 ms (2.14×) والبحث 149.5 ← 71.9 ms؛ (a)(b)(c)(d) كلها `within noise`.

### D5. `scripts/demo_req3.py` — العرض الحي (9 خطوات)
* **الفكرة:** أمر واحد يعرض في الطرفية قبل/بعد بأرقام تُقاس لحظتها؛ ASCII فقط، stdlib فقط. كل شيء يُعاد إلى حالته النهائية في `finally` (الفهارس، `SOURCE_DELAY=0`، تشغيل Redis والـ replica والمخزون، حذف بيانات `req3_demo_*`).
* **الخطوات:** 0 فحص الخدمات والـ flags وعدد الصفوف. 1 EXPLAIN قبل/بعد (baseline مقابل النهائي). 2 عدد الاستعلامات لكل طلب (limit 10/50/100) وعدد نداءات gRPC (N مقابل 1). 3 كلفة الكتابة للفهرس (A B B A على `orders`، معلوماتي INFO). 4 الـ replica: القراءة فقط، وread-your-writes مع `SOURCE_DELAY=3`. 5 Redis: MISS/HIT، TTL، التعديل، المخزون الحي، إيقاف Redis، stampede (20 طلبًا ← ملء واحد). 6 ETag/304 وgzip. 7 k6 متناوب BEFORE/AFTER/BEFORE/AFTER (ومعه فحص stale_reads ونسبة 304). 8 اختبارات pytest. 9 لوحة النتائج والنتيجة الإجمالية PASS/FAIL ورمز الخروج 0/1.
* **الخيارات:** `--quick` (أقصر؛ يتخطى الخطوة 3 ويشغّل مجموعة جزئية من الاختبارات)، `--pause` (انتظار Enter بين الخطوات)، `--step N` (خطوة واحدة)، `--duration S` (ثوانٍ لكل نسخة، الافتراضي 20 و10 مع quick)، `--from-results` (يطبع آخر نتائج محفوظة دون تشغيل شيء ولا يحتاج Docker)، `--no-color`.
* **الخرج المتوقع (لم يُشغَّل الآن):** كتل `[STEP n/9]` فيها `BEFORE` و`AFTER` وسطر `RESULT PASS|FAIL`.
* **أمر:** `python scripts/demo_req3.py --quick`.
* **أرقام حقيقية محفوظة:** `docs/req3/STATE.md`: العرض الكامل **OVERALL PASS** في **496 ث (8.3 دقيقة)** والسريع **141 ث**؛ وآخر نتيجة محفوظة في `loadtest/results/demo_last.json`.
* **ملاحظة صدق:** `--from-results` لم يُجرَّب بدون Docker في الجلسات المسجَّلة (`STATE.md`: NOT VERIFIED).

### D6. `scripts/run_phase1.py` و`scripts/run_phase2.py`
* **الفكرة:** أمر واحد لكل مرحلة: يشغّل المكدّس ← ينتظر الصحة والنسخ ← seed إن كان فارغًا ← `pytest -m req3_phase1` (أو phase2) ← اختبار k6 سريع (20 ث، `--only mixed --quick`) ← **PASS/FAIL لكل فحص**، ويخرج 0 فقط إن نجح الكل.
* **الفحوص:** stack up؛ replication running؛ seed present؛ realistic data volume (≥20,000 منتج و≥300,000 طلب)؛ pytest؛ k6 smoke بلا أخطاء.
* **الخرج المتوقع (لم يُشغَّل الآن):** `=== phase N: PASS (... s) ===`.
* **أمر:** `python scripts/run_phase1.py` / `python scripts/run_phase2.py`.
* **أرقام حقيقية محفوظة:** `STATE.md`: `run_phase1.py` PASS في 153 ث و`run_phase2.py` PASS في 194 ث (جلسة سابقة، قبل إضافة اختبارَي الـ pool إلى المرحلة 2).

---

## E. جدول ملخص (العدد من قراءة الشيفرة)

| الملف | عدد الاختبارات | phase | المتطلب الذي يثبته | يحتاج حاوية إضافية؟ |
|---|---:|---|---|---|
| `test_auth_purge.py` | 5 | 1 | أمان المصادقة بعد نقل التنظيف خارج مسار الطلب | لا (وحدات) |
| `test_grpc_e2e.py` | 1 | 1 | مسار الطلب عبر خدمة Go الحقيقية | لا إضافية، لكن يحتاج المكدّس + `E2E_BASE_URL` |
| `test_response_snapshots.py` | 3 | 1 | عدم كسر شكل الاستجابات (45+15+9 لقطات) | لا (وحدات) |
| `test_n_plus_one.py` | 10 (4 وحدات + 6 خطط حية) | 1 | N+1 وEXPLAIN | الخطط تحتاج `REQ3_DB_URL` (MySQL مزروع) |
| `test_keyset.py` | 9 (6 + 3) | 1 | ترقيم keyset | لا (وحدات) |
| `test_get_stock_batch.py` | 10 | 1 | N+1 بين الخدمتين | خدمة المخزون Go؛ يوقفها ويعيدها |
| `test_replica.py` | 8 | 2 | replica، read-your-writes، الـ pool | `app-v1` للاختبار 7 (وإلا SKIPPED)؛ يوقف replica وRedis |
| `test_cache.py` | 8 | 2 | Redis cache | Redis (يوقفه ويعيده) |
| `test_etag.py` | 6 (2×2 + 2) | 2 | ETag/304/gzip | لا |
| `test_freshness.py` | 4 | 2 | تعديل المنتج يظهر فورًا | replica (يؤخّره 3 ث ويعيده) |
| **المجموع req3** | **64** (المرحلة 1: **38**، المرحلة 2: **26**) | | | |
| الاختبارات القديمة (`tests/test_*.py`) | 21 حالة | بلا marker | المتطلبان 1 و2 | لا |

**مقارنة مع `TESTS_MAP_AR.md`:** متطابقة (64 = 38 + 26؛ `test_replica.py` = 8). لا فروق وُجدت بالعدّ.
(العدّ: المرحلة 1 = 5+1+3+10+9+10 = 38؛ المرحلة 2 = 8+8+6+4 = 26؛ لأن `test_auth_purge` و`test_grpc_e2e` و`test_response_snapshots` و`test_n_plus_one` و`test_keyset` و`test_get_stock_batch` تحمل `req3_phase1`، والباقي `req3_phase2`.)

---

## F. أسئلة المعيد المتوقعة

1. **لماذا يختلف p99 عن p50؟** p50 هو الطلب العادي وp99 ذيل التوزيع (أبطأ 1%). الذيل يتأثر بالانتظار في الطابور أمام عامل Python واحد، وملء الـ cache البارد، والكتابات. مثال محفوظ في `REPORT_AR.md`: `list` النهائي p50 367.3 ms وp99 1011.7 ms؛ وتحسين الوسيط 1.50× بينما الذيل 1.02× فقط. (يُثبَت ببيانات k6 لا باختبار pytest: D1.)
2. **لماذا لا نخزّن المخزون في الـ cache؟** لأنه أساس عدم البيع الزائد (المتطلب 2). الاختبار: `test_stock_is_never_served_from_cache` (C8.2) و`test_reservation_through_the_order_flow_shows_reduced_stock_immediately` (C10.2).
3. **ما هو read-your-writes وكيف يثبت الاختبار أن التأخر حقيقي؟** الكاتب يرى كتابته فورًا رغم تأخر الـ replica بعلامة `ryw:{user}` (5 ث) تحوّل قراءاته إلى الـ primary. في `test_read_your_writes_under_replica_lag` (C7.6) نجعل التأخر 3 ثوانٍ بـ `SOURCE_DELAY=3`؛ قارئ بلا علامة (admin) لا يرى الطلب (`total == 0`) ثم يراه بعد 4 ثوانٍ: هذا هو الدليل على أن التأخر ليس وهميًا.
4. **لماذا نُبطل الـ cache بعد الـ commit فقط؟** لو أبطلنا قبله لأعاد طلب آخر ملء الـ cache بالصف القديم وبقي طوال الـ TTL؛ ولو فشل الـ commit فلا شيء تغيّر. الاختبار: `test_list_uses_a_version_namespace_and_failed_update_does_not_invalidate` (C8.5).
5. **لماذا يقرأ ملء الـ cache من الـ primary لا الـ replica؟** الـ replica قد يكون متأخرًا ثانية أو أكثر؛ بعد الإبطال سيُخزَّن الصف القديم تحت المفتاح الجديد ويبقى حتى انتهاء الـ TTL. يغطيه `test_admin_edit_is_visible_immediately_...` (C10.1) مع replica متأخر 3 ث.
6. **ماذا يوفّر الـ 304؟** جسم الاستجابة (عرض النطاق) لا عمل الخادم في detail (لأن المخزون الحي يُحسب كل مرة). `test_same_etag_gives_304_with_empty_body_and_headers` (C9.1).
7. **ما الذي يبطّئ الفهرس؟** كل INSERT/UPDATE يحدّث كل فهرس ثانوي ويستهلك مساحة وذاكرة. قيس بـ `create_order` متناوبًا فكان الفرق ضمن الضجيج عند 5 طلبات/ث (`optimization_log.md` المدخل 3، ملفات `ab_idx_create_order_*.json`)، وحذفنا الفهرسين الزائدين بمهاجرة منفصلة (المدخل 10). لا اختبار pytest مخصص لهذه النقطة؛ الإثبات من D4.
8. **ماذا يحدث إذا توقف Redis؟** fail-open: يُخدَم الطلب من قاعدة البيانات (`X-Cache: BYPASS`) بلا 500. `test_redis_down_requests_still_succeed_and_recover` (C8.3) و`test_redis_down_is_still_served_from_the_primary` (C7.5).
9. **وإذا توقف الـ replica؟** يُفتح circuit breaker 5 ث وتذهب القراءات إلى الـ primary. `test_replica_down_is_still_served_from_the_primary` (C7.4) و`..._when_the_replica_is_down` (C7.8).
10. **لماذا 20 طلبًا باردًا متزامنًا تسبب ملئًا واحدًا فقط؟** قفل `SET NX PX 5000`: الفائز يملأ والبقية تنتظر ≤ 600 ms ثم تقرأ. `test_stampede_one_fill_for_many_concurrent_cold_requests` (C8.8). ثمنه: في التشغيل البارد ارتفع p50 للـ detail إلى 972.1 ms مقابل 435.5 ms دافئ (`REPORT_AR.md`، جدول cold).
11. **ما خطأ الـ connection pool وأي اختبار يحرسه؟** مع `USE_READ_REPLICA=false` كان `read_db` يفتح جلسة primary **ثانية** بينما جلسة المصادقة ما زالت محجوزة؛ مع 20+ طلبًا متزامنًا (والـ pool 15 اتصالًا) كل طلب يمسك اتصالًا وينتظر آخر حتى `pool_timeout` = 30 ث. ظهر في الجلسة الأولى من الـ benchmark: `my_orders` p50 30,167 ms و60% أخطاء (`optimization_log.md` المدخل 14). الإصلاح: إعادة استعمال جلسة الطلب نفسها. الحارسان: `test_no_connection_pool_exhaustion_when_the_replica_is_off` (C7.7) و`..._is_down` (C7.8).
12. **لماذا بعض نقاط النهاية "within noise"؟** لأن الفرق بين V0 وV4 أصغر من التذبذب بين جولتين من النسخة نفسها (D4)، ولأن عامل Python الواحد هو عنق الزجاجة (CPU التطبيق 89–104% في كل النسخ، `REPORT_AR.md` جدول docker stats) فتحسينات قاعدة البيانات لا تظهر إلا حيث كان الاستعلام ثقيلًا (البحث).
13. **ما السبب الجذري لعدم ظهور أثر الفهارس أولًا؟** الـ ORM كان يكتب `is_active IS true` فلا يستعمل MySQL الفهرس ويفرز. اختبار `test_category_page_plan` وأخواته (C4) يفحص SQL التطبيق الفعلي ويرفض `Table scan` و`Sort` (`optimization_log.md` المدخل 5).
14. **لماذا الاختبارات "حيّة" وليست وحدات فقط؟** لأن المطلوب إثبات سلوك Redis والـ replica وgRPC الحقيقي (التوقيف، التأخير). وحدات sqlite تغطي فقط شكل الاستجابات وعدد الاستعلامات (C1، C3، C4 الجزء الأول، C5).
15. **كيف نعرف أن التحسينات لم تكسر النتائج؟** لقطات ذهبية بايت بايت (`test_response_snapshots.py`، C3) ومسار keyset مقابل OFFSET (C5.1).

---

## G. مشاكل شائعة وحلولها

| المشكلة | السبب | الحل |
|---|---|---|
| `SKIPPED ... E2E_BASE_URL not set` | الاختبار حيّ وشُغّل خارج `tester` | شغّله عبر `docker compose --profile test run --rm --no-deps tester ...` (يضبط المتغير) |
| `SKIPPED ... REQ3_DB_URL not set` | خطط EXPLAIN تحتاج اتصالًا بـ MySQL المزروع | نفس الحل (الحاوية تضبطه) وتأكد أن الـ seed موجود |
| `SKIPPED ... app-v1 (flags off) is not running` | حارس الـ pool يحتاج `app-v1` | `python scripts/ab_build.py up` ثم أعد الاختبار |
| فشل اختبار يبدو "غير منطقي" بعد تعديل في `app/` | صورة `tester` قديمة تحوي الشيفرة القديمة | `docker compose --profile test build tester` ثم أعد التشغيل |
| `test_read_your_writes...` يفشل بـ `replica should still be lagging` | `SOURCE_DELAY` لم يُطبَّق أو الـ replica متوقف | تأكد من `SHOW REPLICA STATUS` (IO وSQL = Yes) ثم أعد |
| الـ replica غير ملحق بعد اختبار | الـ replica يحتاج وقتًا للحاق | `wait_replica_caught_up` ينتظر؛ يدويًا راقب `Seconds_Behind_Source` حتى 0 |
| تعارض منافذ (8000، 3307، 3308، 6380، 8010–8030) | حاويات أخرى أو المشروع القديم `trendova-` يعمل | أوقف المشروع القديم: `docker compose -p trendova- stop` (لا يحذف بياناته) |
| توقف الاختبار في المنتصف | تدخل المستخدم أو انهيار | `container_stopped` يعيد تشغيل الحاوية في `finally`؛ `source_delay` يعيد التأخير إلى 0 في `finally`. إن حدث انقطاع قاسٍ فتحقق: `docker compose ps` وشغّل ما توقف (`docker start trendova-req3-redis-1` مثلًا) واضبط `CHANGE REPLICATION SOURCE TO SOURCE_DELAY=0` |
| بيانات مؤقتة متبقية (`req3_test_*`) | اختبار قُطع قبل تنظيفه | `python scripts/req3_cleanup.py` (`--count` لعرض العدد فقط)؛ لا يمس بيانات seed ولا الـ volumes |
| فهارس ناقصة بعد تشغيل `ab_runner`/العرض | قُطع قبل `set_indexes(True)` | `python -c "import sys;sys.path.insert(0,'scripts');import ab_runner;ab_runner.set_indexes(True)"` |

---

## خاتمة: ما اعتمد على ملفات محفوظة وما هو "متوقع فقط"

**أرقام من ملفات محفوظة (مع اسم الملف):**
* `docs/req3/REPORT_AR.md` (مولَّد من `loadtest/results/final_*.json`): الجدول الرئيسي، الضجيج، الـ cold، hit ratio، freshness (528 فحصًا، `stale_reads = 0`، 80.1% 304)، docker stats.
* `docs/req3/optimization_log.md`: EXPLAIN قبل/بعد، A/B لكل تغيير، stock naive مقابل batch، خطأ الـ pool (المدخل 14)، كلفة الفهرس (المدخل 3).
* `docs/req3/replica.md` و`loadtest/results/replica_lag.json`: أقصى تأخر 1 s.
* `docs/req3/STATE.md`: أزمنة `run_phase1/2` وزمن العرض (496 ث / 141 ث) وعدد الاختبارات (64).

**"متوقع من قراءة الكود، لم يُشغَّل" (كل حقول "الخرج المتوقع" في هذا الدليل):** كل `PASSED` المذكورة لكل اختبار، وصيغ رسائل الفشل، وخرج `k6` و`explain_hot` و`ab_*` و`demo_req3` و`run_phase*`.
**NOT VERIFIED:** أزمنة تشغيل كل ملف على حدة، ونتيجة الاختبارات القديمة (21 حالة) الآن، ونتيجة التشغيل الكامل الحالية، و`demo_req3.py --from-results` بلا Docker.

**مسار الدليل:** `docs/req3/TESTS_GUIDE_AR.md` (لم يُنفَّذ commit).
