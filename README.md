# Jira Custom Report

A local web dashboard for exploring Jira Server and Data Center issue trends by project, reporter, and reporting period.

For setup screenshots and a guided walkthrough, see the [Quick Start Guide](QUICK_START.md).

<!-- showreel:start -->
![10-second dashboard showreel](docs/showreel.gif)

The terminal sequence is reconstructed from the actual `run.cmd` output; it is not a terminal recording. The dashboard sequence uses fictional demo data, so all displayed values are invented. To rebuild the GIF, run `node tests/capture_showreel.cjs`, then `uv run --no-project --with pillow python tests/build_showreel.py`.
<!-- showreel:end -->

## Quick start

Requirements: Windows, Git, and [uv](https://docs.astral.sh/uv/). Place `uv.exe` in `tools/` or install uv on `PATH`.

```bat
uv sync --locked
run.cmd --url https://jira.example.com/jira --id myuser
```

Enter your Jira password at the hidden terminal prompt. The launcher opens the dashboard in your browser. Keep the terminal open while using it; press **Ctrl+C** to stop the server. The dashboard listens only on `127.0.0.1` and chooses an available local port by default.

You can omit `--url` and `--id` to use a saved profile or enter them when prompted. Use `--profile work` to select another profile, `--port 8765` to choose a port, or `--no-open` to print the dashboard URL without opening a browser. Optional initial filters can be supplied with `--project` and `--reporter`:

```bat
run.cmd --url https://jira.example.com/jira --id myuser --project DEMO OTHER --reporter user-a user-b
```

Select the year in the dashboard. The default is the current year; supported years range from 1970 through next year.

## Dashboard

Project and reporter filters use searchable chips with Jira-backed autocomplete. Click a field or press **Ctrl+Space** to show candidates, type to filter, and press **Tab** to add the highlighted candidate. Use the arrow keys and **Enter** to choose another result. Queries run automatically when the filters are valid; there is no query button.

The dashboard displays combined totals and a separate graph and period table for each selected project. Changing the year, projects, or reporters fetches a new report. Switching the reporting period reuses the loaded data. Stale results are hidden while filters change or a request is in progress.

Each report is fetched with one paged Jira search; all reporting periods are counted locally from that result. Supported periods are:

- **Daily:** one bucket per calendar day.
- **Weekly:** consecutive seven-day buckets beginning January 1.
- **Monthly:** the twelve calendar months.
- **Quarterly:** Q1 through Q4, aligned to calendar quarters.
- **Yearly:** one bucket for the full calendar year.

Charts show cumulative created and resolved totals from January 1. Tables, CSV exports, and displayed JQL retain the per-period counts. Resolved issues may have been created before the selected year, so the resolved-to-created ratio is not a cohort resolution rate.

The language selector supports Korean and English; the theme selector supports light and dark modes. The selected language, theme, period, year, projects, and reporters are saved in browser storage and mirrored to `.local/inputs.json` so they can be restored after a server restart. This file contains filter values only and is ignored by Git.

**Save CSV** exports the loaded report for all periods. **Export JPG** saves the currently displayed summary and project charts as an image. Files are written to `outputs/`.

## Try the dashboard without Jira

`demo.cmd` runs the same dashboard with fictional data. It needs no Jira URL, user ID, or password and makes no Jira requests.

```bat
demo.cmd
demo.cmd --no-open
demo.cmd --port 8765
```

The demo provides twelve fictional projects and eight fictional users. Its generated issue data is deterministic for a year and project. Demo preferences are stored separately in `.local/demo-inputs.json`; they do not overwrite `.local/inputs.json`.

## Authentication and security

The Jira server must allow Basic authentication. SSO-only deployments need a separate authentication integration. Both HTTP and HTTPS URLs are supported, including custom ports and context paths. HTTPS certificate verification and redirect blocking remain enabled. An HTTP URL prints a warning because HTTP does not encrypt credentials in transit.

The password stays in server memory and is sent only to the configured Jira server. It is not placed in browser content, command arguments, files, or logs. The dashboard binds to loopback, validates browser requests against the expected host, origin, and session token, and does not expose a general filesystem or Jira proxy.

By default, enter the password at each launch. The optional **Auto login** control can save or remove the current Jira login in Windows Credential Manager after confirmation. When enabled, the saved login is used only for its associated Jira URL and user ID. Start with `--no-auto-login` to require a password for that launch.

## Development

Run `dev.cmd` to start the demo dashboard with automatic reload:

```bat
dev.cmd
dev.cmd --no-open
dev.cmd --port 8766
```

Changes to HTML, CSS, or JavaScript assets reload the browser. Changes to Python files under `cores/python/` restart the demo server; the default port is `8765`, so the browser can reconnect to the restarted server. The development dashboard uses fictional data and never contacts Jira. The normal `run.cmd` and `demo.cmd` launchers do not watch files.

Frontend assets are embedded into the page with `importlib.resources`; no separate static server, CDN, or JavaScript build is required. GIF capture uses Chrome and Node. Pillow is only needed to build the GIF and is not a project dependency.

## Tests

Run the Python test suite with:

```bat
uv run --locked python -m unittest discover -s tests -v
```

Some browser checks also use Node and Chrome. Tests use synthetic Jira credentials and controlled responses; they do not verify authentication against a live Jira deployment.

## Project layout

| Path | Contents |
| --- | --- |
| `cores/python/` | Python application, dashboard server, and launchers |
| `cores/html/` | Dashboard HTML, CSS, and JavaScript assets |
| `docs/` | Showreel and Quick Start screenshots |
| `tests/` | Unit tests and browser checks |
| `issues/` | Local issue records and acceptance criteria |
| `outputs/` | Generated reports; ignored by Git |
| `.local/` | Local profiles, saved inputs, and runtime state; ignored by Git |
