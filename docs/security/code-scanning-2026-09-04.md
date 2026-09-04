# CodeQL alert verification — 2026-09-04

Baseline: `3632e9d45f57e7c0ae7f46d5be9e5a104e794c5d` (the scanned main commit). All 68 open alerts were inspected by rule and source location.

## Findings and remediation

- **55 private-data logging alerts:** MAC identifiers reach logger arguments in Network client/device managers and tools. Remove them at the logging call; also remove adjacent names, IP-setting payloads, and exception text/tracebacks, which can carry the same values. Retain operation context, safe state fields, and exception class. This is privacy hardening, not evidence that 55 credentials leaked.
- **10 workflow-permission alerts across nine workflows:** token permissions were implicit. All affected jobs need checkout/read access only; declare workflow-level `contents: read`. The Codecov token is separately provided where needed.
- **Alert 12:** current `CapabilityMismatch` text is locally constructed from tool product and controller capabilities, not a traceback. This instance is a false positive for stack disclosure. A fixed actionable response defensively removes dependence on exception text.
- **Alert 13:** the catch-all action handler exposes arbitrary exception class and message to callers. Confirmed information-disclosure path. Replace with a fixed response, and harden neighboring serializer exception details too. Preserve HTTP status, success/error envelope, serializer kind/tool, and administrator-only audit diagnostics.
- **Alert 11:** substring assertion in a test of generated TOML, not a production URL allowlist or authentication decision. False positive for URL validation. Replace with an exact route-line assertion that also detects duplicate patterns.

## Relationship to existing redaction

The `unifi_core.redaction` vocabulary and response policy apply to secret-bearing structured fields. MAC addresses, names, and other inventory data remain available in controller requests and tool/API results. Do not expand the secret vocabulary to clear a logging alert, and do not make logging safety depend on the response-policy opt-out. The existing ConnectionManager auth-error sanitizer removes configured username/password values; it cannot protect arbitrary device identifiers or arbitrary downstream exceptions. No new sanitizer is introduced here.

## Verification

Regression tests capture actual manager and MCP tool logs with synthetic private identifiers and private exception messages, while asserting real controller inputs remain intact. ASGI tests inject unexpected, capability, contract, and registry exceptions with private text, including with response redaction disabled. API artifacts are regenerated; no schema change is intended. Full workspace verification and PR CodeQL results are recorded in the PR. GitHub main alerts remain open until the fix is merged and main is rescanned; no alerts are dismissed by this change.

## Alert ledger

Locations below refer to the baseline commit. “Remediated” describes the branch change, not GitHub alert closure.

| Alert | Rule | Baseline location | Disposition |
| --- | --- | --- | --- |
| [#1](https://github.com/sirkirby/unifi-mcp/security/code-scanning/1) | `actions/missing-workflow-permissions` | `.github/workflows/check-skill-references.yml:12` | Confirmed; remediated |
| [#2](https://github.com/sirkirby/unifi-mcp/security/code-scanning/2) | `actions/missing-workflow-permissions` | `.github/workflows/lint.yml:12` | Confirmed; remediated |
| [#3](https://github.com/sirkirby/unifi-mcp/security/code-scanning/3) | `actions/missing-workflow-permissions` | `.github/workflows/test-access.yml:16` | Confirmed; remediated |
| [#4](https://github.com/sirkirby/unifi-mcp/security/code-scanning/4) | `actions/missing-workflow-permissions` | `.github/workflows/test-network.yml:16` | Confirmed; remediated |
| [#5](https://github.com/sirkirby/unifi-mcp/security/code-scanning/5) | `actions/missing-workflow-permissions` | `.github/workflows/test-plugin-setup.yml:20` | Confirmed; remediated |
| [#6](https://github.com/sirkirby/unifi-mcp/security/code-scanning/6) | `actions/missing-workflow-permissions` | `.github/workflows/test-plugin-setup.yml:31` | Confirmed; remediated |
| [#7](https://github.com/sirkirby/unifi-mcp/security/code-scanning/7) | `actions/missing-workflow-permissions` | `.github/workflows/test-protect.yml:16` | Confirmed; remediated |
| [#8](https://github.com/sirkirby/unifi-mcp/security/code-scanning/8) | `actions/missing-workflow-permissions` | `.github/workflows/test-api.yml:16` | Confirmed; remediated |
| [#9](https://github.com/sirkirby/unifi-mcp/security/code-scanning/9) | `actions/missing-workflow-permissions` | `.github/workflows/test-worker.yml:12` | Confirmed; remediated |
| [#10](https://github.com/sirkirby/unifi-mcp/security/code-scanning/10) | `actions/missing-workflow-permissions` | `.github/workflows/test-relay.yml:16` | Confirmed; remediated |
| [#11](https://github.com/sirkirby/unifi-mcp/security/code-scanning/11) | `js/incomplete-url-substring-sanitization` | `apps/worker/test/cli/wrangler.test.mjs:46` | False positive; strengthen test assertion |
| [#12](https://github.com/sirkirby/unifi-mcp/security/code-scanning/12) | `py/stack-trace-exposure` | `apps/api/src/unifi_api/routes/actions.py:245` | False positive at current source; defensively harden response |
| [#13](https://github.com/sirkirby/unifi-mcp/security/code-scanning/13) | `py/stack-trace-exposure` | `apps/api/src/unifi_api/routes/actions.py:295` | Confirmed; remediated |
| [#14](https://github.com/sirkirby/unifi-mcp/security/code-scanning/14) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:213` | Confirmed; remediated |
| [#15](https://github.com/sirkirby/unifi-mcp/security/code-scanning/15) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:217` | Confirmed; remediated |
| [#16](https://github.com/sirkirby/unifi-mcp/security/code-scanning/16) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:237` | Confirmed; remediated |
| [#17](https://github.com/sirkirby/unifi-mcp/security/code-scanning/17) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:241` | Confirmed; remediated |
| [#18](https://github.com/sirkirby/unifi-mcp/security/code-scanning/18) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:254` | Confirmed; remediated |
| [#19](https://github.com/sirkirby/unifi-mcp/security/code-scanning/19) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:266` | Confirmed; remediated |
| [#20](https://github.com/sirkirby/unifi-mcp/security/code-scanning/20) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:272` | Confirmed; remediated |
| [#21](https://github.com/sirkirby/unifi-mcp/security/code-scanning/21) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:276` | Confirmed; remediated |
| [#22](https://github.com/sirkirby/unifi-mcp/security/code-scanning/22) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:294` | Confirmed; remediated |
| [#23](https://github.com/sirkirby/unifi-mcp/security/code-scanning/23) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:298` | Confirmed; remediated |
| [#24](https://github.com/sirkirby/unifi-mcp/security/code-scanning/24) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:316` | Confirmed; remediated |
| [#25](https://github.com/sirkirby/unifi-mcp/security/code-scanning/25) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:320` | Confirmed; remediated |
| [#26](https://github.com/sirkirby/unifi-mcp/security/code-scanning/26) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:357` | Confirmed; remediated |
| [#27](https://github.com/sirkirby/unifi-mcp/security/code-scanning/27) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:361` | Confirmed; remediated |
| [#28](https://github.com/sirkirby/unifi-mcp/security/code-scanning/28) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:379` | Confirmed; remediated |
| [#29](https://github.com/sirkirby/unifi-mcp/security/code-scanning/29) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:383` | Confirmed; remediated |
| [#30](https://github.com/sirkirby/unifi-mcp/security/code-scanning/30) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:443` | Confirmed; remediated |
| [#31](https://github.com/sirkirby/unifi-mcp/security/code-scanning/31) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:450` | Confirmed; remediated |
| [#32](https://github.com/sirkirby/unifi-mcp/security/code-scanning/32) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:490` | Confirmed; remediated |
| [#33](https://github.com/sirkirby/unifi-mcp/security/code-scanning/33) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:499` | Confirmed; remediated |
| [#34](https://github.com/sirkirby/unifi-mcp/security/code-scanning/34) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/client_manager.py:503` | Confirmed; remediated |
| [#35](https://github.com/sirkirby/unifi-mcp/security/code-scanning/35) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:165` | Confirmed; remediated |
| [#36](https://github.com/sirkirby/unifi-mcp/security/code-scanning/36) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:253` | Confirmed; remediated |
| [#37](https://github.com/sirkirby/unifi-mcp/security/code-scanning/37) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:317` | Confirmed; remediated |
| [#38](https://github.com/sirkirby/unifi-mcp/security/code-scanning/38) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:375` | Confirmed; remediated |
| [#39](https://github.com/sirkirby/unifi-mcp/security/code-scanning/39) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:449` | Confirmed; remediated |
| [#40](https://github.com/sirkirby/unifi-mcp/security/code-scanning/40) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:516` | Confirmed; remediated |
| [#41](https://github.com/sirkirby/unifi-mcp/security/code-scanning/41) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:611` | Confirmed; remediated |
| [#42](https://github.com/sirkirby/unifi-mcp/security/code-scanning/42) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:682` | Confirmed; remediated |
| [#43](https://github.com/sirkirby/unifi-mcp/security/code-scanning/43) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/clients.py:816` | Confirmed; remediated |
| [#44](https://github.com/sirkirby/unifi-mcp/security/code-scanning/44) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:78` | Confirmed; remediated |
| [#45](https://github.com/sirkirby/unifi-mcp/security/code-scanning/45) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:82` | Confirmed; remediated |
| [#46](https://github.com/sirkirby/unifi-mcp/security/code-scanning/46) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:95` | Confirmed; remediated |
| [#47](https://github.com/sirkirby/unifi-mcp/security/code-scanning/47) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:101` | Confirmed; remediated |
| [#48](https://github.com/sirkirby/unifi-mcp/security/code-scanning/48) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:105` | Confirmed; remediated |
| [#49](https://github.com/sirkirby/unifi-mcp/security/code-scanning/49) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:123` | Confirmed; remediated |
| [#50](https://github.com/sirkirby/unifi-mcp/security/code-scanning/50) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:127` | Confirmed; remediated |
| [#51](https://github.com/sirkirby/unifi-mcp/security/code-scanning/51) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:145` | Confirmed; remediated |
| [#52](https://github.com/sirkirby/unifi-mcp/security/code-scanning/52) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:149` | Confirmed; remediated |
| [#53](https://github.com/sirkirby/unifi-mcp/security/code-scanning/53) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:267` | Confirmed; remediated |
| [#54](https://github.com/sirkirby/unifi-mcp/security/code-scanning/54) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:280` | Confirmed; remediated |
| [#55](https://github.com/sirkirby/unifi-mcp/security/code-scanning/55) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:289` | Confirmed; remediated |
| [#56](https://github.com/sirkirby/unifi-mcp/security/code-scanning/56) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:293` | Confirmed; remediated |
| [#57](https://github.com/sirkirby/unifi-mcp/security/code-scanning/57) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:610` | Confirmed; remediated |
| [#58](https://github.com/sirkirby/unifi-mcp/security/code-scanning/58) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:620` | Confirmed; remediated |
| [#59](https://github.com/sirkirby/unifi-mcp/security/code-scanning/59) | `py/clear-text-logging-sensitive-data` | `packages/unifi-core/src/unifi_core/network/managers/device_manager.py:658` | Confirmed; remediated |
| [#60](https://github.com/sirkirby/unifi-mcp/security/code-scanning/60) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:159` | Confirmed; remediated |
| [#61](https://github.com/sirkirby/unifi-mcp/security/code-scanning/61) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:208` | Confirmed; remediated |
| [#62](https://github.com/sirkirby/unifi-mcp/security/code-scanning/62) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:256` | Confirmed; remediated |
| [#63](https://github.com/sirkirby/unifi-mcp/security/code-scanning/63) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:309` | Confirmed; remediated |
| [#64](https://github.com/sirkirby/unifi-mcp/security/code-scanning/64) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:366` | Confirmed; remediated |
| [#65](https://github.com/sirkirby/unifi-mcp/security/code-scanning/65) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:406` | Confirmed; remediated |
| [#66](https://github.com/sirkirby/unifi-mcp/security/code-scanning/66) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:563` | Confirmed; remediated |
| [#67](https://github.com/sirkirby/unifi-mcp/security/code-scanning/67) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:1057` | Confirmed; remediated |
| [#68](https://github.com/sirkirby/unifi-mcp/security/code-scanning/68) | `py/clear-text-logging-sensitive-data` | `apps/network/src/unifi_network_mcp/tools/devices.py:1204` | Confirmed; remediated |
