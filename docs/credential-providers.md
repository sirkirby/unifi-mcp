# Credential providers

The MCP servers read the controller password and API key from the environment.
An MCP client passes that environment to the server it spawns, and to every
other process it spawns, so a plain `UNIFI_PASSWORD` is inherited far more
widely than it needs to be. Two indirect spellings keep the value inside the
server process:

| Spelling | Value |
|----------|-------|
| `UNIFI_<SERVER>_PASSWORD_FILE` | A path to a file whose contents are the password. |
| `UNIFI_<SERVER>_PASSWORD_COMMAND` | An argv, run without a shell, whose stdout is the password. |

`UNIFI_<SERVER>_API_KEY_FILE` and `UNIFI_<SERVER>_API_KEY_COMMAND` work the same
way, as do the shared `UNIFI_PASSWORD_*` and `UNIFI_API_KEY_*` forms. Set exactly
one spelling per precedence level; two is refused as ambiguous rather than
resolved by a rule nobody remembers.

## Shared and product-specific precedence

All three servers resolve non-empty product-specific values before shared values:
`UNIFI_NETWORK_*`, `UNIFI_PROTECT_*`, or `UNIFI_ACCESS_*` > `UNIFI_*`. Empty
variables count as unset. This applies to host, username, password, API key and
other connection settings. The shared bootstrap overlays this rule after loading
the bundled YAML, so the YAML variable names alone do not define precedence.

For each secret, the first level with a non-empty spelling is selected. Exactly
one of its plain, `_FILE`, or `_COMMAND` spellings may be set; ambiguity or a
failing provider at that level refuses startup rather than falling back. Lower
levels are ignored once a level is selected. Removing a product-specific provider
can therefore reactivate a shared provider.

Plugin setup switches saved spellings at the same level in one transaction.
Selecting `_FILE`, for example, removes the saved plain and `_COMMAND` siblings.
A JSON stdin patch can delete keys with `null`; the helper preserves unrelated
settings and never executes a provider. It also checks the inherited environment:
correct conflicting provider spellings in the client launcher before retrying.
Raw credentials belong only in private stdin input, never command arguments.

## Startup failures

Every failure refuses startup with exit code 6 and names the variable. Nothing
the file or the helper produces is ever logged.

The file provider is the simpler one and covers the Docker and systemd secrets
convention. The rest of this page is the contract for the command provider,
which executes a program and therefore needs its boundaries written down.

## Supported platforms

| Platform | Status | Basis |
|----------|--------|-------|
| Linux | Supported | Verified end to end against a real provider, GnuPG 2.4.4: server start, controller authentication, one read-only call, and the failure cases below. |
| macOS | Provider acceptance unverified | Synthetic-helper tests cover output, startup isolation, and process-group cleanup, including an exited group leader. Keychain-backed controller authentication has not been verified. |
| Windows | Unverified | The threaded reader is tested with real pipes on POSIX, but native path handling and process-tree termination (`taskkill /T /F`) remain unverified. The server logs a warning naming the variable when the command provider is used there, and `UNIFI_<VAR>_FILE` is the tested option on Windows. |

"Unverified" is a statement about evidence, not a prediction of failure. Report a
platform that works and it moves up; the failure modes are all fail-closed, so a
platform that does not work refuses startup rather than running with a wrong
credential. macOS and Windows differ in kind, not just in degree: macOS runs the
same POSIX code path as Linux, whereas Windows has native process and path handling
that these tests do not exercise, which is why only Windows warns at runtime.

A provider that prompts interactively is not supported on any platform. The
helper's stdin is closed, so a helper that needs a passphrase, a PIN or a touch
confirmation fails immediately instead of hanging the server's startup or
reading the MCP client's protocol stream. Unlock the agent before the server
starts: `gpg-agent` with a cached passphrase, a logged-in `op` session, an
unlocked Keychain.

## What the boundary does not cover

The indirection keeps the secret out of the MCP client's environment. It does not make
the *launcher* trustworthy. Everything the server reads -- the controller host, the port,
`CONFIG_PATH`, and these credential spellings -- comes from the environment the launcher
supplies, so whoever controls the launcher chooses where a resolved credential is sent.
If you load an env file explicitly (`uv run --env-file`, Docker `env_file:`), its values
enter that trusted environment: select only files you control.

The server does not discover configuration on its own. It never loads a project `.env`,
and `CONFIG_PATH` must be an absolute path in the process environment, so the directory
an MCP client happens to start the server in is not part of the trust boundary.

The helper's exit status is the only completeness signal. A helper that writes part of the
credential and still exits 0 -- a shell pipeline without `set -o pipefail`, say, where an
earlier stage dies -- yields a short value that nothing here can distinguish from a short
password. Have the helper fail loudly rather than partially.

## Executable resolution

The command is split into an argv the way a shell would split it, using
`shlex`, and then run directly. No shell is involved, so `$VAR`, `~`, globs,
pipes and redirects reach the program as literal text. On Windows write paths
with forward slashes, because backslash is an escape character to `shlex`.

The first element is resolved under one rule:

- An **absolute path** is used as given.
- A **bare name** with no path separator is looked up on the `PATH` of the
  environment the server was started with.
- Anything else, such as `./helper.sh` or `bin/helper`, is **refused**. A
  relative path names a location relative to a working directory the operator
  did not choose, which is the working directory the MCP client picked.

This rule is specific to the command provider, because the helper is executed.
`_FILE` still resolves a relative path against the working directory the way any
other path-valued setting does; give it an absolute path anyway.

Prefer an absolute path. A bare name is convenient but depends on the `PATH`
your MCP client happened to export, which is often not your shell's `PATH`.

## Process lifecycle

- **Working directory.** The helper runs in a neutral directory, the filesystem
  root on POSIX and `%SystemRoot%` on Windows, never the working directory the
  server was started in. That directory belongs to whatever project the user
  opened in their editor, and it is on `sys.path` for a Python helper, so
  inheriting it would let that project decide what `python -m helper` imports.
  Every path your helper needs must be absolute.
- **Environment.** The helper receives the environment the server process was
  started with, restricted to the variable names present at startup. A name
  introduced after that -- `PYTHONPATH`, `LD_PRELOAD` or similar -- is not passed
  to the helper. Provider settings such as `PASSWORD_STORE_DIR`, `GNUPGHOME` or
  `GPG_TTY` must be exported to the server by its launcher.
- **Trust.** The `_COMMAND` and `_FILE` variables are honoured only for names
  present in that startup snapshot. The server never loads a project `.env`, so
  a directory an MCP client opens cannot supply any of these, nor a plain
  password.
- **stdin** is closed. **stdout** is captured, capped at 64 KiB, and must be a
  single non-empty line after trailing newlines are dropped. **stderr** is
  discarded, not captured: a failing helper frequently prints the credential
  there, and no truncation rule makes that safe to log. Run the helper yourself
  in a terminal to see why it failed.
- **Timeout.** The helper gets 30 seconds, and that budget covers reading its
  output as well as running it. On expiry the helper's session is terminated,
  not just the process that was started: it runs in its own session on POSIX
  and its own process group on Windows, so a descendant it left in the
  background is killed with it. POSIX cleanup retains the original process-group
  ID even when the helper has already exited or been reaped. `SIGTERM` is followed
  by `SIGKILL` after a short grace period. A descendant that left the session on its own -- by
  calling `setsid`, as a daemonising agent does -- is reached by neither
  signal, and may still be running when startup is refused; the refusal message
  says which of the two happened rather than claiming a termination that did
  not occur. Such a descendant cannot delay the refusal: the read is bounded by
  the deadline whether or not anything still holds the pipe open.
- **Agents the provider starts are its own.** A provider may deliberately
  daemonise a long-lived agent and detach it: GnuPG starts `gpg-agent` on first
  use and leaves it running after the helper exits. That agent is outside the
  helper's session on purpose, so the timeout above does not reach it, and
  should not: killing the operator's credential agent is not the server's
  business. Stop or configure it through the provider's own tooling, for example
  `gpgconf --kill gpg-agent`.
- **Failure.** A non-zero exit, a timeout, an unresolvable executable, output
  that is empty, multi-line, oversized or not valid UTF-8, all refuse startup
  with exit code 6. The log names the variable, the executable and the status,
  and nothing else.

## Examples

Exporting these in the MCP client's `env` block, or in the shell that starts a
container, keeps the secret out of the client process:

```bash
# pass (Linux), absolute path to the binary
UNIFI_NETWORK_PASSWORD_COMMAND="/usr/bin/pass show unifi/admin"

# gpg directly, when the passphrase is already cached by gpg-agent
UNIFI_NETWORK_PASSWORD_COMMAND="/usr/bin/gpg --quiet --decrypt /etc/unifi/password.gpg"

# macOS Keychain
UNIFI_NETWORK_PASSWORD_COMMAND="/usr/bin/security find-generic-password -a admin -s unifi-mcp -w"

# 1Password CLI, with an already-signed-in session
UNIFI_NETWORK_PASSWORD_COMMAND="/usr/local/bin/op read op://Private/UniFi/password"
```

The file provider needs no contract beyond the file itself:

```bash
UNIFI_NETWORK_PASSWORD_FILE=/run/secrets/unifi_password
```

A secret file readable by group or others gets a warning; `chmod 600` it.
