# Contributing

Thanks for improving the lab. Keep changes deterministic, synthetic, and safe to run without charger hardware.

## Local checks

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy telemetry_lab
pytest --cov=telemetry_lab --cov-branch
```

When runtime dependencies change, regenerate the hashed deployment lock with:

```bash
pip-compile pyproject.toml --output-file requirements.lock --generate-hashes --strip-extras
pip-compile requirements-build.in --output-file requirements-build.lock --generate-hashes
pip-audit --requirement requirements.lock
pip-audit --requirement requirements-build.lock
```

New behavior should begin with a failing test. Fault injectors must return new immutable samples, record their ground-truth event, and be reproducible from a fixed seed. Never add live charger-control commands, credentials, or real customer telemetry.

Use conventional commits (`feat:`, `fix:`, `test:`, `docs:`) and describe the validation performed in pull requests.
