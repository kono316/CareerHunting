#!/usr/bin/env python3
"""Check every link from an on-demand job scan live, right now, with no cached copies.

Reads job-scan/on-demand.json (written by the on-demand scan) and writes
job-scan/on-demand-link-check.json with one result per link:
  open        the posting is live on the employer's own site
  closed      the posting is gone, expired or redirects away
  unknown     the site didn't give a clear answer
  unofficial  the link isn't on the employer's own career site or applicant-tracking portal

The results carry the scan's runId so the scan can tell they belong to it and not to an earlier run.

Usage:
  python scripts/check_on_demand_links.py job-scan/on-demand.json job-scan/on-demand-link-check.json
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_links import check_link, clean_url, is_official  # noqa: E402

GROUPS = ("excellent", "good")


def check_one(job):
    url = clean_url(job.get("url") or "")
    if not url.startswith(("https://", "http://")):
        status, reason = "closed", "not a web link"
    elif not is_official(url, job.get("company")):
        status, reason = "unofficial", "not the employer's own job site"
    else:
        status, reason = check_link(url)
    return {"url": url, "title": job.get("title"), "company": job.get("company"),
            "group": job.get("_group"), "status": status, "reason": reason}


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: check_on_demand_links.py job-scan/on-demand.json job-scan/on-demand-link-check.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    jobs = []
    for group in GROUPS:
        for job in data.get(group) or []:
            jobs.append({**job, "_group": group})

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check_one, jobs))

    with open(sys.argv[2], "w", encoding="utf-8") as f:
        json.dump({"runId": data.get("runId"), "date": data.get("date"),
                   "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "results": results}, f, indent=2, ensure_ascii=False)
        f.write("\n")

    counts = {s: sum(r["status"] == s for r in results) for s in ("open", "closed", "unknown", "unofficial")}
    print(f"::notice title=On-demand link check::run {data.get('runId')}: {counts['open']} open, "
          f"{counts['closed']} closed, {counts['unknown']} couldn't be checked, "
          f"{counts['unofficial']} not on the employer's own site")
    for r in results:
        if r["status"] != "open":
            print(f"::warning title=Link {r['status']}::{r['title']} ({r['company']}): {r['reason']}")


if __name__ == "__main__":
    main()
