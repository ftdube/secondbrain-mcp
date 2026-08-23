#!/bin/sh
set -eu

OUTBOX="${OUTBOX_PATH:-/outbox}"
INBOX="${NOTE_INBOX:-Inbox}"
PROPOSALS="${PROPOSALS_DIR:-Proposals}"
INTERVAL="${PUSH_SYNC_INTERVAL:-10}"
BRANCH="${GIT_BRANCH:-main}"
CLONE_DIR=/tmp/vault-repo

export HOME=/tmp

if [ -n "${GIT_SSH_KEY_PATH:-}" ]; then
  cp "$GIT_SSH_KEY_PATH" /tmp/push_sync_id
  chmod 400 /tmp/push_sync_id
  export GIT_SSH_COMMAND="ssh -i /tmp/push_sync_id -o StrictHostKeyChecking=no -o BatchMode=yes -o UserKnownHostsFile=/dev/null"
fi

if [ -d "$CLONE_DIR/.git" ]; then
  git -C "$CLONE_DIR" remote set-url origin "$GIT_REPO_URL"
  git -C "$CLONE_DIR" fetch --depth=1 origin "$BRANCH"
  git -C "$CLONE_DIR" reset --hard FETCH_HEAD
else
  rm -rf "$CLONE_DIR"
  git clone --depth=1 -b "$BRANCH" "$GIT_REPO_URL" "$CLONE_DIR"
fi
git -C "$CLONE_DIR" config user.email "push-sync@localhost"
git -C "$CLONE_DIR" config user.name "MCP Push Sync"

while true; do
  for f in "$OUTBOX"/*.md; do
    [ -f "$f" ] || continue
    filename=$(basename "$f")
    case "$filename" in
      *.patch.md) dest="$PROPOSALS"; label="proposal" ;;
      *)          dest="$INBOX";     label="inbox" ;;
    esac
    git -C "$CLONE_DIR" pull --rebase origin "$BRANCH"
    mkdir -p "$CLONE_DIR/$dest"
    cp "$f" "$CLONE_DIR/$dest/$filename"
    git -C "$CLONE_DIR" add "$dest/$filename"
    git -C "$CLONE_DIR" commit -m "$label: ${filename%.md}"
    git -C "$CLONE_DIR" push origin "$BRANCH"
    rm "$f"
    echo "pushed $dest/$filename"
  done
  sleep "$INTERVAL"
done
