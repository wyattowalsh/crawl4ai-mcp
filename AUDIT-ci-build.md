# CI/Build Audit — mcp-crawl4ai

**Date**: 2026-04-13
**Scope**: `pyproject.toml`, `Dockerfile`, `uv.lock`, `replit.nix`, `.replit`, `.github/workflows/` (absent), build tooling, dependency configuration, packaging.

---

## Summary

| Impact | Count |
|--------|-------|
| High   | 3     |
| Medium | 6     |
| Low    | 5     |
| **Total** | **14** |

---

## High Impact

### CI-H01: No CI pipeline exists — zero automated checks

**File**: `.github/workflows/` — directory does not exist

Despite `pyproject.toml` defining comprehensive dev tooling (ruff, pytest, coverage thresholds, ty type checker), there is **no GitHub Actions workflow** or any other CI configuration. This means:
- No automated linting (`ruff check`)
- No automated type checking (`ty check`)
- No automated test execution (`pytest`)
- No coverage enforcement (`fail_under = 90`)
- No dependency vulnerability scanning

The AGENTS.md at line 123 states "Run the full suite before every PR" — but there is no CI to enforce this.

**Correction**: Create `.github/workflows/ci.yml` with at minimum:
```yaml
jobs:
  lint: ruff check .
  typecheck: ty check
  test: pytest --cov --cov-report=term-missing
```

### CI-H02: Dockerfile `builder` stage installs Playwright browsers but runtime stage may have stale binaries

**File**: `Dockerfile:21`

The build runs `uv run crawl4ai-setup` (which installs Playwright browsers into `/root/.cache/ms-playwright`) in the builder stage. The runtime stage copies the cache:
```dockerfile
COPY --from=builder /root/.cache /root/.cache
```

**Issues**:
1. The `python:3.13-slim` runtime image may have different glibc/system library versions than the builder image, causing binary incompatibility.
2. The Playwright browser version is baked at build time; `crawl4ai` updates may expect newer browser binaries, causing silent failures.
3. The `COPY --from=builder /root/.cache /root/.cache` copies the entire cache directory, not just Playwright binaries, potentially bloating the image with pip caches or other artifacts.

**Correction**: 
- Run `crawl4ai-setup` in the runtime stage instead (or both stages use the same base image, which they do — `python:3.13-slim`).
- Use `COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright` to be precise.

### CI-H03: No lockfile integrity check or reproducible build guarantee for Replit deployment

**File**: `.replit:29`

The Replit workflow runs the server from `.venv313/bin/python` — a manually-created virtualenv that is NOT managed by `uv.lock`. The official `uv.lock` (2675 lines) exists for `uv sync` usage but:
1. `.venv313/` was created with `ensurepip` and packages installed via `pip install`, not `uv sync`.
2. There is no script or documentation explaining how to set up `.venv313/` from `uv.lock`.
3. Dependency versions in `.venv313/` may drift from `uv.lock` over time.

**Correction**: Either (a) use `uv sync` to manage the venv and rename to `.venv` (uv's default), or (b) document the `.venv313/` setup procedure and add a lockfile sync script.

---

## Medium Impact

### CI-M01: `ruff>=0.15.4` lower bound is extremely aggressive — latest ruff is 0.11.x

**File**: `pyproject.toml:50`
**Text**: `"ruff>=0.15.4"`

As of April 2026, the latest ruff release is in the 0.11.x series. The bound `>=0.15.4` specifies a version that does not exist yet, meaning `uv sync --group dev` will fail with a resolution error.

**Actual behavior**: Dev dependencies are not installed in the Replit venv (confirmed: `ruff` is not installed), so this hasn't been caught.

**Correction**: Change to `"ruff>=0.11.0"` or whatever the latest stable version is.

### CI-M02: Dev dependencies not installed — no linting or testing available on Replit

**File**: `pyproject.toml:44-52` (dev dependency group)

The dev dependency group includes `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`, `ruff`, and `ty`. None of these are installed in the `.venv313/` virtualenv. Running `pytest` or `ruff` from the Replit workflow is not possible.

**Correction**: Install dev dependencies into the venv or provide a `make dev` target.

### CI-M03: `ty` type checker rules ignore 3 rule categories due to crawl4ai stub issues

**File**: `pyproject.toml:81-88`
```toml
[tool.ty.rules]
missing-argument = "ignore"
unresolved-attribute = "ignore"
not-iterable = "ignore"
```

These suppressions are documented as being caused by incomplete `crawl4ai` type stubs. While the comment explains the rationale, suppressing `missing-argument` globally means actual bugs (missing required args) will be silently accepted.

**Correction**: Consider using per-file or per-line `# type: ignore` directives instead of global suppression, or file upstream issues against `crawl4ai` for stub improvements.

### CI-M04: Dockerfile uses `pip install uv` in both stages — uv should be copied or installed via official method

**File**: `Dockerfile:7, 29`

Both stages run `pip install --no-cache-dir uv`. The official uv installation method is:
```dockerfile
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
```

Using pip to install uv adds ~30s to build time per stage and may install a different uv version between stages if the build cache is stale.

**Correction**: Use the official multi-stage copy method for uv installation.

### CI-M05: No `.dockerignore` — Docker build context includes all files

**File**: `.dockerignore` — does not exist

Without a `.dockerignore`, `docker build` sends the entire repository (including `.git/`, `node_modules/`, `.venv313/`, `uv.lock`, test files, docs/) as build context. This:
1. Slows down builds
2. May leak secrets if any are in the repo
3. Increases image layer cache invalidation

**Correction**: Create `.dockerignore`:
```
.git
.venv*
__pycache__
tests/
docs/
*.md
!README.md
!LICENSE
```

### CI-M06: `setuptools` build backend may not handle `py.typed` marker correctly

**File**: `pyproject.toml:42`
**Text**: `package-data = {"mcp_crawl4ai" = ["py.typed"]}`

The `py.typed` marker file exists (`mcp_crawl4ai/py.typed`), but setuptools `package-data` syntax for TOML uses a table format:
```toml
[tool.setuptools.package-data]
mcp_crawl4ai = ["py.typed"]
```

The inline form `{"mcp_crawl4ai" = ["py.typed"]}` should work in modern setuptools but is less commonly used and may cause issues with some build tools. Verify it's included in sdist/wheel distributions.

**Correction**: Test with `python -m build` and inspect the resulting wheel to confirm `py.typed` is included.

---

## Low Impact

### CI-L01: `replit.nix` hardcodes Nix store path for `mesa-libgbm`

**File**: `.replit:29`
**Text**: `LD_LIBRARY_PATH=/nix/store/24w3s75aa2lrvvxsybficn8y3zxd27kp-mesa-libgbm-25.1.0/lib:$LD_LIBRARY_PATH`

The Nix store hash is content-addressed and will change when the `mesa` package updates. If `replit.nix` updates the Nix channel and mesa is rebuilt, this hardcoded path will break.

**Correction**: Use a dynamic path resolution:
```bash
LD_LIBRARY_PATH=$(nix-build '<nixpkgs>' -A mesa.drivers --no-out-link)/lib:$LD_LIBRARY_PATH
```
Or reference the nix store path via a wrapper script that discovers it dynamically.

### CI-L02: `pyproject.toml` classifiers list only Python 3.13 — should include 3.14 if supported

**File**: `pyproject.toml:15`
```toml
"Programming Language :: Python :: 3.13",
```

The `requires-python = ">=3.13"` allows 3.14+, but classifiers only mention 3.13. PyPI and tool consumers use classifiers for compatibility signaling.

**Correction**: Add `"Programming Language :: Python :: 3.14"` when Python 3.14 is released and tested.

### CI-L03: No `MANIFEST.in` — sdist may miss files

**File**: `MANIFEST.in` — does not exist

While modern setuptools with `pyproject.toml` auto-includes many files, explicit `MANIFEST.in` is still recommended for including LICENSE, CHANGELOG.md, and test fixtures in source distributions.

**Correction**: Create `MANIFEST.in`:
```
include LICENSE CHANGELOG.md
recursive-include tests *.py
```

### CI-L04: Version is hardcoded in `pyproject.toml` and read via `importlib.metadata` — no single source of truth tool

**File**: `pyproject.toml:3`, `mcp_crawl4ai/__init__.py:112`

The version `0.3.1` is defined in `pyproject.toml:3` and read at runtime via `importlib.metadata.version("mcp-crawl4ai")`. This works correctly when the package is installed, but if run from source without installation, `__version__` falls back to `"0.0.0"`.

This is standard practice but worth noting: tools like `setuptools-scm` or `hatch-vcs` can derive version from git tags, eliminating the manual update step.

### CI-L05: `asyncio_default_fixture_loop_scope = "function"` is redundant

**File**: `pyproject.toml:56`

The `function` scope is already the default for `pytest-asyncio`. This setting is harmless but adds noise.

**Correction**: Remove the line or keep for explicitness (optional).

---

## Build Reproducibility Assessment

| Aspect | Status | Notes |
|--------|--------|-------|
| Lockfile exists | Yes | `uv.lock` (2675 lines) |
| Lockfile used in Docker | Yes | `uv sync --frozen` |
| Lockfile used in Replit | **No** | `.venv313/` created manually |
| CI enforces lockfile | **No** | No CI exists |
| Dependency pinning (runtime) | Yes | Via `uv.lock` |
| Dependency pinning (dev) | **Broken** | `ruff>=0.15.4` doesn't exist |
| Build backend | setuptools | Standard, well-supported |
| Multi-stage Docker | Yes | Builder + runtime |
| Image size optimization | Partial | No `.dockerignore`, full cache copy |

---

## Prioritized Correction Roadmap

### Immediate (blocks development quality)
1. **CI-H01**: Create CI pipeline with lint, typecheck, test jobs
2. **CI-M01**: Fix ruff version bound to an existing version
3. **CI-M02**: Install dev dependencies in Replit venv

### Short-term (improves reliability)
4. **CI-H03**: Align Replit venv with `uv.lock`
5. **CI-H02**: Fix Playwright binary copy in Dockerfile
6. **CI-M04**: Use official uv installation in Dockerfile
7. **CI-M05**: Add `.dockerignore`

### Low priority
8. Fix remaining Low items (L01–L05)
9. Address CI-M03 (ty suppressions) and CI-M06 (py.typed validation)
