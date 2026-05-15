# MCP Tasks Alignment

MCP Tasks are an experimental capability in the `2025-11-25` protocol
revision. UniFi MCP should align with the standard shape now, but avoid
advertising first-class task capability until the server runtime path can handle
task-augmented requests end to end.

References:

- [MCP Tasks specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)
- [MCP schema reference](https://modelcontextprotocol.io/specification/2025-11-25/schema)
- [2025-11-25 release announcement](https://blog.modelcontextprotocol.io/posts/2025-11-25-first-mcp-anniversary/)

## Standard Shape

The spec defines Tasks as durable state machines for deferred work. A receiver
returns a `CreateTaskResult` immediately when it accepts a task-augmented
request, and the requestor later uses `tasks/get` and `tasks/result`.

The SDK already exposes these protocol models:

- `Task`
- `CreateTaskResult`
- `GetTaskResult`
- `GetTaskPayloadResult`
- `ListTasksResult`
- `TaskStatusNotification`
- task capability models for clients and servers

## UniFi Mapping

UniFi MCP already has compatibility jobs through `*_batch` and
`*_batch_status`. Those remain stable and continue to return `jobId`.

The standard MCP mapping is:

| Current UniFi job field | MCP Task field | Notes |
|-------------------------|----------------|-------|
| `jobId` | `taskId` | Keep the same opaque ID when adapting compatibility jobs. |
| `status=running` | `status=working` | Non-terminal task state. |
| `status=done` | `status=completed` | Result is available from the existing job result today; future protocol handlers should return it from `tasks/result`. |
| `status=error` | `status=failed` | Tool results with `isError=true` are also failed tasks under the spec. |
| `status=unknown` | protocol error for native Tasks | Compatibility `*_batch_status` may still return `unknown`; native `tasks/get` should reject missing IDs with invalid params. |
| `started` | `createdAt` | Convert Unix timestamp to ISO 8601 UTC. |
| `completed` | `lastUpdatedAt` | Use `started` while still working. |
| configured retention | `ttl` | Default prototype value is 10 minutes. |
| configured polling hint | `pollInterval` | Default prototype value is 1 second. |

## Prototype Scope

This PR adds `unifi_mcp_shared.tasks` as a small adapter layer:

- `task_from_job_status(job_id, job_status)` converts a compatibility job
  status to the MCP SDK `Task` model.
- `task_to_dict(task)` serializes protocol field names such as `taskId`,
  `createdAt`, and `pollInterval`.
- `create_task_result_from_job(...)` creates the standard `CreateTaskResult`
  shape and can include the provisional
  `io.modelcontextprotocol/model-immediate-response` metadata.
- `related_task_meta(task_id)` returns
  `io.modelcontextprotocol/related-task` metadata for task-associated messages.

This deliberately does not replace `*_batch` or `*_batch_status`, and it does
not yet advertise Tasks in server capabilities.

## Candidate Workflow

The best first native workflow is batch execution status, not RF scans, backups,
upgrades, or clip export.

Why batch first:

- It already has an in-memory job store and status tool.
- It is non-destructive when composed from read-only operations.
- It exists across Network, Protect, and Access through shared meta-tools.
- It lets us validate task state mapping without adding controller-specific
  polling logic.

Recommended implementation sequence:

1. Keep `*_batch` returning `jobId` for compatibility.
2. Add experimental task capability only when FastMCP exposes a stable handler
   path for task-augmented `tools/call` requests.
3. On task-augmented `*_batch` calls, return `CreateTaskResult` with the first
   accepted batch job or a parent task representing the batch.
4. Implement native `tasks/get` by reading the existing job store through the
   adapter.
5. Implement native `tasks/result` so terminal tasks return exactly the
   underlying tool result or JSON-RPC error.
6. Add `tasks/list` with cursor pagination before advertising list capability.
7. Add `tasks/cancel` only after `JobStore` tracks the underlying
   `asyncio.Task`, because the spec requires terminal `cancelled` state after a
   valid cancellation request.

## Adoption Gates

Do not mark MCP Tasks as fully supported until all of these are true:

- `initialize` advertises task capabilities only for implemented operations.
- `tasks/get` rejects nonexistent IDs with JSON-RPC invalid params instead of
  the compatibility `unknown` status.
- `tasks/result` blocks for non-terminal tasks and returns the underlying
  request result for terminal tasks.
- `tasks/list` is paginated and scoped to retrievable tasks.
- Task responses include `createdAt`, `lastUpdatedAt`, and actual `ttl`.
- Optional `notifications/tasks/status` are treated as best-effort only; clients
  must still be able to poll.
- Cancellation is not advertised until cancellation semantics are real.

## Compatibility Position

`*_batch` and `*_batch_status` are still the correct compatibility surface for
current clients. Native MCP Tasks should come alongside them, not replace them,
because Tasks are still experimental and client support will vary.
