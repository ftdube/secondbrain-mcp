FROM alpine/git:latest

COPY push-sync.sh /
RUN chmod +x /push-sync.sh

ENTRYPOINT ["/push-sync.sh"]
