FROM alpine/git:2.54.0@sha256:ac6c828f15d82775d204d3d75112e1d34af8945da80ccf922713c9891ba68e7a

RUN adduser -D -u 1000 mcp

COPY push-sync.sh /
RUN chmod +x /push-sync.sh

ENTRYPOINT ["/push-sync.sh"]
