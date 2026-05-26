"""
Pre-flight check — run before starting the bot.
Verifies Python version, dependencies, and .env configuration.
"""
import sys
import os

PASS = "  [OK]"
FAIL = "  [MISSING]"
errors = []

print("=" * 50)
print("  UAEOPS Bot — Setup Check")
print("=" * 50)

# Python version
major, minor = sys.version_info[:2]
if major >= 3 and minor >= 11:
    print(f"{PASS} Python {major}.{minor}")
else:
    print(f"{FAIL} Python {major}.{minor} — need 3.11 or higher")
    errors.append("Upgrade Python to 3.11+: https://www.python.org/downloads/")

# Required packages
packages = {
    "slack_bolt":   "slack-bolt",
    "anthropic":    "anthropic",
    "apscheduler":  "APScheduler",
    "dateparser":   "dateparser",
    "dotenv":       "python-dotenv",
}
for module, package in packages.items():
    try:
        __import__(module)
        print(f"{PASS} {package}")
    except ImportError:
        print(f"{FAIL} {package}")
        errors.append(f"Run: pip install -r requirements.txt")

# .env file
env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_path):
    print(f"{PASS} .env file found")
else:
    print(f"{FAIL} .env file not found")
    errors.append("Create .env from .env.example and fill in your tokens")

# Load and check env vars
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

required_vars = {
    "SLACK_BOT_TOKEN":  "xoxb-",
    "SLACK_APP_TOKEN":  "xapp-",
    "ANTHROPIC_API_KEY": "sk-ant-",
}
for var, prefix in required_vars.items():
    val = os.getenv(var, "")
    if not val:
        print(f"{FAIL} {var} — not set in .env")
        errors.append(f"Add {var} to your .env file (see HANDOVER.md Step 2-3)")
    elif not val.startswith(prefix):
        print(f"{FAIL} {var} — looks wrong (should start with {prefix})")
        errors.append(f"Check {var} in .env — should start with '{prefix}'")
    else:
        print(f"{PASS} {var} ({val[:12]}...)")

print("=" * 50)

if errors:
    print(f"\nFound {len(errors)} issue(s) to fix:\n")
    for i, e in enumerate(errors, 1):
        print(f"  {i}. {e}")
    print()
    sys.exit(1)
else:
    print("\nAll checks passed — ready to start the bot!\n")
    sys.exit(0)
