#!/usr/bin/env bash
# Assert that the Python running this CI job is the one the Dockerfile builds on.
#
# The version is declared twice and cannot be deduplicated: a job's
# `container.image` cannot read the Dockerfile. So it is asserted instead.
# Run this in EVERY containerised job — a guard in one job leaves the others
# free to drift and still report green.
#
# `|| true` on the grep pipeline is load-bearing: under `pipefail` a
# non-matching grep would abort the script here, before the explicit
# "could not parse" message below could ever run.
set -euo pipefail

want=$(grep -oE '^FROM python:[0-9]+\.[0-9]+' Dockerfile | cut -d: -f2 | sort -u || true)

if [ -z "$want" ]; then
  echo "::error::could not parse any 'FROM python:<major>.<minor>' line from Dockerfile"
  exit 1
fi
if [ "$(printf '%s\n' "$want" | wc -l | tr -d ' ')" -ne 1 ]; then
  echo "::error::Dockerfile stages disagree on the Python version: $(printf '%s ' $want)"
  exit 1
fi

py=$(command -v python || command -v python3 || true)
if [ -z "$py" ]; then
  echo "::error::no python interpreter on PATH in this job"
  exit 1
fi
have=$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')

if [ "$want" != "$have" ]; then
  echo "::error::Dockerfile builds on python $want but this CI job runs $have"
  exit 1
fi
echo "python $have matches the Dockerfile"
