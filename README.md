# CareerHunting

Emails the weekly job-match list from the Monday job scan.

Each Monday a scheduled Claude task scans 76 employers' openings, checks each posting against my resume and requirements (Seattle area or remote, $175k+ base, senior roles in BI platforms, Tableau, data engineering and analytics enablement), and saves the results to `job-scan/latest.json`. That commit starts the **Email job matches** workflow, which sends the list with every link through Gmail.

All leads and their statuses also live on the Monday Job Leads tracker page.

## Gmail credentials (repository secrets)

Settings → Secrets and variables → Actions → New repository secret. Use one of:

| Option | Secrets |
|---|---|
| Gmail app password | `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` |
| Gmail API (OAuth) | `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, and `GMAIL_ADDRESS` |

Optional: `EMAIL_TO` sends the email to a different address than `GMAIL_ADDRESS`.

Never commit keys or passwords to the repo files.

## Files

- `job-scan/latest.json`: the most recent scan results, written by the Monday task
- `scripts/send_job_email.py`: builds and sends the email (Python standard library only)
- `.github/workflows/email-job-matches.yml`: runs the script when `latest.json` changes, or by hand from the Actions tab

Preview an email without sending it: `python scripts/send_job_email.py job-scan/latest.json --preview`
