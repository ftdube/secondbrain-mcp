VAULT_REPO ?= $(error VAULT_REPO not set — path to your local vault git clone)

.PHONY: proposals apply-proposals

proposals:
	python3 scripts/apply_proposals.py --repo $(VAULT_REPO)

apply-proposals:
	python3 scripts/apply_proposals.py --repo $(VAULT_REPO) --apply
