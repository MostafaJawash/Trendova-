# خريطة اختبارات Requirement 4

شغل الحاويات أولا:

```powershell
docker compose --profile test --profile req4 up -d --build
docker compose --profile test --profile req4 run --rm --no-deps tester tests -m "req4 or req4_latency" -v -s
```

| الملف | ما يثبته | خطوة العرض |
|---|---|---|
| `test_queue.py` | topology durable وoutbox | 5، 6 |
| `test_channel_auth.py` | admin/owner/other-user/missing-token | 7 |
| `test_live_queue.py` | إيقاف العامل وخمس رسائل، ثم RabbitMQ down/outbox، وretry/DLQ | 4، 5 |
| `test_latency_before_after.py` | قياس inline مقابل queue وحفظ JSON | 1 |

آخر نتائج مثبتة: أربعة اختبارات أولية مررت منفردة، واختبار RabbitMQ-down مر: `1 passed in 114.15s`. اختبار latency لم يُشغّل بعد، لذلك أرقامه **NOT VERIFIED**.
