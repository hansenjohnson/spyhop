"""Spyhop — sightings, effort and event logging for vessel-based surveys."""

# The one place the version is set (pyproject.toml reads it from here).
# MAJOR.MINOR.PATCH: MINOR for new features, PATCH for fixes only. MAJOR goes to 1 for
# the first release used on real surveys; after that, MAJOR changes only when data
# files change in a way older versions can't read. See CHANGELOG.md.
__version__ = "0.63.0"
VERSION_DATE = "2026-11-28"

# 0.60: the Python versions Spyhop is tested with (released ones). Keep in step with pyproject.toml,
# the start files' PY_OK and .github/workflows/tests.yml.
PYTHON_TESTED = ((3, 10), (3, 15))


def python_supported(v=None) -> bool:
    import sys
    v = v or sys.version_info
    return PYTHON_TESTED[0] <= tuple(v[:2]) <= PYTHON_TESTED[1] and v.releaselevel == "final"
