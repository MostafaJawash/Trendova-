# عرض Requirement 5

ابدأ بـ `make req5-up` ثم نفذ `python scripts/demo_req5.py`. افحص `docker compose ps`، ثم نفذ `curl -i http://localhost:8000/health` عدة مرات لرؤية `X-Instance`.

لإيقاف نسخة: `docker stop trendova-req3-app-1`، ثم أعدها بـ `docker start trendova-req3-app-1`. لا تستعمل `down -v` لأن البيانات محفوظة في volumes.

التوسع الأفقي يعني إضافة نسخ مستقلة؛ العمودي يعني زيادة موارد نسخة واحدة. لا يجوز أن تحتفظ أي نسخة بحالة العميل: الصور مشتركة، الدخول المحدود في Redis، والمعاملات والـoutbox في MySQL. WebSocket يتصل مباشرة بـ Soketi على 6001 لأنه خدمة مشتركة مستقلة.
