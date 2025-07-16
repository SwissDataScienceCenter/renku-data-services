SHELL = bash
LDFLAGS=--ldflags "-s"

.PHONY: api-proxy
api-proxy:
	go build -v -o api-proxy $(LDFLAGS)

.PHONY: format
format:  ## Format source files
	gofmt -l -w .

.PHONY: check-format
check-format:  ## Check that sources are correctly formatted
	gofmt -d -s . && git diff --exit-code

.PHONY: check-vet
check-vet:  ## Check source files with `go vet`
	go vet ./...
