# Security

- **Do not put GitHub, Hugging Face, or cloud tokens in this repository or in chat.**
- Use `gh auth login` or a local environment variable (`GH_TOKEN`) that is never committed.
- `compose/mongo/pwfile` is local-only and gitignored. The study password is for the disposable Docker replica set, not production.
- Community MongoDB `mongot` is preview software. Do not expose host ports 27018 / 27028 / 6333 beyond localhost.

To report a vulnerability in this harness, open a private GitHub security advisory on the repository (do not file a public issue with credentials).
