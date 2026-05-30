FROM alpine/git:latest

RUN adduser -D -u 1000 mcp

COPY push-sync.sh /
RUN chmod +x /push-sync.sh

ENTRYPOINT ["/push-sync.sh"]
