#!/usr/bin/env bash
# Assert that the python running this CI job is the one the Dockerfile builds on.
#
# The version is declared twice and cannot be deduplicated — a job's runtime is
# chosen by the workflow, which cannot read the Dockerfile — so it is asserted.
# Call this from EVERY job that sets up python: a guard in one job leaves the
# others free to drift and still report green.
#
# Resolved relative to this script, not the working directory, so a job that
# sets `working-directory:` does not turn this into a misleading parse error.
#
# `|| true` on the grep pipeline is load-bearing: under `pipefail` a
# non-matching grep would abort here, before the explicit "could not parse"
# message below could run.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
dockerfile="$root/Dockerfile"

if [ ! -f "$dockerfile" ]; then
  echo "::error::no Dockerfile at $dockerfile"
  exit 1
fi

want=$(grep -oE '^[[:space:]]*FROM[[:space:]]+(--[^[:space:]]+[[:space:]]+)*([^[:space:]]+/)?python:[0-9]+\.[0-9]+' "$dockerfile" | sed 's/.*://' | sort -u || true)

if [ -z "$want" ]; then
  echo "::error::could not parse any 'FROM python:<major>.<minor>' line from $dockerfile"
  exit 1
fi
if [ "$(printf '%s\n' "$want" | wc -l | tr -d ' ')" -ne 1 ]; then
  echo "::error::Dockerfile stages disagree on the python version: $(echo "$want" | tr '\n' ' ')"
  exit 1
fi

have=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [ "$want" != "$have" ]; then
  echo "::error::Dockerfile builds on python $want but this CI job runs $have"
  exit 1
fi
echo "python $have matches the Dockerfile"
