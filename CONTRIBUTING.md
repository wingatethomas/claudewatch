# Contributing

## Setup

```bash
git clone https://github.com/wingatethomas/claudewatch.git
cd claudewatch
uv sync
uv run pre-commit install
```

## Dev

```bash
uv run claudewatch          # run the app
uv run pytest -v             # tests
uv run ruff check .          # lint
```

## PRs

- One branch per feature/fix
- Type hints on all functions
- Tests for new backend logic
- Run lint + tests before pushing
