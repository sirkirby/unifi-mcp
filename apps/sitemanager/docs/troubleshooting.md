# Troubleshooting — Site Manager Server

## The server lists only `sitemanager_setup_status`

No API key is set. Set `UNIFI_SITEMANAGER_API_KEY` and restart the server. `UNIFI_API_KEY` is not used: it holds a console's local key.

## "rejected the API key" (401)

The key is wrong, revoked or expired, or it is a console's local key rather than a Site Manager key. Create a new one at unifi.ui.com > Settings > API Keys.

## "refused this request" (403)

The key lacks the Site Manager scope, or the account cannot read that resource.

## A host or site is missing

The API returns what the key's account can see: consoles it owns or has been invited to. A key created inside a Fabric lists only that Fabric's consoles.

## A list returns fewer entries than expected

List tools return one page. Pass `next_cursor` back as `cursor` until it is absent. A page can be short or empty while more pages remain.

## ISP metrics are empty for a site

Not every site reports ISP metrics. The query tool returns no series for such a site and does not set `partial`. `5m` metrics are kept for 24 hours and `1h` metrics for 30 days.

## "cannot read ISP metrics for any of the requested sites"

The account has no access to any site in the query. Check the `host_id` and `site_id` values against `sitemanager_list_sites`.

## Rate limited (429)

The API allows 10,000 requests per minute. The server waits out a short limit on a read, up to about ten seconds in one call. Beyond that it returns the time to wait.

## Timeouts and connection errors

The server needs outbound HTTPS to `api.ui.com`. It ignores proxy environment variables, so it cannot reach the API through a proxy that must be configured that way. Raise `UNIFI_SITEMANAGER_TIMEOUT_SECONDS` if responses are slow.

## An id from this server fails in another server

Site Manager ids are their own family. A host, site or device id from these tools is not valid in the Network, Protect or Access servers.

## Reporting a problem

Errors include a trace id from Ubiquiti when one was returned. Include it in a bug report. Do not include your API key, host ids or site names.
