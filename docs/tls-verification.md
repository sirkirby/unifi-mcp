# TLS verification

The Network, Protect and Access servers verify the controller's TLS certificate by
default. A server that skips the check sends the console password, or API key, to
whoever answers on the controller's address, so the check stays on unless you
choose otherwise.

Each server's connection is in one of three states:

| State | How to get it | What is checked |
|-------|---------------|-----------------|
| **Verified** (default) | `UNIFI_VERIFY_SSL=true` | The certificate chains to a CA the host trusts and matches the configured host name. |
| **Pinned** | `UNIFI_SSL_FINGERPRINT=<sha256>` | The certificate's SHA-256 fingerprint equals the configured value. CA chain and host name are not checked. |
| **Disabled** | `UNIFI_VERIFY_SSL=false`, no fingerprint | Nothing. The server logs a warning at startup. |

A fingerprint takes precedence over `UNIFI_VERIFY_SSL`. Every request a server
sends uses the same setting, including the unauthenticated probes the Network
server sends before login to pick the login endpoint.

Each variable has a per-server spelling that overrides the shared one, for
example `UNIFI_NETWORK_SSL_FINGERPRINT`, `UNIFI_PROTECT_SSL_FINGERPRINT` and
`UNIFI_ACCESS_SSL_FINGERPRINT`.

## Self-signed consoles: pin the certificate

UniFi OS consoles ship with a self-signed certificate, so the default check fails
against them with `CERTIFICATE_VERIFY_FAILED`. Pin the certificate instead of
turning verification off.

Read the fingerprint from a machine on a network you trust:

```bash
openssl s_client -connect 192.168.1.1:443 -servername 192.168.1.1 </dev/null 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256
```

That prints `sha256 Fingerprint=AB:CD:...`. Set the value, with or without the
colons or the `sha256 Fingerprint=` prefix:

```bash
UNIFI_SSL_FINGERPRINT=AB:CD:...:EF
```

Compare the value against the console itself if you can, for example in the
browser's certificate viewer on a direct connection. A fingerprint read through
an attacker's proxy pins the attacker.

An invalid value stops the server at startup. A valid value that does not match
the certificate fails the connection with fixed guidance in the error.

### When the console certificate changes

A pin matches one certificate. A console that regenerates its self-signed
certificate, after a factory reset, a firmware update that rotates it, or a host
name change, fails the connection until you read the new fingerprint and update
the variable. That failure is the pin working. Check that the change was expected
before you update it.

## Trusted certificates

If the console serves a certificate that chains to a public or internal CA,
leave the default in place. Set `UNIFI_HOST` to a name on the certificate, not the
IP address, so the host name check passes. For an internal CA, add it to the
host's trust store or point `SSL_CERT_FILE` at a bundle that includes it.

## Turning verification off

`UNIFI_VERIFY_SSL=false` with no fingerprint turns the check off entirely. It is
supported for lab setups and for upgrades from releases where it was the default,
and the server warns at startup every time it runs this way. The support bundle
reports the state as `tls_verification_enabled`.

## Upgrading from an earlier release

Earlier releases defaulted to `UNIFI_VERIFY_SSL=false`. If you never set the
variable and your console uses its self-signed certificate, the server now fails
to connect with a certificate error. Set `UNIFI_SSL_FINGERPRINT` as above, or set
`UNIFI_VERIFY_SSL=false` to keep the old behaviour.

The Claude Code plugin bundles still pass `verify_ssl=false` and offer no
fingerprint option. They pin server releases that predate this setting, so the
plugin defaults change only once compatible server releases are pinned.
