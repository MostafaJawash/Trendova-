# دليل تشغيل Requirement 5

كل عبارة **نتيجة متوقعة (لم تُقَس أثناء كتابة هذا الدليل)** لا تحتوي على أرقام مخترعة.

## A. البدء

1. شغّل Docker Desktop ثم افتح PowerShell داخل المشروع `Trendova-`.
2. أنشئ `.env` من `.env.example` واضبط `DATABASE_PASSWORD` و`SECRET_KEY` وبيانات SMTP. للتجربة المحلية يوفّر profile `test` خدمة Mailpit على 1025/8025.
3. نفّذ `make req5-up` أو `docker compose --profile test up -d --build --scale app=3 --scale worker=3`.
4. نفّذ `docker compose ps` ثم `curl.exe -i http://localhost:8000/health`.

نتيجة متوقعة (لم تُقَس أثناء كتابة هذا الدليل): nginx واحد وثلاث `app` وثلاث `worker`، ورأسا `X-Instance` و`X-Upstream-Addr`.

لتشغيل الواجهة الأمامية: داخل `trendova-frontend` نفّذ `npm run dev`، ثم ادخل بحساب `ADMIN_EMAIL` و`ADMIN_PASSWORD` من `.env`.

## B. توزيع الطلبات

```powershell
1..30 | ForEach-Object { (curl.exe -s -D - http://localhost:8000/health -o NUL | Select-String '^X-Instance:').ToString() } | Group-Object | Select-Object Count,Name
python scripts/load_500.py
```

يعرض `load_500.py` عدد الطلبات لكل instance، حالات HTTP، وأزمنة p50/p95/p99 والأخطاء. نتيجة متوقعة (لم تُقَس أثناء كتابة هذا الدليل): تظهر أسماء النسخ الثلاث في الجدول.

## C. إيقاف نسخة أو عامل

اعرض الأسماء أولاً: `docker ps --format "table {{.Names}}	{{.Status}}"`. الاسم المعتاد لأول نسخة هو `trendova-req3-app-1`.

```powershell
docker stop trendova-req3-app-1
docker compose up -d --scale app=2
# في نافذة ثانية: كرر curl.exe -i http://localhost:8000/health
docker start trendova-req3-app-1
docker compose up -d --scale app=3
```

نتيجة متوقعة (لم تُقَس أثناء كتابة هذا الدليل): تستمر nginx في خدمة الطلبات من النسخ الأخرى. لإيقاف نسختين أوقف `app-1` و`app-2`. لإيقاف عامل: `docker stop trendova-req3-worker-1` ثم افحص `python scripts/queue_status.py` وواجهة RabbitMQ في `http://localhost:15672`.

## D. عدد مختلف من النسخ

ابدأ بنسختين: `docker compose up -d --scale app=2 --scale worker=2`. للعودة: `docker compose up -d --scale app=3 --scale worker=3`.

## E. الاختبارات و BEFORE/AFTER

```powershell
docker compose --profile test run --rm --no-deps tester tests/req5/test_distribution.py -m req5 -s
docker compose --profile test run --rm --no-deps tester tests/req5/test_before_after.py -m req5 -s
docker compose --profile test run --rm --no-deps tester tests/req5/test_before_after.py::test_light_failover_evidence -m req5 -s
```

| المشكلة | toggle | BEFORE | AFTER |
| --- | --- | --- | --- |
| الصور | `UPLOADS_SHARED` | `false` | `true` |
| outbox | `OUTBOX_SINGLE_PUBLISHER` | `false` | `true` |
| startup | `STARTUP_LOCK_ENABLED` | `false` | `true` |
| login | `REDIS_LOGIN_LIMITER` | `false` | `true` |
| email | `WORKER_IDEMPOTENCY` | `false` | `true` |

الملف `test_before_after.py` يعيد النسخ إلى قيمة `true` في `finally` ولا يستخدم `down -v`.

## F. العرض

`python scripts/demo_req5.py --pause` يطلب Enter قبل القياس؛ `--quick` يقلل الطلبات؛ `--step N` يقبل رقم الخطوة (والسكربت الحالي ينفذ قياس التوزيع نفسه)؛ `--from-results` يطبع ملفات النتائج المحفوظة. قل: «كل نسخة عديمة الحالة، وnginx يوزع الطلبات».

## G. الإيقاف والمشاكل الشائعة

أوقف بأمان عبر `docker compose down` فقط. لا تستخدم `docker compose down -v` لأنه يحذف volumes وبيانات dataset. إذا كان 8000 مستخدماً أوقف العملية الأخرى؛ إذا لم تصبح النسخ healthy انتظر healthcheck أو زِد ذاكرة Docker Desktop. قد يحجب VPN منفذ SMTP 587؛ اضبط مزود SMTP مناسباً (465/SSL يتطلب دعماً وإعدادات SMTP إضافية غير موجودة حالياً في هذا المشروع).

## H. إجابات الشرائح 4-10

- الأفقي يضيف نسخاً؛ العمودي يزيد موارد نسخة واحدة.
- أي نسخة يجب أن تخدم الطلب لأن الحالة المشتركة في MySQL/Redis/RabbitMQ/volume.
- لا نستخدم `ip_hash` لأنه يثبت العميل على نسخة ويخفي أخطاء الحالة المحلية.
- عند موت نسخة، nginx يحاول نسخة سليمة للطلبات اللاحقة.
- unique key في `sent_emails` يسجل البريد قبل الإرسال؛ العمال competing consumers مع `prefetch=1`.
- الصور تحتاج volume مشتركاً كي تراها كل النسخ.
