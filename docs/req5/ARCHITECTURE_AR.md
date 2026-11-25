# معمارية Requirement 5

```text
Browser/frontend --> nginx:8000 --> app x3 --> MySQL / Redis / inventory gRPC
                                  --> shared uploads volume
RabbitMQ email.order_created --> worker x3 (competing consumers, prefetch=1) --> SMTP/Mailpit
Browser ---------------------> Soketi:6001 (WebSocket مباشر، ليس عبر nginx)
```
