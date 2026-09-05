# Pilot lessons

The September 2026 pilot used six PRs in its first wave and three in its second.
These are workflow observations, not statements about those PRs' current status.
Full mutable evidence remains in the pilot Myco plan `71b693906b00e7b9`.

## Test environments

- Shared setup can finish after quick static reviews. Prepare the runtime while
  domain reviewers inspect source; let completed reviewers return source evidence
  without implying test completion.
- Core, Network, Protect and API tests reuse `tests` module names. A single pytest
  invocation spanning packages caused collection/import collisions. Separate
  processes passed. An environment failure needs classification before a PR finding.
- A tracked source snapshot omits build-generated `unifi_api._version`. The pilot
  used the genuine generated module from its trusted baseline build and recorded
  that metadata overlay. Do not silently import baseline implementation code to
  make a PR's tests pass; verify implementation import origins from the PR snapshot.
- The runner's timestamp-only filenames produced one collision during parallel
  execution. Treat mixed/overwritten logs as invalid, rerun those checks, and use
  collision-resistant names with exclusive creation. Keep a distinct log for each
  command, even when multiple commands inspect the same PR head.
- Removing inherited environment variables is not enough to isolate a host with
  credentials on disk. Tests ran in network-disabled containers with read-only
  source, a private temporary directory, no host home mount and no Docker socket.
  Live reads used a separate centrally owned environment after source inspection.

## Review quality

- A small MCP filter addition passed its focused tests while its generated API
  action schema remained stale. Generated-artifact inspection belongs in the
  individual PR review even if artifact regeneration is coordinated across a batch.
- A client lookup change passed its focused suites but classified errors by looking
  for `404` anywhere in exception text. A synthetic hostname containing those digits
  exposed an incorrect not-found result for a different HTTP status. Challenge the
  actual library exception representation, not just mocks written for the new branch.
- The independent event reviewer and the primary reviewer both identified a
  connection-status problem; additional focused probes checked cancellation and
  reconnect semantics. Shared conclusions increase confidence only when the initial
  investigations were independent and the concrete behavior was verified.
- A diagnostics probe found raw MAC identifiers, but current policy did not promise
  MAC redaction at that opt-in diagnostics boundary. It remained a limitation, not
  an invented secret-exposure blocker. Consult current boundary-specific governance.
- A six-sensor live comparison showed the candidate preserved the manager's non-null
  fields while current main discarded most. The report contained counts, field names
  and version information, not private sensor values. Successful read-only hardware
  evidence did not imply that all release or GitHub gates had passed.
- In a local forward test, a candidate revision changed sensor projection after a
  passing review. The evaluating agent preserved the old evidence, inspected the
  delta and reproduced three failing tests instead of carrying the earlier result
  forward. Keep local exercises local; remote refresh is unavailable when excluded
  by the packet's scope.

No sequential timing baseline was collected, so the pilot does not establish a
percentage speedup. Its demonstrated benefits are shared domain context, distinct
test ownership, independent counterexamples and one consolidated decision record.
