#!/bin/sh
set -eu

OUTBOX="${OUTBOX_PATH:-/outbox}"
INBOX="${NOTE_INBOX:-Inbox}"
INTERVAL="${PUSH_SYNC_INTERVAL:-10}"
CLONE_DIR=/tmp/vault-repo

export HOME=/tmp

if [ -n "${GIT_SSH_KEY_PATH:-}" ]; then
  cp "$GIT_SSH_KEY_PATH" /tmp/push_sync_id
  chmod 400 /tmp/push_sync_id
  export GIT_SSH_COMMAND="ssh -i /tmp/push_sync_id -o StrictHostKeyChecking=no -o BatchMode=yes"
fi

git clone --depth=1 "$GIT_REPO_URL" "$CLONE_DIR"
git -C "$CLONE_DIR" config user.email "push-sync@localhost"
git -C "$CLONE_DIR" config user.name "MCP Push Sync"

while true; do
  for f in "$OUTBOX"/*.md; do
    [ -f "$f" ] || continue
    filename=$(basename "$f")
    git -C "$CLONE_DIR" pull --rebase
    mkdir -p "$CLONE_DIR/$INBOX"
    cp "$f" "$CLONE_DIR/$INBOX/$filename"
    git -C "$CLONE_DIR" add "$INBOX/$filename"
    git -C "$CLONE_DIR" commit -m "inbox: ${filename%.md}"
    git -C "$CLONE_DIR" push
    rm "$f"
    echo "pushed $INBOX/$filename"
  done
  sleep "$INTERVAL"
done
