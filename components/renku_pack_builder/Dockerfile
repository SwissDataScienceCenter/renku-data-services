# syntax=docker/dockerfile:1

# Build the application from source
FROM golang:1.23 AS build-stage

WORKDIR /app

COPY go.mod go.sum ./

RUN go mod download

COPY Makefile *.go ./

# RUN CGO_ENABLED=0 GOOS=linux go build -o /pack-build
RUN make build

# Run the tests in the container
FROM build-stage AS run-test-stage
RUN go test -v ./...

# Deploy the application binary into a lean image
#FROM paketobuildpacks/build-jammy-base AS build-release-stage
FROM docker.io/paketobuildpacks/builder-jammy-full:latest AS build-release-stage

WORKDIR /

COPY --from=build-stage /app/bin/renku-pack-builder /usr/local/bin/renku-pack-builder
