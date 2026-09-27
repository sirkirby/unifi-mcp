# Verify an IPv4 DNS redirect

Use this recipe to test native V2 NAT redirection before expanding a DNS policy.
It covers one test client, one synthetic destination, and a resolver on the same
subnet. Network 10.6.106 on a UDM Pro SE was verified with UDP and TCP, translating
port 53 to a synthetic resolver on port 53053. Other firmware and topologies need
their own packet test.

## Prepare the scope

Use Network session credentials. Read `unifi_list_networks` for the gateway LAN
network ID and `unifi_list_nat_rules` for the original inventory and rule order.
NAT IDs belong to these tools; firewall policy and port-forward IDs are different.

Choose three distinct addresses: `CLIENT_IP`, `RESOLVER_IP`, and `GATEWAY_IP` on
that LAN. Keep the client's usual default route and DNS settings. Direct only
`198.51.100.53/32` through the test gateway if the client has another default path.
The resolver should answer a unique `.test` name with a known synthetic A record,
such as `192.0.2.123`, over both UDP and TCP on port 53053.

Before creating rules, require:

- Direct queries from the client to `RESOLVER_IP:53053` return that answer.
- Queries from the client to `198.51.100.53:53` do not return it.
- The resolver host's route to that synthetic destination uses this gateway.
- The existing firewall permits the intended client-to-resolver forwarding path.
  LAN-ingress DNAT does not receive the automatic firewall allowance used for WAN DNAT.

Get approval for the exact client, destination, resolver and enabled test. Saved
NAT rules alone do not prove that the gateway has provisioned or enforced them.

## Preview and create two disabled rules

Replace placeholders with discovered values. Call `unifi_create_nat_rule` with
`rule_data` equal to each object below, first with `confirm: false`. Review the
preview, then repeat with `confirm: true`. Retain the two returned NAT IDs.

Destination translation:

```json
{
  "type": "DNAT",
  "description": "dns-test-UNIQUE-dnat",
  "enabled": false,
  "ip_version": "IPV4",
  "protocol": "tcp_udp",
  "in_interface": "LAN_NETWORK_ID",
  "source_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "CLIENT_IP"},
  "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "198.51.100.53", "port": "53"},
  "ip_address": "RESOLVER_IP",
  "port": "53053"
}
```

Same-subnet return-path translation:

```json
{
  "type": "SNAT",
  "description": "dns-test-UNIQUE-snat",
  "enabled": false,
  "ip_version": "IPV4",
  "protocol": "tcp_udp",
  "out_interface": "LAN_NETWORK_ID",
  "source_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "CLIENT_IP"},
  "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "address": "RESOLVER_IP", "port": "53053"},
  "ip_address": "GATEWAY_IP"
}
```

The SNAT rule matches the translated resolver destination and sets no translated
port. It lets replies return through the gateway, which reverses
both translations. Read both rules back: require the exact addresses, ports,
interfaces, disabled state, and manual/non-predefined origin. Core 0.4.60 and later normalize single-host `/32`
filter inputs to bare IPv4 addresses. Bare host filter addresses also work with
Core 0.4.59. Network 10.6.106 rejects the `/32` wire spelling. The translation
`ip_address` itself must be a bare IPv4 address.

## Enable and prove the packet path

Preview `unifi_update_nat_rule` with each retained `rule_id` and
`update_data: {"enabled": true}`, then confirm the two updates. Read back both
enabled flags. Allow time for provisioning before querying; use a bounded retry
window and clean up if the expected answers never arrive.

From the test client, run both protocols, substituting the actual name and IP:

```sh
dig @198.51.100.53 UNIQUE.test A +time=3 +tries=1
dig @198.51.100.53 UNIQUE.test A +tcp +time=3 +tries=1
dig @RESOLVER_IP -p 53053 UNIQUE.test A +time=3 +tries=1
dig @RESOLVER_IP -p 53053 UNIQUE.test A +tcp +time=3 +tries=1
```

Require the known answer in all four results. Correlate redirected queries with
the synthetic resolver's observations; it should see the gateway as their source.
Then issue the synthetic-destination queries from the resolver host itself. Check
its route first and require no new synthetic-resolver request. A bind error,
unreachable route, or failed command makes this control inconclusive.

The exact client-only source match excludes the resolver from both rules. Check
that readback explicitly; a resolver-origin negative query alone cannot prove
exemption. This test checks that source exclusion, not a recursive resolver's
upstream operation. Broader client subnet rules need separate resolver exemptions
and their own ordering/packet verification. Public NAT writes do not support
unverified `exclude` or inverted-filter semantics.

## Clean up and score the audit

Delete the retained DNAT rule first, then the SNAT rule with
`unifi_delete_nat_rule` using preview and confirmation. If a write or response is
uncertain, list rules before retrying. Attempt cleanup of both owned rules even
if one deletion fails. Require fresh absence of both IDs and compare the remaining
inventory with the original. Restore temporary client routes and adapters.

Report configuration persistence and packet results separately. This scoped test
proves the redirect for the tested source and destination only. EGR-02 remains
`partial-pass` until the actual client networks and unauthorized DNS destinations
are covered and verified. Direct approved DNS and resolver source exclusion must
also pass. IPv6, encrypted DNS (DoH/DoT), arbitrary rule ordering, and alternate
firmware are outside this tested recipe; DNS records alone do not enforce egress.
