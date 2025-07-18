FROM golang:1.24.5-alpine3.22 AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY api_proxy.go api_proxy.go
COPY pkg pkg
RUN go build -o /api-proxy github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy

FROM alpine:3.22
USER 1000:1000
COPY --from=builder --chmod=755 /api-proxy /usr/bin/api-proxy
ENTRYPOINT [ "/usr/bin/api-proxy" ]
