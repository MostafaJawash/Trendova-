FROM golang:1.22-alpine AS builder
WORKDIR /src/inventory-service
COPY inventory-service/go.mod inventory-service/go.sum ./
COPY inventory-service/vendor ./vendor
COPY inventory-service .
RUN CGO_ENABLED=0 go build -mod=vendor -o /inventory-service ./cmd/server
FROM alpine:3.20
RUN adduser -D -u 10001 appuser
COPY --from=builder /inventory-service /inventory-service
USER appuser
EXPOSE 50051
ENTRYPOINT ["/inventory-service"]
