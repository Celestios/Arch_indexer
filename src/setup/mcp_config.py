import os
import sys
import json
from pathlib import Path

def register_claude_desktop_mcp(project_root: Path):
    """Automatically registers this project's Arch MCP server in Claude Desktop config."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        print("\n[MCP Setup] Error: APPDATA environment variable not found. Skipping automatic registration.")
        return
        
    claude_dir = Path(appdata) / "Claude"
    claude_config_file = claude_dir / "claude_desktop_config.json"
    
    claude_dir.mkdir(parents=True, exist_ok=True)
    
    config = {}
    if claude_config_file.exists():
        try:
            with open(claude_config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"\n[MCP Setup] Warning: Failed to parse existing Claude Desktop config: {e}")
            
    if "mcpServers" not in config:
        config["mcpServers"] = {}
        
    python_exe = sys.executable
    # Cross-platform venv detection
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        python_exe = str(venv_python)
        
    server_path = project_root / "src" / "interface" / "server.py"
    
    config["mcpServers"]["arch"] = {
        "command": python_exe,
        "args": [str(server_path)],
        "env": {
            "ARCH_PROJECT_ROOT": str(project_root)
        }
    }
    
    try:
        with open(claude_config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"\n[MCP Setup] Registered Arch in Claude Desktop: {claude_config_file}")
    except Exception as e:
        print(f"\n[MCP Setup] Warning: Failed to write Claude Desktop configuration ({e})")
