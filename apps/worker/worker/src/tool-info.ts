import type { ToolInfo } from "./types";

export function toolInputSchema(tool: ToolInfo): Record<string, unknown> | undefined {
  return tool.inputSchema ?? tool.input_schema;
}

export function toolServerOrigin(tool: ToolInfo): string | undefined {
  return tool.serverOrigin ?? tool.server_origin;
}
