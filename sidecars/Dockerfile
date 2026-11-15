FROM alpine/git:2.54.0@sha256:6a1fdb962814ca11508ca8d1bab94375b5b7ac4e4a9a40981c29fc32c02f095d

RUN adduser -D -u 1000 mcp

COPY push-sync.sh /
RUN chmod +x /push-sync.sh

ENTRYPOINT ["/push-sync.sh"]
