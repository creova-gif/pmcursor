# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in `pmcursor`, please report it privately using **GitHub Security Advisories** ("Report a vulnerability" in the repository's Security tab).

- **Do not** open a public GitHub issue, pull request, or discussion for undisclosed vulnerabilities.
- We aim to provide an initial response within **48 hours** of receiving a report, along with an assessment and remediation timeline.

## Built-in Security Controls

`pmcursor` includes the following defense-in-depth controls:

- **SSRF Guard (`src/pmcursor/publisher.py`):** Outbound publish targets are validated against private, loopback, link-local, and metadata IP ranges before requests are dispatched.
- **Path Containment & Size Limits (`indexer.py`, `api/server.py`):** Repository indexing and API file operations enforce root path containment and a 2 MB per-file read/index cap to prevent path traversal and memory exhaustion.
- **Webhook Authentication & Deduplication:** Incoming GitHub webhook deliveries are verified using HMAC-SHA256 signatures and tracked for delivery deduplication to prevent spoofing and replay.
- **API Authentication & Bind Guard:** Non-loopback API server binds require `PMCURSOR_API_TOKEN` to be configured, preventing unauthenticated network exposure.
- **Non-Root Container (`Dockerfile`):** The container image runs as an unprivileged non-root user.
