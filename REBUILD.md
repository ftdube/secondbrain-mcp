# Rebuild

From an empty workstation to a running server. This repository holds the server, its sidecars and a Compose file; Kubernetes manifests live in the deploying GitOps repository, not here.

**Rehearsal status:** not rehearsed from this page.

## Inputs

| Input | Needed for | Where it lives |
|---|---|---|
| The vault's git repository | Indexing (git-sync) and writes (push-sync) | Your git host; `GIT_REPO_URL` in `.env` |
| A read-only deploy key | git-sync (NFR-SEC-7) | Generated per [README](README.md#sidecars); `GITSYNC_SSH_KEY_PATH` |
| A read-write deploy key | push-sync | Your git host; `SSH_KEY_PATH` |
| An OIDC issuer (Dex) with a client for this server | Auth (BRD §9.8) | `DEX_ISSUER`, `MCP_CLIENT_ID` |

## Workstation

1. Clone the repository.
2. `pip install -r requirements.txt -r requirements-dev.txt`, then `pytest tests/` — the same checks CI runs. Python must match the `Dockerfile`'s version (`scripts/ci-python-matches-dockerfile.sh`).
3. Run locally: [README, "Running locally"](README.md#running-locally). Environment variables: [README](README.md#environment-variables) and `.env.example`; `compose.yaml` is authoritative for the sidecars'.

## Deploy

Build the server image (`Dockerfile`) and the push-sync image (`sidecars/Dockerfile`), then deploy them from the GitOps repository alongside Dex. Mount the push-sync key with `defaultMode: 0400` (NFR-SEC-2) and set `GITSYNC_LINK=vault` on git-sync (`AGENTS.md`).

## Proposals

Applying proposals runs on a workstation against a local vault clone: `make apply-proposals VAULT_REPO=<path>` (`make proposals` previews).
