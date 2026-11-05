# Checking the controller's identity

The Network, Protect and Access servers don't verify the controller's TLS certificate by default. Most UniFi OS consoles run on a factory self-signed certificate and are reached by IP, so verification on by default would stop nearly every install from connecting.

That leaves the controller's identity unchecked, so anything on the network path can pose as the controller and capture the credentials. Each server logs one warning about this at startup. To add the check, pin the certificate, or turn on verification if the certificate is trusted.

| State | Set | What is checked |
|---|---|---|
| Not checked (default) | Nothing | Nothing. The server warns at startup. |
| Pinned | `UNIFI_SSL_FINGERPRINT` | The certificate's SHA-256 fingerprint matches. The CA chain and host name aren't checked. |
| Verified | `UNIFI_VERIFY_SSL=true` | The certificate chains to a CA this machine trusts and matches the host name. |

A fingerprint takes precedence over `UNIFI_VERIFY_SSL`.

Each variable has a per-server spelling that overrides the shared one: `UNIFI_NETWORK_SSL_FINGERPRINT`, `UNIFI_PROTECT_SSL_FINGERPRINT` and `UNIFI_ACCESS_SSL_FINGERPRINT`. A pin matches one certificate, so use the per-server spellings if your servers connect to different consoles.

## Pin a certificate

Read the fingerprint from a machine on a network you trust, replacing `<console>` with your console's address:

```bash
openssl s_client -connect <console>:443 </dev/null 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256
```

This prints `sha256 Fingerprint=AB:CD:...`. Set the value as printed. The prefix and colons are optional:

```bash
UNIFI_SSL_FINGERPRINT=AB:CD:...:EF
```

If you can, compare it against the console itself, for example in a browser's certificate viewer on a direct connection. A fingerprint read through someone else's proxy pins their certificate, not the console's.

In the Claude Code plugins, set the **Certificate fingerprint** option (`ssl_fingerprint`), and for Access the **API port certificate fingerprint** option (`api_ssl_fingerprint`) too. Each plugin's option pins only that server. With Codex or OpenClaw, the plugin's setup skill can set the per-server variables for you.

A malformed value stops the server at startup, and the error doesn't repeat the value. A valid value that doesn't match the certificate fails the connection with an error saying what to do.

## Pin both Access ports

UniFi Access uses two ports, and the console can present a different certificate on each:

| Variable | Port | Used for |
|---|---|---|
| `UNIFI_ACCESS_SSL_FINGERPRINT` or `UNIFI_SSL_FINGERPRINT` | `UNIFI_ACCESS_PORT` (443) | Username and password |
| `UNIFI_ACCESS_API_SSL_FINGERPRINT` | `UNIFI_ACCESS_API_PORT` (12445) | API key, including visitor tools |

Read each port's fingerprint by running the command above with that port. The shared `UNIFI_SSL_FINGERPRINT` doesn't apply to the API key port.

If you use both ports, set both pins. While one port is pinned, the other is refused unless it has its own pin or `UNIFI_VERIFY_SSL=true`, and the server doesn't send it the API key or password. The error names the port and the variable to set.

## When a pinned certificate changes

A pin matches one certificate. If the console's certificate changes, for example after a factory reset, the connection fails until you update the fingerprint. This is the pin doing its job, because a changed certificate is also what an impersonator would present. Confirm the change is expected before you update it.

## Trusted certificates

If the console's certificate chains to a CA this machine trusts, you can set `UNIFI_VERIFY_SSL=true`. Set `UNIFI_HOST` to a name on the certificate, because connecting by IP address can fail the check even when the certificate is trusted.

## Turn the check off again

Clear any fingerprint and set `UNIFI_VERIFY_SSL=false`. Setting the flag alone isn't enough, because a fingerprint takes precedence over it.

The support bundle reports whether a check is active as `tls_verification_enabled`.
