"""Pytest configuration — add non-package directories to sys.path."""
import sys
import os

# Make mcp-servers/honeybadge-nebula-mcp importable as a top-level package
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_nebula_mcp_path = os.path.join(_project_root, "mcp-servers", "honeybadge-nebula-mcp")
if _nebula_mcp_path not in sys.path:
    sys.path.insert(0, _nebula_mcp_path)

# Make analytics-worker skills importable as top-level packages (common, anomaly_detection, etc.)
_skills_path = os.path.join(_project_root, "hiclaw", "workers", "analytics-worker", "agent", "skills")
if _skills_path not in sys.path:
    sys.path.insert(0, _skills_path)
