# Issue records

Keep issue descriptions, user stories, and acceptance criteria in this directory. The canonical tracker remains GitHub Issues:

- [Project layout and output management](project-layout-and-outputs.md)
- [Fast single-query aggregation (78f878f0)](closed/report_query/fast-aggregation/78f878f0.md)
- [README showreel GIF (9a74c2e1)](closed/demo/showreel/9a74c2e1.md)

- [Multiple project graphs (#2)](https://github.com/PARK4139/jira_custom_report/issues/2)
- [Automatic dropdown filtering (#3)](https://github.com/PARK4139/jira_custom_report/issues/3)

New issues follow pk_system `cores/common/rules/issue/lifecycle.py`: `{backlog|working|closed}/{function family}/{sub family}/{uuid:8}.md`, with IDs reserved through pk_system `cores/common/scripts/issue_ids.py --root <this repo>`, function families in [families.md](families.md), and active order in [priority.md](priority.md). Do not copy Jira credentials, issue bodies, or real report data into issue files.
