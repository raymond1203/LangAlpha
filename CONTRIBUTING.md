# Contributing to LangAlpha

Thanks for your interest in contributing to LangAlpha! This guide covers how to set up your development environment and submit changes.

## Prerequisites

**Docker setup (recommended):**
- Docker and Docker Compose

**Manual setup:**
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker (for PostgreSQL and Redis)
- Node.js 22+ and pnpm (for the web UI)

See the [README](README.md#getting-started) for full setup instructions.

## Development Workflow

1. **Fork** the repository and clone your fork
2. **Set up** your environment following the [Getting Started](README.md#getting-started) guide
3. **Create a branch** for your change: `git checkout -b my-feature`
4. **Make your changes** — the backend supports hot-reload, so changes to `src/` take effect immediately
5. **Run tests** to verify nothing is broken:
   ```bash
   make test       # backend unit tests
   make test-web   # frontend unit tests
   make lint       # linters
   ```
6. **Commit** with a clear message describing the change
7. **Open a pull request** against `main`

## Code Style

**Python:**
- Linted with [Ruff](https://docs.astral.sh/ruff/) — run `uv run ruff check src/` to check
- Async-first: use `async def` for handlers and services
- No ORM — raw SQL via psycopg3

**Frontend (TypeScript/React):**
- Linted with ESLint 9 (flat config) — run `cd web && pnpm lint` to check
- Components use shadcn/ui + Tailwind CSS

## Tests

- **Unit tests must pass** before merging — these run in CI automatically
- **Integration tests are optional** locally — they require a running PostgreSQL instance and skip gracefully when API keys are absent
- Backend tests: `uv run pytest tests/unit/ -v`
- Frontend tests: `cd web && pnpm vitest run`

## Reporting Issues

Open a [GitHub Issue](https://github.com/ginlix-ai/langalpha/issues) with:
- What you expected vs what happened
- Steps to reproduce
- Relevant logs or screenshots

## Questions?

Open a [GitHub Discussion](https://github.com/ginlix-ai/langalpha/discussions) or comment on a relevant issue.
