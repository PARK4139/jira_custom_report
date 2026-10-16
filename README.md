# Jira web dashboard

On-premises Jira Server/Data Center issue trends in a local web app.

## Start

This is a uv project (`pyproject.toml`, `uv.lock`, `.python-version`). Put `uv.exe` in `tools/` (or install uv on PATH), then run (`run.cmd` is a wrapper for `uv run --locked jira-report`):

```cmd
uv sync --locked
run.cmd --url https://jira.example.com/jira --id myuser
```

Enter the Jira password in the terminal's hidden prompt. The launcher opens the dashboard in your browser. Keep the terminal open while using it; Ctrl+C stops the server. Running run.cmd again stops this checkout's previous dashboard and restarts it, reusing the local port when possible. Invalid arguments or cancelled credential input leave the running dashboard unchanged.

**Select the year in the browser dropdown. There is no `--year` argument or terminal year prompt.** The default is the current year. Supported years run from 1970 through next year. Changing the year after a successful query automatically fetches the selected year's results.

**Projects** and **Reporters** are chip fields with Jira-backed autocomplete: every selected value becomes a chip, and results load automatically once all required filters are valid. There is no **Query Jira** button. The fields are empty-looking boxes whose placeholder is just `ctrl space + tab`. Click a field or press **Ctrl+Space** to list candidates; type to narrow them with skim-style fuzzy matching (the matched characters are highlighted). Project candidates come from the projects visible to the signed-in Jira account and are shown as `Name (KEY)`. The number of projects Jira listed is shown next to the **Projects** label. If Jira's project list omits a project, typing its key (Jira keys use letters, digits, and underscores, so `L-HUB` would be a name and `LHUB` its key) looks the project up directly with `GET /rest/api/2/project/<KEY>` and adds it to the candidates; project names can only be matched when Jira lists the project. Reporter candidates are looked up in Jira as you type (`/rest/api/2/user/search`, active users only, at most 50 per lookup, with only the typed text sent) and are shown as `Display name (employee ID)`, so every reporter chip shows both the name and the ID. **Tab** turns the highlighted candidate into a chip; use the arrow keys with **Enter** to pick another candidate, and **Esc** to close the list. Remove a chip with its **×** or with **Backspace** on an empty field. Typing a finished value and pressing **Enter**, a comma, or leaving the field also makes a chip: a project must exist in Jira (otherwise it is reported instead of queried), while a reporter that does not identify exactly one known Jira user is kept as the typed user ID. JQL uses the project keys and reporter user IDs. Reload the page to refresh the project list. All inputs (year, projects, reporters with their names, period, language, and theme) are saved in the browser's localStorage and mirrored to `.local/inputs.json` through the dashboard server, so they are restored after a restart even when the dashboard comes back on a different port (a new browser origin starts with an empty localStorage). localStorage wins when both exist. The file contains only these input values (no credentials, URLs, or Jira data) and is ignored by Git; delete it to forget the saved inputs. Optional initial values:

```cmd
run.cmd --url https://jira.example.com/jira --id myuser --project DEMO OTHER --reporter user-a user-b
```

Each selected project gets a **separate named graph and a period-count/JQL table** for every period dropdown selection. Combined totals appear above these graphs for reference; a project's graph always uses its own counts. CSV exports include project keys and names. Changing the selection immediately hides stale results and automatically queries the latest filters after a 250 ms debounce. Year and period dropdown changes apply to all selected projects together. Duplicated names are distinguished by keys, and duplicate keys are queried once. Initial projects are preselected only if accessible. Empty or failed project lists disable querying until projects become available. Filters are not saved automatically.

User stories and acceptance criteria: [multiple project graphs #2](https://github.com/PARK4139/jira_custom_report/issues/2), [automatic dropdown filtering #3](https://github.com/PARK4139/jira_custom_report/issues/3).

`--url` / `--id` can be omitted to use an existing profile or terminal prompts. `--site-url` / `--email` remain aliases. `--profile work` reads existing nonsecret defaults; its legacy year is ignored by the web app. `config.example.toml` illustrates an optional profile without a year. `--no-open` prints the URL without opening a browser; `--port 8765` selects a local port (otherwise one is allocated automatically).

The old export CLI options (`--year`, `--periods`, `--configure`, `--output-dir`, and credential-storage flags) are not accepted by the web launcher. Existing stored credentials are never read automatically.

## Reporting periods

Every query loads **1week / 2week / monthly / yearly** results for the selected year, plus the four quarters **q1 / q2 / q3 / q4** (1분기-4분기). A quarter is shown in 1-week buckets (13-14 per quarter, the last one ends on the quarter's last day) and, like every other period, is cumulative from January 1: its chart starts from the Created/Resolved counts of the quarters before it, and the totals and the Resolved / Created ratio are the cumulative values the chart ends on. The table lists only the quarter's own weekly counts. Use the period dropdown to switch the chart, Created/Resolved totals, date-range table, and executed JQL. **Save CSV** writes the loaded results for every period into `outputs/`.

Graphs use **carried-forward cumulative totals**: each point adds that period's Created/Resolved counts to the preceding periods within the selected calendar year. For example, period counts `2, 0, 5` produce chart values `2, 2, 7`. Created and Resolved accumulate independently for each project, beginning at zero on January 1. Switching periods or redrawing does not accumulate the same counts again. Saved HTML and JPG use these cumulative curves. Tables, CSV, and the executed JQL retain the original per-period counts; the final cumulative point equals the year's total.

The language selector switches between **한국어 (Korean) / 영어 (English)**. The adjacent **화이트 / 다크 모드** toggle changes the theme immediately. The initial language follows the browser language; the initial theme is Light. Explicit selections are saved locally in that browser. Language, theme, and loaded period changes reuse the existing results.

**Export JPG** saves the selected period's title, filters, combined totals, and every displayed project chart in one image. It uses the current language and theme, with a width of 1800 pixels and a height that grows with the project count. Image generation happens locally in the browser. Controls are temporarily disabled while exporting and restored even if export fails. Period counts are also available in CSV; date-range tables and full JQL remain on the page. The JPG contains the chart summary.

- 1week: consecutive 7-day buckets beginning January 1.
- 2week: consecutive 14-day buckets beginning January 1.
- monthly: the 12 calendar months.
- yearly: the entire selected calendar year.

The final bucket ends January 1 of the following year. These are calendar-year buckets, not rolling windows or ISO week numbers. Queries include the start date and exclude the end date; Jira interprets dates in the account timezone. Zero counts are included. Resolved issues can have been created before the selected year, so the displayed ratio is not a cohort resolution rate.

For 2026 there are 53 + 27 + 12 + 1 buckets: **186 JQL queries per project**, plus pagination requests. Requests run sequentially and can take several minutes. Changing the period dropdown uses loaded data without a network request. Changing the year, projects, or reporters automatically fetches new data. Valid initial defaults load after the project list is ready. Rapid changes are coalesced, requests are serialized, and outdated responses are discarded. Only one report query runs at a time. A failed query hides prior results rather than showing them under the wrong filters.

## Authentication and transport

The specified server must allow Basic authentication with the Jira user ID and password. SSO-only deployments require a different authentication integration. Both http:// and https:// URLs are accepted without an extra flag; custom ports and context paths such as `/jira` are supported. Configure your environment to trust internal certificate authorities. TLS certificate validation and redirect blocking remain enabled.

An explicitly entered `http://` URL is accepted automatically; `--allow-insecure-http` is no longer required (the old flag is accepted for compatibility). A warning is printed before hidden password entry because HTTP does not encrypt the password. HTTPS is never automatically downgraded and certificate checks remain enabled.

Search requests go directly to the configured server's `/rest/api/2/search` endpoint with `startAt` pagination. The project selector uses GET /rest/api/2/project. No Cloud gateway or tenant discovery is used.

The dashboard binds exclusively to **127.0.0.1**. Its local HTTP traffic contains aggregate results and filters; the Jira password is kept only in Python server memory and sent to the specified Jira URL (HTTP is unencrypted; HTTPS remains certificate-validated). Browser requests are checked against the expected Host, Origin, and a session request token. Responses disable caching and framing. The server does not provide a filesystem browser, arbitrary Jira proxy, or a public network listener.

Passwords are never placed in browser HTML, JavaScript, API responses, files, command arguments, or logs. Hidden input fails if the terminal cannot support it. No `.env` files or `JIRA_*` environment variables are loaded. Existing Windows Credential Manager entries are not used by this web flow.

## Files and validation

`.local/<profile>.toml` contains optional nonsecret defaults. Legacy internal names `email` and `token` mean user ID and password. `.local/runtime.jsonl` records event codes and aggregate counts, excluding URLs, identities, JQL, issue bodies, and credentials. `logs/jql.jsonl` records the exact JQL sent to Jira (one line per request page, with timestamp, run ID, start offset, and total) and contains internal project and reporter IDs but no URLs or credentials; `logs/` is ignored by Git. Profiles, generated files, and environments are ignored by Git. Downloaded CSV files contain internal aggregate data.

```cmd
uv run --locked python -m unittest discover -s tests -v
```

Tests use synthetic credentials and controlled Jira responses, including real local HTTP requests to the dashboard. Actual deployment authentication still needs to be verified against your Jira server.

## Project layout

Application source and generated artifacts are separated:

| Directory | Contents |
| --- | --- |
| `cores/python/` | Python implementation and launcher modules |
| `cores/html/` | HTML, CSS, and JavaScript source assets |
| `issues/` | Local issue records and acceptance criteria |
| `outputs/` | Generated HTML, CSV, and JPG reports; ignored by Git |

`run.cmd` remains the Windows launcher. The former root-level Python module names remain as small import shims for compatibility. Implementation is separated by responsibility:

| File | Responsibility |
| --- | --- |
| `cores/python/jira_web.py` | Public dashboard entry point and compatibility exports |
| `cores/python/jira_dashboard_cli.py` | Options, credential prompt, and server lifecycle |
| `cores/python/jira_dashboard_server.py` | Loopback HTTP routes, session checks, and request validation |
| `cores/python/jira_dashboard_service.py` | Combined and per-project report aggregation |
| `cores/python/jira_projects.py` | Jira project catalog retrieval and validation |
| `cores/python/jira_reporters.py` | Jira user lookup for reporter autocomplete |
| `cores/python/jira_inputs.py` | Validated, git-ignored `.local/inputs.json` copy of the saved dashboard inputs |
| `cores/html/combo.js` | Fuzzy candidate list and Tab completion shared by the project and reporter fields |
| `cores/python/jira_dashboard_ui.py` | Dashboard composition and escaped browser configuration |
| `cores/python/jira_report_view.py` | Offline report rendering |
| `cores/html/` | Packaged HTML, CSS, chart/query scripts, translations, preferences, and exports |

Frontend resources are read with `importlib.resources` and embedded in the generated page. They do not require a static-file server, external CDN, or JavaScript build step. HTML/CSS/JS resources are included in installation packages. The offline report command writes HTML and CSV into `outputs/` by default; `--output-dir` can select another location. JPG export posts the locally generated image to the loopback server, which saves it under a unique name in `outputs/`. Restart the launcher after editing cached assets.

The regression suite also checks rendering from a packaged zip outside the checkout. When Node is available, it validates the assembled JavaScript and runs the dashboard and offline report DOM checks. The optional Playwright check uses `tests/serve_dashboard_fixture.py` and `tests/check_dashboard_features.cjs` with synthetic data.

Dashboard restart state is stored in `.local/dashboard.json` (local port, PID, workspace identity, and shutdown session token; no Jira password). A startup lock serializes competing launches. Tracked servers are stopped through an authenticated loopback request. On Windows, older untracked instances are stopped only when their command line matches this checkout's exact absolute `cores/python/launch_report.py` path; other Python applications are not terminated.
