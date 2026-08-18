# Security Policy

## Supported versions

Breadcrumbs is pre-1.0 and ships fixes on the newest release only. Please
reproduce on the latest `crumb-kit` from PyPI (or on `main`) before reporting.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: go to the
[Security tab](https://github.com/jr-mccoy/breadcrumbs/security/advisories) and
open a draft security advisory ("Report a vulnerability"). That keeps the report
private until a fix ships and gives you credit on the advisory.

Expect an acknowledgement within a week. This is a personally maintained
project, not a funded one — there is no bounty, and timelines are best-effort.

## What is in scope

The threat model is documented in [`docs/security.md`](docs/security.md); read it
first, because two things that look like vulnerabilities are documented design
positions rather than bugs.

In scope:

- **Secret leakage.** `crumb scan-secrets` / `crumb audit` gate committed memory.
  A credential shape that slips past the scanner and lands in a committed record
  is a real finding.
- **Prompt injection via memory.** Records are read by agents. Text that escapes
  the advisory framing and gets an agent to treat stored content as instruction
  is in scope; `audit`'s `instruction-like` check exists for exactly this.
- **Path traversal or writes outside the store.** Any input that makes `crumb`
  read or write outside the target project's `.project-memory/`.
- **Hook and MCP surfaces.** A payload that makes the Claude Code hooks or the
  MCP server execute something the user did not ask for, or that leaks host
  paths or environment contents to an agent.

Out of scope (by design, see `docs/security.md`):

- **Memory is advisory, never authoritative.** Current user instruction, source
  code, tests, and security policy outrank anything in `.project-memory/`. A
  record containing wrong or hostile *claims* is a data-quality problem the
  `audit`/`mark-status` surface is meant to handle, not a vulnerability.
- **The store is plain files in your repo.** Anyone who can write to the repo can
  write to the store; `.project-memory/private/` is git-ignored, not encrypted.
- **Third-party agent behaviour.** How a given agent chooses to act on a record
  it read is that agent's trust boundary, not this tool's.
