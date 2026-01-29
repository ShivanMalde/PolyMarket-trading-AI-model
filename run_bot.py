#!/usr/bin/env python3
import sys
from pathlib import Path

# Load a .env file
def load_env_file(env_file_path):
    env_path = Path(env_file_path)
    if not env_path.exists():
        print(f"Error: {env_file_path} not found")
        sys.exit(1)
    
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                # Export to environment
                print(f"Loading {key}={value}")
                sys.stdout.flush()
                sys.environ[key] = value

if __name__ == "__main__":
    # Load environment from file (first argument)
    if len(sys.argv) > 1:
        load_env_file(sys.argv[1])
    else:
        print("Usage: python run_bot.py <env_file>")
        sys.exit(1)
    
    # Run the bot
    sys.argv = ["cli.py", "run-autonomous-trader"]
    exec(open('scripts/python/cli.py').read())
