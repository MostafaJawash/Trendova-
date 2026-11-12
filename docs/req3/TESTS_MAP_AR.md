# خريطة اختبارات المتطلب الثالث (للمناقشة)

> أعداد الاختبارات من `pytest --collect-only -q` الفعلي (ليست مقدّرة). كل أمر يُشغَّل من جذر المشروع؛ الاختبارات تعمل داخل حاوية `tester`
> (فيها docker CLI ومقبس docker لتوقيف/تشغيل Redis والـ replica وخدمة المخزون ثم إعادتها دائمًا في `finally`).
> الأمر العام: `docker compose --profile test run --rm --no-deps tester <المسار> -q`.
> بعد أي تعديل في شيفرة التطبيق أعد البناء أولًا: `docker compose --profile test build tester`.

## 1) ملفات pytest

| الملف | عدد الاختبارات | المتطلب الذي يثبته | أمر تشغيل الملف وحده | ماذا يثبت (جملة بالعربية) | خطوة العرض |
|---|---:|---|---|---|---|
| `tests/req3/test_response_snapshots.py` | 3 | قاعدة البيانات / عدم كسر الاستجابات | `docker compose --profile test run --rm --no-deps tester tests/req3/test_response_snapshots.py -q` | يثبت أن أجسام القائمة والتفاصيل وطلباتي (الحقول والترتيب والأعداد وعلامات is_favorite لكل مستخدم) لم تتغير بايت بايت بعد كل تحسين. | 8 |
| `tests/req3/test_n_plus_one.py` | 10 | N+1 + EXPLAIN | `docker compose --profile test run --rm --no-deps tester tests/req3/test_n_plus_one.py -q` | يثبت أن عدد الاستعلامات ثابت مهما كبر limit، وأن الاستعلامات الساخنة تستعمل الفهرس بلا مسح كامل ولا filesort وبعدد صفوف مفحوصة محدود. | 1، 2 |
| `tests/req3/test_keyset.py` | 9 | قاعدة البيانات (ترقيم keyset) | `docker compose --profile test run --rm --no-deps tester tests/req3/test_keyset.py -q` | يثبت أن المشي بالـ cursor يعطي نفس صفحات OFFSET لستة ترتيبات (مع تعادلات)، وأن `page` ما زال يعمل. | 8 |
| `tests/req3/test_get_stock_batch.py` | 10 | N+1 بين الخدمتين | `docker compose --profile test run --rm --no-deps tester tests/req3/test_get_stock_batch.py -q` | يثبت أن `GetStockBatch` يساوي N نداء منفردًا، وقائمة فارغة، ومعرّف مجهول، وحدًّا أقصى، وتوقف الخدمة ثم عودتها. | 2 |
| `tests/req3/test_replica.py` | 8 | Read replica + read-your-writes | `docker compose --profile test run --rm --no-deps tester tests/req3/test_replica.py -q` | يثبت أن الكتابة لا تصل للـ replica، وأنه يخدم عند توقف أيٍّ من الـ replica أو Redis (وعدم نفاد pool الاتصالات تحت 40 طلبًا متزامنًا)، وأن الكاتب يرى كتابته فورًا بينما غيره قد يرى بيانات قديمة (SOURCE_DELAY=3). | 4 |
| `tests/req3/test_cache.py` | 8 | Redis cache | `docker compose --profile test run --rm --no-deps tester tests/req3/test_cache.py -q` | يثبت MISS ثم HIT ثم MISS بعد التعديل، وأن المخزون لا يأتي من الـ cache، والعمل عند إيقاف Redis، والـ TTL، وإبطال الإصدار، وملء واحد فقط عند stampede. | 5 |
| `tests/req3/test_etag.py` | 6 | ETag / 304 | `docker compose --profile test run --rm --no-deps tester tests/req3/test_etag.py -q` | يثبت 304 بلا جسم مع نفس الـ ETag، وأن الـ ETag القديم بعد تعديل المدير يعطي 200 وETag جديدًا، وسلوك gzip. | 6 |
| `tests/req3/test_freshness.py` | 4 | الحداثة ("تعديل المنتج يظهر فورًا") | `docker compose --profile test run --rm --no-deps tester tests/req3/test_freshness.py -q` | يثبت مع replica متأخر 3 ثوانٍ أن تعديل المدير والمخزون المحجوز يظهران فورًا رغم أن القائمة والتفاصيل مخزّنتان. | 5، 7 |
| `tests/req3/test_auth_purge.py` | 5 | قاعدة البيانات (نقل التنظيف خارج مسار الطلب) | `docker compose --profile test run --rm --no-deps tester tests/req3/test_auth_purge.py -q` | يثبت أن إلغاء الرمز ما زال يُرفض بعد نقل حذف الرموز المنتهية إلى مهمة خلفية. | 8 |
| `tests/req3/test_grpc_e2e.py` | 1 | حجز المخزون عبر خدمة Go الحقيقية | `docker compose --profile test run --rm --no-deps tester tests/req3/test_grpc_e2e.py -q` | يثبت مسار الطلب كاملًا عبر gRPC (إنشاء، نقص مخزون 409، إلغاء) على المكدّس الحي. | 8 |

**مجموع اختبارات `tests/req3` المختارة بـ `-m "req3_phase1 or req3_phase2"`: 64** (المرحلة 1: 38، المرحلة 2: 26).

## 2) سيناريوهات k6

| السيناريو | الملف | المتطلب | أمر التشغيل | ماذا يثبت | خطوة العرض |
|---|---|---|---|---|---|
| `list`, `list_deep` | `loadtest/k6/main.js` | اختبار الحمل (قبل/بعد) | `py scripts/bench.py --label x --only list` | سعة قائمة المنتجات (تصفية فئة + صفحة عميقة OFFSET 17,980) تحت 20 مستخدمًا. | 7 |
| `detail` | `loadtest/k6/main.js` | اختبار الحمل | `py scripts/bench.py --label x --only detail` | سعة تفاصيل المنتج. | 7 |
| `search` | `loadtest/k6/main.js` | اختبار الحمل / EXPLAIN | `py scripts/bench.py --label x --only search` | البحث النصي (أكبر مكسب من إصلاح الفهرس). | 7 |
| `my_orders` | `loadtest/k6/main.js` | اختبار الحمل / replica | `py scripts/bench.py --label x --only my_orders` | طلباتي لمستخدمين كثيري الطلبات. | 7 |
| `create_order` | `loadtest/k6/main.js` | كلفة الكتابة (ما الذي يبطّئ الفهرس) | `py scripts/bench.py --label x --only create_order` | زمن إنشاء الطلب بمعدل ثابت 5/ث (حلقة مفتوحة). | 3 |
| `mixed` | `loadtest/k6/main.js` | اختبار الحمل | `py scripts/bench.py --label x --only mixed` | خليط 90% قراءة / 10% كتابة بـ 30 مستخدمًا. | 7 |
| `freshness` | `loadtest/k6/freshness.js` | الحداثة | `py scripts/ab_runner.py` أو `ab_runner.run_k6('x','app',script='freshness.js')` | المدير يحدّث السعر والعميل يقرأ فورًا؛ `stale_reads` يجب أن يساوي 0. | 7 |
| `browser` | `loadtest/k6/freshness.js` | ETag | نفس الأمر أعلاه | عميل يشبه المتصفح يحفظ الـ ETag لكل URL ويرسل `If-None-Match`؛ يقيس `not_modified_ratio`. | 7 |
| المتناوب الكامل V0..V4 | `scripts/ab_runner.py` + `main.js` | الجدول الرئيسي للتقرير | `py scripts/bench_final.py` | تشغيلان متناوبان لكل نسخة + control في البداية والنهاية + تشغيل cache بارد + docker stats. | — |

## 3) آخر تشغيل كامل

* آخر تشغيل كامل لـ `pytest -m "req3_phase1 or req3_phase2"` (الخطوة 8 من العرض الكامل `demo_req3.py`، مخرجات حقيقية في `/tmp/demo_full1.log`): **64 passed, 0 failed, 0 skipped**.
* تشغيلا `run_phase1.py` (38 passed) و`run_phase2.py` (24 passed) نجحا قبل إضافة اختبارَي pool (جلسة سابقة).
* بعد آخر تعديل في الشيفرة (تخزين `top_products` للوحة الإحصاءات مؤقتًا): **NOT VERIFIED** (لم تُعد الاختبارات؛ لا يوجد اختبار مخصص لهذا التعديل).
* مجموعة الوحدات القديمة `tests/test_*.py` (fake): 18 passed في آخر تشغيل لها قبل تعديل الـ pool؛ بعده **NOT VERIFIED**.
