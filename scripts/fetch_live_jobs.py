"""Pull open jobs live from each employer's own hiring system and keep the ones that may fit Mike.

Run by the "Find live jobs" GitHub Action every Monday before the job scan (or by hand from the
Actions tab). Every job in the output came straight from the employer's job data at run time, so
its link is live at that moment. Nothing comes from search engines or cached pages.

Output: job-scan/live-jobs.json
  generatedAt  when the run finished (UTC)
  jobs         candidate jobs: company, title, url, location, workMode, postedDate, payText,
               payMin, payMax, source
  sources      one row per employer source: ok / error, how many jobs were read and kept
  manualCheck  employers whose sites can't be read this way, with their careers page

To add or fix an employer, edit the SOURCES list below (the "ats" value says which system it uses).
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------------------------
# Employers and where their jobs live. "company" is the name shown in results.
# workday: host, tenant, site (from a posting URL: https://<host>/<site>/job/...)
# greenhouse / lever / ashby / breezy: the board name from the employer's job-board URL
# eightfold: the careers host plus the company's domain
# amazon: amazon.jobs search (covers Twitch)
# ---------------------------------------------------------------------------------------------
SOURCES = [
    # Big employers on Workday (host, tenant, site taken from real posting links)
    {"company": "Salesforce (Tableau)", "ats": "workday", "host": "salesforce.wd12.myworkdayjobs.com", "tenant": "salesforce", "site": "External_Career_Site"},
    {"company": "NVIDIA", "ats": "workday", "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "NVIDIAExternalCareerSite"},
    {"company": "Zillow", "ats": "workday", "host": "zillow.wd5.myworkdayjobs.com", "tenant": "zillow", "site": "Zillow_Group_External"},
    {"company": "Netflix", "ats": "workday", "host": "netflix.wd108.myworkdayjobs.com", "tenant": "netflix", "site": "netflix"},
    {"company": "T-Mobile", "ats": "workday", "host": "tmobile.wd1.myworkdayjobs.com", "tenant": "tmobile", "site": "External"},
    {"company": "Gates Foundation", "ats": "workday", "host": "gatesfoundation.wd1.myworkdayjobs.com", "tenant": "gatesfoundation", "site": "Gates"},
    {"company": "Blue Origin", "ats": "workday", "host": "blueorigin.wd5.myworkdayjobs.com", "tenant": "blueorigin", "site": "blueorigin"},
    {"company": "CrowdStrike", "ats": "workday", "host": "crowdstrike.wd5.myworkdayjobs.com", "tenant": "crowdstrike", "site": "crowdstrikecareers"},
    {"company": "Nordstrom", "ats": "workday", "host": "nordstrom.wd501.myworkdayjobs.com", "tenant": "nordstrom", "site": "nordstrom_careers"},
    # Workday sites still to be confirmed by the first run (an error here just means fix or remove)
    {"company": "Expedia Group", "ats": "workday", "host": "expedia.wd108.myworkdayjobs.com", "tenant": "expedia", "site": "search"},
    {"company": "Disney", "ats": "workday", "host": "disney.wd5.myworkdayjobs.com", "tenant": "disney", "site": "disneycareer"},
    {"company": "The Home Depot", "ats": "workday", "host": "homedepot.wd5.myworkdayjobs.com", "tenant": "homedepot", "site": "CareerDepot"},
    {"company": "Warner Bros. Discovery", "ats": "workday", "host": "warnerbros.wd5.myworkdayjobs.com", "tenant": "warnerbros", "site": "global"},
    {"company": "REI", "ats": "workday", "host": "rei.wd5.myworkdayjobs.com", "tenant": "rei", "site": "rei"},
    {"company": "Activision Blizzard", "ats": "workday", "host": "activision.wd1.myworkdayjobs.com", "tenant": "activision", "site": "External"},
    {"company": "Chewy", "ats": "workday", "host": "chewy.wd5.myworkdayjobs.com", "tenant": "chewy", "site": "External"},
    # Eightfold career sites
    {"company": "Microsoft", "ats": "eightfold", "host": "apply.careers.microsoft.com", "domain": "microsoft.com"},
    {"company": "Starbucks", "ats": "eightfold", "host": "apply.starbucks.com", "domain": "starbucks.com"},
    # Amazon (includes Twitch)
    {"company": "Amazon / Twitch", "ats": "amazon"},
    # Greenhouse boards
    {"company": "Wizards of the Coast (Hasbro)", "ats": "greenhouse", "board": "hasbro"},
    {"company": "The Pokémon Company International", "ats": "greenhouse", "board": "pokemoncareers"},
    {"company": "SpaceX", "ats": "greenhouse", "board": "spacex"},
    {"company": "Riot Games", "ats": "greenhouse", "board": "riotgames"},
    {"company": "Epic Games", "ats": "greenhouse", "board": "epicgames"},
    {"company": "Mythical Games", "ats": "greenhouse", "board": "mythicalgames"},
    {"company": "Anduril", "ats": "greenhouse", "board": "andurilindustries"},
    {"company": "Smartsheet", "ats": "greenhouse", "board": "smartsheet"},
    {"company": "Bezos Academy", "ats": "greenhouse", "board": "day1academies"},
    {"company": "Otter", "ats": "greenhouse", "board": "otter"},
    {"company": "Xealth", "ats": "greenhouse", "board": "xealth"},
    {"company": "Possible Finance", "ats": "greenhouse", "board": "possiblefinancialinc"},
    {"company": "Newsela", "ats": "greenhouse", "board": "newsela"},
    {"company": "dbt Labs", "ats": "greenhouse", "board": "dbtlabsinc"},
    {"company": "Grafana Labs", "ats": "greenhouse", "board": "grafanalabs"},
    {"company": "AlphaSense", "ats": "greenhouse", "board": "alphasense"},
    {"company": "DAS42", "ats": "greenhouse", "board": "das42"},
    {"company": "InterWorks", "ats": "greenhouse", "board": "interworks"},
    {"company": "Sigma Computing", "ats": "greenhouse", "board": "sigmacomputing"},
    {"company": "Rollstack", "ats": "greenhouse", "board": "rollstack"},
    # Lever boards
    {"company": "Spotify", "ats": "lever", "board": "spotify"},
    {"company": "Brooks Running", "ats": "lever", "board": "brooksrunning"},
    {"company": "Omnidian", "ats": "lever", "board": "omnidian"},
    {"company": "Opala", "ats": "lever", "board": "Opala"},
    {"company": "Outreach", "ats": "lever", "board": "outreach"},
    {"company": "Findem", "ats": "lever", "board": "findem"},
    {"company": "Shipium", "ats": "lever", "board": "shipium"},
    # Ashby and Breezy boards
    {"company": "Hex", "ats": "ashby", "board": "hex"},
    {"company": "Aimpoint Digital", "ats": "breezy", "board": "aimpoint-digital"},
]

# Employers whose sites can't be read this way yet. Listed in the output so they still get checked by hand.
MANUAL = [
    ("Oracle", "https://careers.oracle.com"), ("ServiceNow", "https://careers.servicenow.com"),
    ("Costco", "https://www.costco.com/jobs.html"), ("Electronic Arts / PopCap", "https://jobs.ea.com"),
    ("Bungie (PlayStation)", "https://careers.playstation.com"), ("Nintendo of America", "https://careers.nintendo.com/jobs"),
    ("L3Harris", "https://careers.l3harris.com"), ("Fred Hutch", "https://www.fredhutch.org/en/about/careers.html"),
    ("NOAA", "https://www.usajobs.gov"), ("Sparq (Amplify)", "https://ats.rippling.com/sparq/jobs"),
    ("World Wide Technology", "https://www.wwt.com/careers"), ("Sonos", "https://www.sonos.com/en-us/careers"),
    ("Frontline Education", "https://www.frontlineeducation.com/careers"), ("Edward Jones", "https://careers.edwardjones.com"),
]

# ---------------------------------------------------------------------------------------------
# What counts as a possible fit (the Monday scan then rates each one against Mike's background)
# ---------------------------------------------------------------------------------------------
SEARCH_TERMS = [
    "Tableau", "Power BI", "business intelligence", "data engineer", "analytics engineer",
    "data governance", "analytics manager", "data platform", "technical program manager data",
    "solutions architect data", "data architect", "Fabric",
]
TITLE_RE = re.compile(
    r"tableau|power ?bi|business intelligence|\bbi\b|analytic|data engineer|data platform|data governance|"
    r"data architect|data warehouse|data & ai|data and ai|data strateg|data product|data quality|data management|"
    r"data infrastructure|data systems|data scien|insights|reporting|semantic|visualization|enablement|"
    r"success architect|solutions? (architect|engineer|consultant)|technical (program|account) manager|"
    r"program manager.*(data|analytics|platform)|\bfabric\b|databricks|snowflake|alteryx", re.I)
LEVEL_RE = re.compile(r"\b(senior|sr\.?|lead|staff|principal|manager|director|head|architect|iii|iv|v|5|6|l5|l6|ic4|ic5)\b", re.I)
EXCLUDE_RE = re.compile(
    r"\b(intern|internship|junior|jr\.?|associate|entry|new grad|graduate|apprentice|co-?op|"
    r"account executive|sales executive|sales representative|recruiter|"
    r"store|warehouse|technician|mechanic|nurse|physician)\b", re.I)
AREA = ("seattle", "shoreline", "bothell", "kirkland", "redmond", "bellevue", "woodinville", "lynnwood",
        "edmonds", "mountlake terrace", "everett", "mukilteo", "issaquah", "mercer island", "renton",
        "tukwila", "kent", "seatac", "puget sound", "greater seattle")
US_WORDS = ("united states", "usa", "u.s.", "us-", "us ", "(us)", "us remote", "remote us", "north america", "anywhere")
NON_US = ("canada", "toronto", "vancouver", "london", "united kingdom", " uk", "india", "bangalore", "bengaluru",
          "hyderabad", "ireland", "dublin", "germany", "poland", "mexico", "brazil", "singapore", "japan",
          "australia", "philippines", "costa rica", "netherlands", "spain", "france", "israel", "sweden", "stockholm")
PAY_FLOOR = 175_000
MAX_PAGES = 3          # Workday pages of 20 per search term
DETAIL_LIMIT = 60      # posting pages fetched per Workday/Eightfold source to read pay and full locations

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def http(url, data=None, accept="application/json"):
    headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9",
               "Cache-Control": "no-cache"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if "json" in accept else raw
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 + attempt * 3)
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = str(e)[:120]
            time.sleep(2)
    raise RuntimeError(last or "request failed")


# ---------------------------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------------------------
def text_of(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(h or "")))).strip()


def title_ok(title):
    return bool(TITLE_RE.search(title or "")) and bool(LEVEL_RE.search(title or "")) and not EXCLUDE_RE.search(title or "")


def where(location, remote_flag=False):
    """'area', 'remote', or None for a location that doesn't fit."""
    loc = (location or "").lower()
    if any(a in loc for a in AREA):
        return "area"
    if ("washington" in loc and "dc" not in loc and "d.c" not in loc) or re.search(r"\bwa\b", loc):
        return "area"
    remoteish = remote_flag or "remote" in loc or "virtual" in loc or "anywhere" in loc
    if remoteish and not any(n in loc for n in NON_US):
        return "remote"
    if re.fullmatch(r"\s*(united states|usa|us)( of america)?[\s,\-]*(multiple locations)?\s*", loc):
        return "remote?"
    return None


PAY_RE = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])(?:\.\d{2})?\s*(?:USD)?\s*(?:-|–|—|to)\s*(?:USD\s*)?"
    r"\$?\s?(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])", re.I)


def money(s):
    s = s.replace(",", "").replace(" ", "")
    return int(float(s[:-1]) * 1000) if s.lower().endswith("k") else int(float(s))


def pay_from(text):
    """(payMin, payMax, payText) using the highest annual range in the text, or Nones if none is posted."""
    best = None
    for m in PAY_RE.finditer(text or ""):
        lo, hi = money(m.group(1)), money(m.group(2))
        if hi < 40_000 or hi > 2_000_000 or lo > hi:
            continue
        if best is None or hi > best[1]:
            best = (lo, hi)
    if not best:
        return None, None, "pay not posted"
    return best[0], best[1], f"${best[0] / 1000:,.1f}k–${best[1] / 1000:,.1f}k".replace(".0k", "k")


def mode_of(location, place):
    loc = (location or "").lower()
    if "remote" in loc or place in ("remote", "remote?"):
        return "Remote"
    if "hybrid" in loc:
        return "Hybrid"
    return "Not stated"


def keep(job, out, stats):
    """Apply location and pay rules, then add to results."""
    place = where(job["location"], job.pop("_remote", False))
    if not place:
        return
    if job.get("payMax") and job["payMax"] < PAY_FLOOR:
        return
    job.setdefault("workMode", mode_of(job["location"], place))
    if place == "remote?":
        job["note"] = "listed as United States; check whether it is remote"
    out.append(job)
    stats["kept"] += 1


def job(company, title, url, location, posted=None, pay_text="", source="", remote=False, mode=None):
    lo, hi, pt = pay_from(pay_text)
    j = {"company": company, "title": title.strip(), "url": url, "location": (location or "").strip(),
         "postedDate": posted, "payMin": lo, "payMax": hi, "payText": pt, "source": source, "_remote": remote}
    if mode:
        j["workMode"] = mode
    return j


# ---------------------------------------------------------------------------------------------
# Readers, one per hiring system
# ---------------------------------------------------------------------------------------------
def read_workday(s, out, stats):
    base = f"https://{s['host']}/wday/cxs/{s['tenant']}/{s['site']}"
    seen = {}
    for term in SEARCH_TERMS:
        for page in range(MAX_PAGES):
            data = http(f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term})
            posts = data.get("jobPostings") or []
            stats["read"] += len(posts)
            for p in posts:
                if p.get("externalPath") and title_ok(p.get("title")):
                    seen.setdefault(p["externalPath"], p)
            if len(posts) < 20:
                break
            time.sleep(0.3)
    for i, (path, p) in enumerate(seen.items()):
        url = f"https://{s['host']}/{s['site']}{path}"
        loc, desc, posted, remote = p.get("locationsText") or "", "", p.get("postedOn"), False
        if i < DETAIL_LIMIT:
            try:
                d = http(f"{base}{path}").get("jobPostingInfo") or {}
                if d.get("canApply") is False:
                    continue
                locs = [d.get("location") or ""] + list(d.get("additionalLocations") or [])
                loc = "; ".join(x for x in locs if x) or loc
                desc = text_of(d.get("jobDescription"))
                posted = d.get("startDate") or posted
                remote = "remote" in (d.get("remoteType") or "").lower()
                url = d.get("externalUrl") or url
            except RuntimeError:
                pass
            time.sleep(0.2)
        keep(job(s["company"], p["title"], url, loc, posted, desc, "workday", remote), out, stats)


def read_eightfold(s, out, stats):
    host, domain = s["host"], s["domain"]
    seen = {}
    for term in SEARCH_TERMS:
        q = urllib.parse.urlencode({"domain": domain, "query": term, "start": 0, "num": 100, "sort_by": "relevance"})
        try:
            data = http(f"https://{host}/api/apply/v2/jobs?{q}")
            posts = data.get("positions") or []
        except RuntimeError:
            q2 = urllib.parse.urlencode({"domain": domain, "query": term, "start": 0})
            data = http(f"https://{host}/api/pcsx/search?{q2}")
            posts = (data.get("data") or {}).get("positions") or []
        stats["read"] += len(posts)
        for p in posts:
            title = p.get("name") or p.get("title") or ""
            if title_ok(title):
                seen.setdefault(str(p.get("id")), p)
        time.sleep(0.3)
    for i, (pid, p) in enumerate(seen.items()):
        title = p.get("name") or p.get("title") or ""
        locs = p.get("locations") or p.get("standardizedLocations") or [p.get("location") or ""]
        loc = "; ".join(str(x) for x in locs if x)
        url = p.get("canonicalPositionUrl") or p.get("positionUrl") or f"https://{host}/careers/job/{pid}"
        if url.startswith("/"):
            url = f"https://{host}{url}"
        desc = ""
        if i < DETAIL_LIMIT:
            try:
                d = http(f"https://{host}/api/apply/v2/jobs/{pid}?domain={domain}")
                desc = text_of(d.get("job_description") or "")
            except RuntimeError:
                pass
        remote = "remote" in (str(p.get("work_location_option") or p.get("workLocationOption") or "")).lower()
        posted = p.get("t_create") or p.get("postedTs")
        if isinstance(posted, (int, float)):
            posted = dt.datetime.fromtimestamp(posted, dt.timezone.utc).date().isoformat()
        keep(job(s["company"], title, url, loc, posted, desc, "eightfold", remote), out, stats)


def read_amazon(s, out, stats):
    seen = {}
    for term in SEARCH_TERMS:
        for loc in ("Seattle, Washington, USA", "Bellevue, Washington, USA", "Redmond, Washington, USA"):
            q = urllib.parse.urlencode({"base_query": term, "loc_query": loc, "radius": "24km",
                                        "result_limit": 100, "offset": 0, "sort": "relevant"})
            data = http(f"https://www.amazon.jobs/en/search.json?{q}")
            posts = data.get("jobs") or []
            stats["read"] += len(posts)
            for p in posts:
                if title_ok(p.get("title")):
                    seen.setdefault(p.get("job_path"), p)
            time.sleep(0.3)
    for path, p in seen.items():
        loc = p.get("normalized_location") or p.get("location") or ""
        text = " ".join(str(p.get(k) or "") for k in ("description", "preferred_qualifications", "basic_qualifications"))
        company = "Twitch" if "twitch" in (p.get("company_name") or "").lower() else "Amazon"
        keep(job(company, p["title"], f"https://www.amazon.jobs{path}", loc, p.get("posted_date"), text, "amazon.jobs"), out, stats)


def read_greenhouse(s, out, stats):
    data = http(f"https://boards-api.greenhouse.io/v1/boards/{s['board']}/jobs?content=true")
    posts = data.get("jobs") or []
    stats["read"] += len(posts)
    for p in posts:
        if not title_ok(p.get("title")):
            continue
        loc = (p.get("location") or {}).get("name", "")
        offices = "; ".join(o.get("name", "") for o in (p.get("offices") or []))
        keep(job(s["company"], p["title"], p.get("absolute_url"), f"{loc}; {offices}".strip("; "),
                 (p.get("first_published") or p.get("updated_at") or "")[:10] or None, text_of(p.get("content")),
                 "greenhouse"), out, stats)


def read_lever(s, out, stats):
    posts = http(f"https://api.lever.co/v0/postings/{s['board']}?mode=json")
    stats["read"] += len(posts)
    for p in posts:
        if not title_ok(p.get("text")):
            continue
        cat = p.get("categories") or {}
        loc = "; ".join([cat.get("location") or ""] + list(cat.get("allLocations") or []))
        sal = p.get("salaryRange") or {}
        pay = f"${sal['min']:,} - ${sal['max']:,}" if sal.get("min") and sal.get("max") else ""
        text = f"{pay} {p.get('descriptionPlain') or ''} {p.get('additionalPlain') or ''}"
        posted = dt.datetime.fromtimestamp(p["createdAt"] / 1000, dt.timezone.utc).date().isoformat() if p.get("createdAt") else None
        keep(job(s["company"], p["text"], p.get("hostedUrl"), loc, posted, text, "lever",
                 (p.get("workplaceType") or "") == "remote"), out, stats)


def read_ashby(s, out, stats):
    data = http(f"https://api.ashbyhq.com/posting-api/job-board/{s['board']}?includeCompensation=true")
    posts = data.get("jobs") or []
    stats["read"] += len(posts)
    for p in posts:
        if not title_ok(p.get("title")):
            continue
        comp = (p.get("compensation") or {}).get("compensationTierSummary") or ""
        locs = [p.get("location") or ""] + [x.get("location", "") for x in (p.get("secondaryLocations") or [])]
        keep(job(s["company"], p["title"], p.get("jobUrl"), "; ".join(x for x in locs if x),
                 (p.get("publishedAt") or "")[:10] or None, f"{comp} {p.get('descriptionPlain') or ''}", "ashby",
                 bool(p.get("isRemote"))), out, stats)


def read_breezy(s, out, stats):
    posts = http(f"https://{s['board']}.breezy.hr/json")
    stats["read"] += len(posts)
    for p in posts:
        if not title_ok(p.get("name")):
            continue
        loc = p.get("location") or {}
        locname = loc.get("name") or ", ".join(x for x in (loc.get("city"), (loc.get("state") or {}).get("name")) if x)
        keep(job(s["company"], p["name"], p.get("url"), locname, (p.get("published_date") or "")[:10] or None,
                 str(p.get("salary") or ""), "breezy", bool(loc.get("is_remote"))), out, stats)


READERS = {"workday": read_workday, "eightfold": read_eightfold, "amazon": read_amazon, "greenhouse": read_greenhouse,
           "lever": read_lever, "ashby": read_ashby, "breezy": read_breezy}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="job-scan/live-jobs.json")
    ap.add_argument("--only", help="run just the sources whose company name contains this text")
    args = ap.parse_args()

    jobs, rows = [], []
    for s in SOURCES:
        if args.only and args.only.lower() not in s["company"].lower():
            continue
        stats = {"company": s["company"], "ats": s["ats"], "status": "ok", "read": 0, "kept": 0}
        before = len(jobs)
        try:
            READERS[s["ats"]](s, jobs, stats)
            if stats["read"] == 0:
                stats["status"] = "empty"
        except Exception as e:  # one broken source must not stop the others
            stats["status"] = "error"
            stats["error"] = str(e)[:200]
            del jobs[before:]
            stats["kept"] = 0
        rows.append(stats)
        print(f"{stats['status']:5}  {stats['company']}: read {stats['read']}, kept {stats['kept']}"
              + (f"  ({stats.get('error')})" if stats.get("error") else ""), flush=True)

    unique, seen = [], set()
    for j in jobs:
        if j.get("url") and j["url"] not in seen:
            seen.add(j["url"])
            unique.append(j)
    unique.sort(key=lambda j: (j["company"].lower(), j["title"].lower()))

    result = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payFloor": PAY_FLOOR,
        "jobs": unique,
        "sources": rows,
        "manualCheck": [{"company": c, "careersUrl": u} for c, u in MANUAL],
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")
    ok = sum(r["status"] == "ok" for r in rows)
    print(f"\n{len(unique)} jobs kept from {ok} of {len(rows)} sources -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
