# CareerHunting

Emails the weekly job-match list from the Monday job scan.

Each Monday a scheduled Claude task scans 81 employers' openings, checks each posting against my resume and requirements (Seattle area or remote, $175k+ base, senior roles in BI platforms, Tableau, data engineering and analytics enablement), and saves the results to `job-scan/latest.json`. That commit starts the **Email job matches** workflow. It checks every job link first (Workday, Greenhouse and Lever postings through each site's own job data, other sites by loading the page), leaves closed postings out, sends the list through Gmail, and saves the results to `job-scan/link-check.json` so the Monday scan can mark closed jobs on the tracker.

All leads and their statuses also live on the Monday Job Leads tracker page.

## On-demand job scan

Run the **On-demand job scan** scheduled task whenever you want a fresh list (it has no schedule; start it with "Run now"). It reads `Company_List` from a fresh clone of `main`, so your latest edits always count, and searches every employer for jobs that fit my resume: US remote or Seattle area, $150k+ a year (or $72+/hour for contracts), full-time or contract. It saves the matches to `job-scan/on-demand.json`, which starts the **Check on-demand job links** workflow. That workflow loads every link live, asking servers and caches for a fresh copy, and saves the results to `job-scan/on-demand-link-check.json`. The scan then posts only the links that passed, grouped into Excellent fits and Good fits. These files are separate from the Monday scan's, so the two never overwrite each other.

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
- `scripts/send_job_email.py`: checks the links, then builds and sends the email (Python standard library only)
- `scripts/check_links.py`: decides whether each job link is open, closed or couldn't be checked
- `job-scan/link-check.json`: the latest link check results, saved by the workflow
- `job-scan/on-demand.json`: the most recent on-demand scan results, written by the on-demand task
- `scripts/check_on_demand_links.py`: checks every link in `on-demand.json` and saves `job-scan/on-demand-link-check.json`
- `.github/workflows/check-on-demand-links.yml`: runs that check when `on-demand.json` changes, or by hand from the Actions tab
- `Company_List`: the employers both scans cover; add or remove a line to change the list
- `.github/workflows/email-job-matches.yml`: runs the script when `latest.json` changes, or by hand from the Actions tab (choose "Only check the links" to skip the email)

Preview an email without sending it: `python scripts/send_job_email.py job-scan/latest.json --preview`
