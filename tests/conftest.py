"""Pytest configuration — add non-package directories to sys.path."""
import sys
import os
import importlib
import importlib.util

# Make mcp-servers/honeybadge-nebula-mcp importable as a top-level package
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_nebula_mcp_path = os.path.join(_project_root, "mcp-servers", "honeybadge-nebula-mcp")
if _nebula_mcp_path not in sys.path:
    sys.path.insert(0, _nebula_mcp_path)

# Make analytics-worker skills importable as top-level packages (common, anomaly_detection, etc.)
_skills_path = os.path.join(_project_root, "hiclaw", "workers", "analytics-worker", "agent", "skills")
if _skills_path not in sys.path:
    sys.path.insert(0, _skills_path)

# Hyphenated directory names cannot be imported with Python's normal import
# mechanism. Register them under their underscore aliases so that
# `anomaly-detection` is importable as `anomaly_detection` and
# `multi-step-analysis` is importable as `multi_step_analysis`.
_hyphenated_skills = {
    "anomaly_detection": "anomaly-detection",
    "multi_step_analysis": "multi-step-analysis",
}
for _module_name, _dir_name in _hyphenated_skills.items():
    if _module_name not in sys.modules:
        _pkg_path = os.path.join(_skills_path, _dir_name, "__init__.py")
        if os.path.exists(_pkg_path):
            _spec = importlib.util.spec_from_file_location(
                _module_name,
                _pkg_path,
                submodule_search_locations=[os.path.join(_skills_path, _dir_name)],
            )
            if _spec and _spec.loader:
                _module = importlib.util.module_from_spec(_spec)
                sys.modules[_module_name] = _module
                _spec.loader.exec_module(_module)
