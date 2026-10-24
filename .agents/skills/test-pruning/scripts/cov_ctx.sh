#!/bin/zsh
# usage: cov_ctx.sh <repo-dir> <suite> <out-coverage-file>
# Unsets UNIFI_* first: an exported settings value changes which tests collect.
# suites: core shared relay network protect access api
export PATH=$HOME/.local/bin:$PATH
for v in ${(k)parameters[(I)UNIFI_*]}; do unset $v; done
repo=$1; suite=$2; out=$3
typeset -A P T; P=(core unifi-core shared unifi-mcp-shared relay unifi-mcp-relay network unifi-network-mcp protect unifi-protect-mcp access unifi-access-mcp api unifi-api-server)
T=(core packages/unifi-core/tests shared packages/unifi-mcp-shared/tests relay packages/unifi-mcp-relay/tests network apps/network/tests protect apps/protect/tests access apps/access/tests api apps/api/tests)
extra=(); [[ $suite == core ]] && extra=(--all-extras)
cd $repo && COVERAGE_FILE=$out uv run --package $P[$suite] $extra pytest $T[$suite] -n auto -q -p no:cacheprovider \
  --cov=unifi_core --cov=unifi_mcp_shared --cov=unifi_mcp_relay --cov=unifi_api --cov=unifi_network_mcp --cov=unifi_protect_mcp --cov=unifi_access_mcp \
  --cov-branch --cov-context=test --cov-report=
