"""Windows launcher result display; report behavior stays in jira_issue_monthly."""
from __future__ import annotations

import os
import sys

from jira_paths import D_PROJECT

# Run directly as a script, only cores/python is on sys.path; `cores.*` imports need the project root.
if str(D_PROJECT) not in sys.path:
    sys.path.insert(0, str(D_PROJECT))


def execute_report() -> int:
    try:
        from jira_issue_monthly import main
        main()
    except SystemExit as exc:
        if exc.code is None or exc.code == 0:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(str(exc.code), file=sys.stderr)
        return 1
    except ModuleNotFoundError:
        print("Environment is incomplete. Run uv sync --locked in the project folder.", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, EOFError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Execution cancelled.", file=sys.stderr)
        return 130
    return 0


def launch() -> int:
    os.chdir(D_PROJECT)
    exit_code = execute_report()
    try:
        from jira_audit import record_event
        record_event(event="launcher", outcome="success" if exit_code == 0 else "failure", count=exit_code)
    except OSError:
        print("Could not write the launcher status log.", file=sys.stderr)
    # --help remains ordinary CLI output; normal report execution prints its paths.
    if not any(argument in ("-h", "--help") for argument in sys.argv[1:]):
        if exit_code == 0:
            print("Execution completed successfully.")
        else:
            print(f"Execution failed (exit code {exit_code}). Review the message above.", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(launch())
