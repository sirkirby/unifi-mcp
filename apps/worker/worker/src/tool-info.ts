import type { ToolInfo } from "./types";

export const TOOL_INDEX_META_TOOL: ToolInfo = {
  name: "unifi_tool_index",
  title: "UniFi Tool Index",
  description:
    "Discover available UniFi tools. Returns names and descriptions by default. " +
    "Use 'category' to filter by area (e.g. clients, firewall, devices), " +
    "'search' for keyword matching, or 'include_schemas' for full parameter schemas. " +
    "Use this to discover tools before calling unifi_execute.",
  inputSchema: {
    type: "object",
    properties: {
      category: {
        type: "string",
        description: "Optional category filter (e.g., 'clients', 'devices', 'firewall')",
      },
      search: {
        type: "string",
        description:
          "Case-insensitive token search over tool names and descriptions. " +
          "Ignores common words and one-character terms; multi-word queries require at least half " +
          "of usable terms (minimum two). Terms of four or more characters also match token prefixes. " +
          "Results are ranked by exact phrase and name matches, with at most 20 returned. " +
          "An empty string applies no filter; a non-empty query with no usable terms returns no tools.",
      },
      include_schemas: {
        type: "boolean",
        description:
          "Include full input schemas per tool. Defaults to false. " +
          "Set true with a category or search filter to get parameter details for specific tools.",
        default: false,
      },
    },
  },
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: true,
    openWorldHint: false,
  },
};

const TOKEN_PATTERN = /[a-z0-9]+/g;
export const MAX_TOOL_SEARCH_RESULTS = 20;
const SEARCH_STOP_WORDS = new Set([
  "a",
  "an",
  "and",
  "are",
  "as",
  "at",
  "be",
  "by",
  "for",
  "from",
  "how",
  "in",
  "is",
  "it",
  "of",
  "on",
  "or",
  "that",
  "the",
  "this",
  "to",
  "with",
]);

function tokenize(value: string): string[] {
  return value.toLowerCase().match(TOKEN_PATTERN) ?? [];
}

function isTokenMatch(query: string, candidate: string): boolean {
  return candidate === query || (query.length >= 4 && candidate.startsWith(query));
}

function containsExactPhrase(tokens: string[], queryTokens: string[]): boolean {
  return tokens.some((_, start) => queryTokens.every((query, offset) => tokens[start + offset] === query));
}

export function rankToolsBySearch<T extends Pick<ToolInfo, "name" | "description">>(
  tools: T[],
  search: string,
): T[] {
  const queryTokens = [
    ...new Set(tokenize(search).filter((token) => token.length >= 2 && !SEARCH_STOP_WORDS.has(token))),
  ];
  if (queryTokens.length === 0) {
    return [];
  }

  const requiredMatches = queryTokens.length === 1 ? 1 : Math.max(2, Math.ceil(queryTokens.length / 2));

  return tools
    .map((tool, index) => {
      const nameTokens = tokenize(tool.name);
      const descriptionTokens = tokenize(tool.description);
      const allTokens = [...nameTokens, ...descriptionTokens];
      const tokenMatches = queryTokens.filter((query) => allTokens.some((candidate) => isTokenMatch(query, candidate)));
      const nameMatches = queryTokens.filter((query) => nameTokens.some((candidate) => isTokenMatch(query, candidate)));
      const exactPhrase =
        containsExactPhrase(nameTokens, queryTokens) || containsExactPhrase(descriptionTokens, queryTokens) ? 1 : 0;
      return { tool, index, exactPhrase, nameMatches: nameMatches.length, tokenMatches: tokenMatches.length };
    })
    .filter(({ tokenMatches }) => tokenMatches >= requiredMatches)
    .sort(
      (a, b) =>
        b.exactPhrase - a.exactPhrase ||
        b.nameMatches - a.nameMatches ||
        b.tokenMatches - a.tokenMatches ||
        a.index - b.index,
    )
    .slice(0, MAX_TOOL_SEARCH_RESULTS)
    .map(({ tool }) => tool);
}

export interface ToolIndexOptions {
  category?: string;
  search?: string;
  includeSchemas?: boolean;
}

export interface ToolIndexEntry extends Pick<ToolInfo, "name" | "description"> {
  title?: string;
  locations: string[];
  annotations?: ToolInfo["annotations"];
  inputSchema?: Record<string, unknown>;
}

export function buildToolIndexEntries(
  locationTools: Map<string, ToolInfo[]>,
  toolToLocations: Map<string, string[]>,
  options: ToolIndexOptions = {},
): ToolIndexEntry[] {
  const entries: ToolIndexEntry[] = [];
  const seen = new Set<string>();

  for (const [locationId, tools] of locationTools) {
    for (const tool of tools) {
      if (seen.has(tool.name)) {
        continue;
      }

      seen.add(tool.name);
      const entry: ToolIndexEntry = {
        name: tool.name,
        description: tool.description,
        locations: toolToLocations.get(tool.name) ?? [locationId],
        annotations: tool.annotations,
      };
      if (tool.title) {
        entry.title = tool.title;
      }
      const inputSchema = toolInputSchema(tool);
      if (options.includeSchemas && inputSchema) {
        entry.inputSchema = inputSchema;
      }
      entries.push(entry);
    }
  }

  let filtered = entries;
  if (options.category) {
    const category = options.category.toLowerCase();
    filtered = filtered.filter(
      (tool) =>
        tool.name.toLowerCase().includes(category) || tool.description.toLowerCase().includes(category),
    );
  }
  if (options.search) {
    filtered = rankToolsBySearch(filtered, options.search);
  }
  return filtered;
}

export function toolInputSchema(tool: ToolInfo): Record<string, unknown> | undefined {
  return tool.inputSchema ?? tool.input_schema;
}

export function toolServerOrigin(tool: ToolInfo): string | undefined {
  return tool.serverOrigin ?? tool.server_origin;
}
