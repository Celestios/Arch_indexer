import os
import json
import sys
from pathlib import Path
from db.connection import DbConnection
from db.repository import Repository

DEFAULT_CONFIG_JSON = {
  "lib": {
    "manual_fields": {
      "ai_summary": {
        "default": "",
        "reset_on_change": True
      },
      "pattern": {
        "values": ["Data Model", "Controller", "Service", "None"],
        "default": "None",
        "reset_on_change": False
      }
    },
    "automatic_fields": {
      "layer": {
        "values": ["Presentation", "Application", "Domain", "Infrastructure"],
        "default": "Domain",
        "assignment_rules": [
          {"value": "Presentation", "conditions": {"path_prefix": "lib/ui"}},
          {"value": "Application", "conditions": {"path_prefix": "lib/engine"}},
          {"value": "Infrastructure", "conditions": {"path_prefix": "lib/infra"}}
        ],
        "handler": "dependency_check",
        "rules": [
          {"source": "Presentation", "target": "Infrastructure", "message": "Presentation layer cannot directly call Infrastructure layer"}
        ]
      }
    }
  },
  "rust": {
    "automatic_fields": {
      "layer": {
        "values": ["Bridge", "Domain", "Persistence"],
        "default": "Domain",
        "assignment_rules": [
          {"value": "Bridge", "conditions": {"path_prefix": "rust/src/bridge"}},
          {"value": "Persistence", "conditions": {"path_prefix": "rust/src/persistence"}}
        ],
        "handler": "dependency_check",
        "rules": [
          {"source": "Domain", "target": "Persistence", "message": "Rust Domain layer should not directly depend on Persistence layer"}
        ]
      }
    }
  }
}

def initialize_workspace(project_root: Path) -> Path:
    """
    Initializes the workspace: creates output folders, deploys a default config.json,
    initializes the database schema, and loads configuration rules into the DB.
    """
    arch_dir = project_root / ".arch"
    arch_dir.mkdir(parents=True, exist_ok=True)
    
    config_file = arch_dir / "config.json"
    
    # 1. Deploy default config.json if not present
    if not config_file.exists():
        print(f"Deploying default configuration rules to {config_file}...")
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG_JSON, f, indent=2)
        except Exception as e:
            print(f"Error deploying config.json: {e}", file=sys.stderr)
            raise e
    else:
        print(f"Configuration file already exists at {config_file}.")

    # 2. Initialize the database connection & schema
    db_path = arch_dir / "arch.db"
    print(f"Initializing database at {db_path}...")
    db_conn = DbConnection(db_path)
    repository = Repository(db_conn)
    
    # This establishes connection and automatically triggers schema.sql creation
    try:
        db_conn.get_connection()
        db_conn.close()
    except Exception as e:
        print(f"Failed to initialize database schema: {e}", file=sys.stderr)
        raise e

    # 3. Read config.json and sync compliance rules to the database
    print("Syncing architectural rules to compliance catalog...")
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
            
        for prefix, prefix_conf in config.items():
            auto_fields = prefix_conf.get("automatic_fields", {})
            for field_name, field_conf in auto_fields.items():
                if field_conf.get("handler") == "dependency_check":
                    rules = field_conf.get("rules", [])
                    for rule in rules:
                        source = rule.get("source")
                        target = rule.get("target")
                        msg = rule.get("message", f"Dependency violation: {source} -> {target}")
                        severity = rule.get("severity", "Error")
                        
                        # Unique identifier for the rule
                        rule_id = f"{prefix}_{field_name}_{source}_{target}".lower().replace("/", "_").replace(".", "_")
                        repository.compliance.upsert_compliance_rule(rule_id, msg, severity)
                        
        print("Architectural compliance rules successfully synchronized.")
    except Exception as e:
        print(f"Warning: Failed to synchronize compliance rules from config.json: {e}", file=sys.stderr)
    finally:
        db_conn.close()

    return arch_dir

if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    try:
        initialize_workspace(project_root)
        print("Workspace successfully initialized.")
    except Exception as err:
        print(f"Initialization failed: {err}", file=sys.stderr)
        sys.exit(1)
