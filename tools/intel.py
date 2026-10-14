#!/usr/bin/env python3
"""MECSR Intel - static site builder and run helpers (Python 3.8+, standard library only).

The site is a pure build artefact of data/daily/*.json. Every page is regenerated on each
build, so a day's JSON is the only thing a run has to write.

Commands
  build      [--repo DIR]                      render every page from data/
  validate   FILE.json [FILE.json ...]         schema + privacy check of daily files (exit 1 on error)
  last       [--today YYYY-MM-DD]              last published day and today's coverage window
  seen       WORD [WORD ...] [--days N]        earlier findings that mention all the words (dedupe)
  match      NAME [--country C] --index FILE   fuzzy match a property against the directory index
  week       [YYYY-MM-DD]                      ISO week id and its Monday-Sunday dates
  tracker    --xlsx FILE                       names already curated in tracker sheets 10/11/12 (needs openpyxl)
  prospects  --src DIR --out DIR --repo DIR    INTERNAL ONLY: cumulative prospects page + CSV outside the repo
"""
import argparse, csv, datetime as dt, difflib, glob, html, io, json, os, re, sys
from collections import Counter, OrderedDict, defaultdict

SCHEMA = "mecsr-intel/1"
SITE_TITLE = "MECSR Intel"
SITE_TAG = "Retail, CX & AI intelligence for MECSR and MECSC"
FLAT_PLAN_URL = "https://orient-alt.github.io/mecsr-directory-2027/"

STREAMS = OrderedDict([
    ("dest",    {"label": "Shopping destinations & pipeline", "short": "Destinations", "icon": "🏬"}),
    ("member",  {"label": "Member company news",              "short": "Members",      "icon": "🏢"}),
    ("cx",      {"label": "Customer experience & service",    "short": "CX",           "icon": "📞"}),
    ("ai",      {"label": "AI & retail technology",           "short": "AI & tech",    "icon": "🤖"}),
    ("library", {"label": "Reports, PDFs & manuals",          "short": "Library",      "icon": "📚"}),
])
TYPES = {"new": "New property", "pipeline": "Pipeline", "expansion": "Expansion", "status": "Status update",
         "closure": "Closure", "market": "Market data", "financial": "Financial", "leadership": "Leadership",
         "deal": "Deal / JV", "award": "Award", "policy": "Policy", "event": "Event", "launch": "Launch",
         "entry": "Market entry", "report": "Report", "manual": "Manual / guide", "cx": "CX", "ai": "AI / tech",
         "opening": "Opening", "tenant": "Tenant news", "": ""}
DOC_TYPES = OrderedDict([
    ("market-report", "Market report"), ("annual-report", "Annual report"), ("investor", "Investor presentation"),
    ("filing", "Exchange filing"), ("manual", "Manual / fit-out guide"), ("guideline", "Design / regulatory guideline"),
    ("policy", "Policy / regulation"), ("cx-standard", "CX standard / award criteria"), ("research", "Research / white paper"),
    ("brochure", "Brochure / leasing pack"), ("other", "Other document")])
SHEETS = OrderedDict([("10", "New properties & pipeline"), ("11", "Updates to listed properties"), ("12", "Article ideas")])
ACTIONS_10 = ["Add now", "Add to pipeline", "Check first", "Watch", "Out of scope"]
PRIORITIES_11 = ["High", "Medium", "Low"]
TIER_D = ["mecsr.org", "getoccupi.com", "rentechdigital.com", "fastbase.com", "wheree.com", "bizapedia.com",
          "evendo.com", "wanderlog.com", "zoominfo.com", "leadiq.com", "apollo.io", "lusha.com", "rocketreach.co",
          "signalhire.com", "kompass.com", "aeroleads.com", "datanyze.com"]
FORBIDDEN_KEYS = {"prospect", "prospects", "membership_status", "membership", "crm", "lapsed", "contact_email",
                  "contact_phone", "plan", "renewal", "internal"}
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_RX = re.compile(r"(?<![\w/])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{3}[\s.-]?\d{3,4}(?![\w/])")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)

def parse_iso(s):
    """'2026-10-12' -> date; '2026-10' -> date(2026,10,1); else None."""
    if not s or not isinstance(s, str):
        return None
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", s.strip())
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None

def fmt_date(s, long=False):
    d = parse_iso(s)
    if not d:
        return s or ""
    if isinstance(s, str) and len(s.strip()) == 7:
        return f"{MONTHS[d.month-1]} {d.year}"
    if long:
        return d.strftime("%A ") + f"{d.day} {d.strftime('%B')} {d.year}"
    return f"{d.day} {MONTHS[d.month-1]} {d.year}"

def fmt_range(a, b):
    if a.year == b.year and a.month == b.month:
        return f"{a.day}–{b.day} {MONTHS[b.month-1]} {b.year}"
    if a.year == b.year:
        return f"{a.day} {MONTHS[a.month-1]} – {b.day} {MONTHS[b.month-1]} {b.year}"
    return f"{a.day} {MONTHS[a.month-1]} {a.year} – {b.day} {MONTHS[b.month-1]} {b.year}"

def iso_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"

def week_dates(week_id):
    y, w = int(week_id[:4]), int(week_id[6:])
    mon = dt.date.fromisocalendar(y, w, 1)
    return mon, mon + dt.timedelta(days=6)

def norm_name(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9؀-ۿ ]+", " ", s)
    core = re.sub(r"\b(the|mall|malls|avm|shopping|centre|center|al|el|community|retail|district|project|plaza|"
                  r"souq|souk|city|park|phase|new)\b", " ", s)
    core = re.sub(r"\s+", " ", core).strip()
    return core or re.sub(r"\s+", " ", s).strip()

def domain(u):
    m = re.match(r"https?://([^/]+)", u or "")
    if not m:
        return ""
    h = m.group(1).lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h

# ----------------------------------------------------------------------------- data loading
class Repo:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.days = []
        for p in sorted(glob.glob(os.path.join(self.root, "data", "daily", "*.json"))):
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
            d["_file"] = os.path.relpath(p, self.root)
            self.days.append(d)
        self.days.sort(key=lambda d: d["date"])
        for d in self.days:
            for i, f in enumerate(d.get("findings", [])):
                f.setdefault("id", f"{d['date']}-{i+1:02d}")
                f["_date"] = d["date"]
                f["_age"] = age_of(f, d)

    def weeks(self):
        w = OrderedDict()
        for d in self.days:
            w.setdefault(iso_week(parse_iso(d["date"])), []).append(d)
        return w

def age_of(f, day):
    if f.get("age") in ("window", "recent", "background", "unverified"):
        return f["age"]
    ad = parse_iso(f.get("article_date"))
    if not ad:
        return "unverified"
    rd = parse_iso(day["date"])
    cov = day.get("coverage") or {}
    cf, ct = parse_iso(cov.get("from")), parse_iso(cov.get("to"))
    month_only = isinstance(f.get("article_date"), str) and len(f["article_date"]) == 7
    if cf and ct and not month_only and cf <= ad <= rd:
        return "window"
    if not cf and not month_only and 0 <= (rd - ad).days <= 3:
        return "window"
    return "recent" if (rd - ad).days <= 90 else "background"

# ----------------------------------------------------------------------------- validation
def walk_strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_strings(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o

def walk_keys(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield f"{path}.{k}", k
            yield from walk_keys(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_keys(v, f"{path}[{i}]")

def validate_day(d, name="?"):
    errs, warns = [], []
    for k in ("date", "findings"):
        if k not in d:
            errs.append(f"{name}: missing '{k}'")
    if not parse_iso(d.get("date", "")):
        errs.append(f"{name}: bad date {d.get('date')!r}")
    if d.get("status") not in ("full", "quiet", None):
        errs.append(f"{name}: status must be 'full' or 'quiet'")
    seen_ids = set()
    for i, f in enumerate(d.get("findings", [])):
        where = f"{name} finding[{i}] {f.get('title','')[:50]!r}"
        if f.get("stream") not in STREAMS:
            errs.append(f"{where}: stream must be one of {list(STREAMS)}")
        if not f.get("title"):
            errs.append(f"{where}: missing title")
        if not f.get("summary") and not d.get("legacy"):
            warns.append(f"{where}: missing summary")
        if f.get("id") in seen_ids:
            errs.append(f"{where}: duplicate id {f.get('id')}")
        seen_ids.add(f.get("id"))
        srcs = f.get("sources") or []
        if not srcs and not d.get("legacy"):
            errs.append(f"{where}: needs at least one source")
        for s in srcs:
            u = s.get("url", "")
            if not u.startswith("http"):
                errs.append(f"{where}: source without http url")
            if any(domain(u) == t or domain(u).endswith("." + t) for t in TIER_D):
                errs.append(f"{where}: Tier D (forbidden) source {domain(u)}")
            if not d.get("legacy") and not (s.get("outlet") or s.get("label")):
                errs.append(f"{where}: source needs an outlet name")
        ad = f.get("article_date")
        if ad and not parse_iso(ad):
            errs.append(f"{where}: article_date must be YYYY-MM-DD or YYYY-MM")
        if not ad and not d.get("legacy") and f.get("stream") != "library":
            warns.append(f"{where}: no article_date - shown as 'date unverified'")
        dirx = f.get("directory")
        if dirx:
            if str(dirx.get("sheet")) not in SHEETS:
                errs.append(f"{where}: directory.sheet must be 10, 11 or 12")
            if str(dirx.get("sheet")) == "10" and dirx.get("action") not in ACTIONS_10:
                errs.append(f"{where}: sheet-10 action must be one of {ACTIONS_10}")
            if str(dirx.get("sheet")) == "11" and dirx.get("priority") not in PRIORITIES_11:
                errs.append(f"{where}: sheet-11 priority must be one of {PRIORITIES_11}")
    for i, doc in enumerate(d.get("library", [])):
        if not str(doc.get("url", "")).startswith("http"):
            errs.append(f"{name} library[{i}]: needs an http url")
        if doc.get("doc_type") and doc["doc_type"] not in DOC_TYPES:
            warns.append(f"{name} library[{i}]: unknown doc_type {doc.get('doc_type')!r}")
    for path, s in walk_strings(d):
        if path.endswith(".url") or path.endswith("_url"):
            continue
        if EMAIL_RX.search(s):
            errs.append(f"{name}{path}: e-mail address in public data ({EMAIL_RX.search(s).group(0)}) - remove it")
        if PHONE_RX.search(s):
            errs.append(f"{name}{path}: phone number in public data ({PHONE_RX.search(s).group(0)}) - remove it")
    for path, k in walk_keys(d):
        if k.lower() in FORBIDDEN_KEYS:
            errs.append(f"{name}{path}: key '{k}' is internal-only and must not be in the public repo")
    return errs, warns

# ----------------------------------------------------------------------------- html helpers
def nav(prefix, active, latest_week):
    items = [("index.html", "Today", "today"), (f"weekly/{latest_week}.html", "This week", "week"),
             ("archive.html", "Archive", "archive"), ("library.html", "Library", "library"),
             ("pipeline.html", "Directory feed", "pipeline"), ("method.html", "Method", "method")]
    return "".join(f'<a href="{prefix}{h}" class="{"on" if k == active else ""}">{esc(t)}</a>' for h, t, k in items)

def page(prefix, active, latest_week, title, body, desc=""):
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc or SITE_TAG)}">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{prefix}assets/site.css">
<script src="{prefix}assets/site.js"></script>
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="{prefix}index.html"><b>MECSR <span>Intel</span></b><small>{esc(SITE_TAG)}</small></a>
  <nav class="nav" aria-label="Sections">{nav(prefix, active, latest_week)}</nav>
  <button class="theme-toggle" type="button" title="Switch light / dark">◐ Theme</button>
</div></header>
<main class="wrap">
{body}
<footer class="foot">
  Public news only, researched to the MECSR Directory Source Policy v1.0: every item is dated from the article itself and
  linked to its source. Membership prospects and CRM data are kept off this site.
  <a href="{prefix}method.html">How this is researched</a> · <a href="{FLAT_PLAN_URL}">2027 Directory flat plan</a> ·
  built {esc(built)}
</footer>
</main>
</body>
</html>
"""

def chip(text, cls=""):
    return f'<span class="chip {cls}">{text}</span>' if text else ""

def stream_chip(k):
    s = STREAMS[k]
    return f'<span class="chip"><span class="dot d-{k}"></span>{esc(s["short"])}</span>'

def age_pill(f):
    a = f.get("_age") or "unverified"
    ad = f.get("article_date")
    if a == "window":
        return f'<span class="age win">{esc(fmt_date(ad))} · in window</span>'
    if a == "recent":
        return f'<span class="age rec">{esc(fmt_date(ad))} · recent</span>'
    if a == "background":
        return f'<span class="age old">{esc(fmt_date(ad))} · background</span>'
    return '<span class="age rec">date unverified</span>'

def source_links(srcs):
    out = []
    for s in srcs or []:
        u = s.get("url", "")
        label = s.get("label") or " · ".join(x for x in [s.get("outlet", ""), fmt_date(s.get("date")) if s.get("date") else
                                                          ("date unverified" if s.get("date_unverified") else "")] if x)
        pdf = '<span class="pdf">PDF</span>' if (s.get("kind") == "pdf" or u.lower().split("?")[0].endswith(".pdf")) else ""
        tier = f'<span class="tier" title="Source tier (MECSR Source Policy)">{esc(s["tier"])}</span>' if s.get("tier") else ""
        out.append(f'<span>{pdf}<a href="{esc(u)}" target="_blank" rel="noopener">{esc(label or domain(u))} ↗</a>{tier}</span>')
    return f'<div class="srcs">{"".join(out)}</div>' if out else ""

def dir_chip(f):
    dx = f.get("directory")
    if not dx:
        return ""
    sh = str(dx.get("sheet"))
    what = dx.get("action") if sh == "10" else (f"Update listing · {dx.get('priority')}" if sh == "11" else "Article idea")
    return chip(f"→ 2027 Directory: {esc(what)}", "dir")

def card(f, anchor=True):
    k = f.get("stream", "dest")
    text = " ".join(str(f.get(x, "")) for x in ("title", "summary", "entity", "company", "country", "city")).lower()
    chips = [stream_chip(k)]
    if f.get("country"):
        chips.append(chip(esc(f["country"] + (f" · {f['city']}" if f.get("city") else ""))))
    if f.get("type") and TYPES.get(f["type"], f["type"]):
        chips.append(chip(esc(TYPES.get(f["type"], f["type"]))))
    chips.append(age_pill(f))
    if f.get("member"):
        chips.append(chip("MECSR member", "member"))
    if f.get("confidence"):
        chips.append(chip(f"Confidence: {esc(f['confidence'])}"))
    chips.append(dir_chip(f))
    why = f'<p class="why"><b>Why it matters:</b> {esc(f["why"])}</p>' if f.get("why") else ""
    summ = "".join(f"<p>{esc(p)}</p>" for p in re.split(r"\n{2,}", f.get("summary", "")) if p.strip())
    aid = f' id="{esc(f["id"])}"' if anchor and f.get("id") else ""
    return (f'<article class="card s-{k}"{aid} data-stream="{k}" data-text="{esc(text)}">'
            f'<h3>{esc(f.get("title", ""))}</h3><div class="chips">{"".join(c for c in chips if c)}</div>'
            f'{summ}{why}{source_links(f.get("sources"))}</article>')

def kpi(label, value, sub="", dot=""):
    d = f'<span class="dot d-{dot}"></span>' if dot else ""
    return (f'<div class="kpi"><div class="label">{d}{esc(label)}</div><div class="value">{esc(value)}</div>'
            f'{f"<div class=sub>{esc(sub)}</div>" if sub else ""}</div>')

def filter_bar(streams_present, placeholder="Filter these findings…"):
    btns = ['<button class="chipbtn" type="button" data-filter="all" aria-pressed="true">All</button>']
    for k in STREAMS:
        if k in streams_present:
            btns.append(f'<button class="chipbtn" type="button" data-filter="{k}" aria-pressed="false">'
                        f'<span class="dot d-{k}"></span>{esc(STREAMS[k]["short"])}</button>')
    return f'<div class="tools">{"".join(btns)}<input class="search" type="search" placeholder="{esc(placeholder)}" aria-label="Filter"></div>'

# ----------------------------------------------------------------------------- directory feed
# Exact headers of tracker sheets 10, 11 and 12 (MECSR_2027_Directory_Content_Tracker.xlsx, checked
# 14 Oct 2026). The CSV files use them in this order so rows paste straight under the tracker's own;
# the team's columns (SN, LISTING PAGES, VERIFIED, ASSIGNED TO, NOTES, sheet 11/12 STATUS, WRITER,
# SPONSOR / MEMBER FIT) are left blank on purpose.
TRACKER_COLS = {
    "10": ["SN", "ACTION", "PROPERTY", "CITY", "COUNTRY", "DEVELOPER / OWNER", "STATUS", "OPENING", "SIZE (AS REPORTED)",
           "WHAT THE INTEL SAYS", "DIRECTORY CHECK", "LISTING PAGES", "FIRST SEEN", "LAST SEEN", "REPORTS", "SOURCES",
           "LINK", "NEXT STEP", "VERIFIED", "ASSIGNED TO", "NOTES"],
    "11": ["SN", "PRIORITY", "PROPERTY (AS LISTED)", "COUNTRY", "PAGE", "FIELD", "DIRECTORY SAYS (v13 BOOK)", "INTEL SAYS",
           "CHANGE TO MAKE", "FIRST SEEN", "LAST SEEN", "SOURCES", "LINK", "STATUS", "ASSIGNED TO", "NOTES"],
    "12": ["SN", "WORKING HEADLINE", "ANGLE", "WHERE IT FITS", "MARKETS", "KEY FACTS FROM THE INTEL", "SPONSOR / MEMBER FIT",
           "CAUTION", "SOURCES", "MAIN LINK", "MORE LINKS", "STATUS", "WRITER", "NOTES"],
}
TRACKER_ALIAS = {"DIRECTORY SAYS (v13 BOOK)": "DIRECTORY SAYS"}
TEAM_COLS = {"10": {"SN", "LISTING PAGES", "VERIFIED", "ASSIGNED TO", "NOTES"},
             "11": {"SN", "STATUS", "ASSIGNED TO", "NOTES"},
             "12": {"SN", "SPONSOR / MEMBER FIT", "STATUS", "WRITER", "NOTES"}}

def tracker_value(sheet, row, col):
    return "" if col in TEAM_COLS[sheet] else row.get(TRACKER_ALIAS.get(col, col), "")

def clip(text, n=400):
    """Shorten a summary for a tracker cell at a sentence or word boundary."""
    text = (text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n]
    stop = cut.rfind(". ")
    if stop >= n // 2:
        return cut[:stop + 1]
    return cut[:cut.rfind(" ")].rstrip(",;:") + " …"

def src_label(s):
    return s.get("label") or " · ".join(x for x in [s.get("outlet", ""), fmt_date(s.get("date")) if s.get("date") else ""] if x)

def build_feed(repo):
    rows = OrderedDict()
    for d in repo.days:
        for f in d.get("findings", []):
            dx = f.get("directory")
            if not dx:
                continue
            sh = str(dx.get("sheet"))
            name = dx.get("property") or dx.get("listed_as") or dx.get("headline") or f.get("entity") or f.get("title")
            key = (sh, norm_name(name), (f.get("country") or "").lower())
            r = rows.get(key)
            srcs = [src_label(s) for s in f.get("sources", [])]
            links = [s.get("url") for s in f.get("sources", []) if s.get("url")]
            if not r:
                r = rows[key] = {"sheet": sh, "first": d["date"], "last": d["date"], "days": set(), "sources": [],
                                 "links": [], "f": f, "dx": dx, "name": name}
            r["last"] = max(r["last"], d["date"]); r["first"] = min(r["first"], d["date"])
            r["days"].add(d["date"])
            merged = {**r["dx"], **{k: v for k, v in dx.items() if v}}
            for k in ("change", "next", "intel"):
                old, new = r["dx"].get(k), dx.get(k)
                if old and new and old != new and new not in old:
                    merged[k] = f"{new} | earlier: {old}"
            r["f"], r["dx"] = f, merged
            r["sources"] += [s for s in srcs if s not in r["sources"]]
            r["links"] += [l for l in links if l not in r["links"]]
    out = {"10": [], "11": [], "12": []}
    for r in rows.values():
        f, dx, sh = r["f"], r["dx"], r["sheet"]
        common = {"FIRST SEEN": r["first"], "LAST SEEN": r["last"], "REPORTS": len(r["days"]),
                  "SOURCES": "; ".join(r["sources"][:6])}
        if sh == "10":
            out["10"].append({"ACTION": dx.get("action", ""), "PROPERTY": r["name"], "CITY": f.get("city", ""),
                              "COUNTRY": f.get("country", ""), "DEVELOPER / OWNER": dx.get("developer", ""),
                              "STATUS": dx.get("status", ""), "OPENING": dx.get("opening", ""),
                              "SIZE (AS REPORTED)": dx.get("size", ""), "WHAT THE INTEL SAYS": dx.get("intel") or clip(f.get("summary", "")),
                              "DIRECTORY CHECK": dx.get("check", ""), **common, "LINK": (r["links"] or [""])[0],
                              "NEXT STEP": dx.get("next", ""), "_id": f.get("id"), "_date": f.get("_date")})
        elif sh == "11":
            out["11"].append({"PRIORITY": dx.get("priority", ""), "PROPERTY (AS LISTED)": dx.get("listed_as") or r["name"],
                              "COUNTRY": f.get("country", ""), "PAGE": dx.get("page", ""), "FIELD": dx.get("field", ""),
                              "DIRECTORY SAYS": dx.get("directory_says", ""), "INTEL SAYS": dx.get("intel") or clip(f.get("summary", "")),
                              "CHANGE TO MAKE": dx.get("change", ""), **common, "LINK": (r["links"] or [""])[0],
                              "_id": f.get("id"), "_date": f.get("_date")})
        else:
            out["12"].append({"WORKING HEADLINE": dx.get("headline") or r["name"], "ANGLE": dx.get("angle", ""),
                              "WHERE IT FITS": dx.get("fits", ""), "MARKETS": dx.get("markets") or f.get("country", ""),
                              "KEY FACTS FROM THE INTEL": dx.get("facts") or clip(f.get("summary", "")),
                              "CAUTION": dx.get("caution", ""), "FIRST SEEN": r["first"], "LAST SEEN": r["last"],
                              "SOURCES": common["SOURCES"], "MAIN LINK": (r["links"] or [""])[0],
                              "MORE LINKS": " ".join(r["links"][1:4]), "_id": f.get("id"), "_date": f.get("_date")})
    order10 = {a: i for i, a in enumerate(ACTIONS_10)}
    out["10"].sort(key=lambda x: (order10.get(x["ACTION"], 9), x["COUNTRY"], x["PROPERTY"]))
    out["11"].sort(key=lambda x: (PRIORITIES_11.index(x["PRIORITY"]) if x["PRIORITY"] in PRIORITIES_11 else 9, x["COUNTRY"]))
    out["12"].sort(key=lambda x: x["LAST SEEN"], reverse=True)
    return out

def write_feed(repo, feed):
    data = os.path.join(repo.root, "data")
    def json_row(k, r):
        row = {c: tracker_value(k, r, c) for c in TRACKER_COLS[k] if c not in TEAM_COLS[k]}
        row.update({"FIRST SEEN": r.get("FIRST SEEN", ""), "LAST SEEN": r.get("LAST SEEN", ""), "REPORTS": r.get("REPORTS", ""),
                    "DAY PAGE": f"daily/{r['_date']}.html#{r['_id']}" if r.get("_id") and r.get("_date") else ""})
        return row
    with open(os.path.join(data, "directory_feed.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "built": dt.date.today().isoformat(),
                   "note": ("Rows for the MECSR 2027 Directory tracker, sheets 10/11/12. The CSV files use the tracker's exact "
                            "columns in order (team columns left blank) so rows paste straight in; this JSON adds first and "
                            "last seen, report count and the day page of the latest finding."),
                   "sheets": {k: [json_row(k, r) for r in v] for k, v in feed.items()}},
                  fh, ensure_ascii=False, indent=1)
    for k, rows in feed.items():
        with open(os.path.join(data, f"directory_feed_sheet{k}.csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(TRACKER_COLS[k])
            for r in rows:
                w.writerow([tracker_value(k, r, c) for c in TRACKER_COLS[k]])

# ----------------------------------------------------------------------------- library
def build_library(repo):
    docs, seen = [], set()
    for d in repo.days:
        for doc in d.get("library", []):
            u = doc.get("url", "")
            if u in seen:
                continue
            seen.add(u)
            docs.append({**doc, "_date": d["date"]})
        for f in d.get("findings", []):
            for s in f.get("sources", []):
                u = s.get("url", "")
                if u.lower().split("?")[0].endswith(".pdf") and u not in seen:
                    seen.add(u)
                    docs.append({"title": f.get("title"), "publisher": s.get("outlet") or domain(u), "doc_type": "other",
                                 "country": f.get("country", ""), "date": s.get("date") or f.get("article_date") or "",
                                 "url": u, "note": "PDF cited in an intel finding", "_date": d["date"],
                                 "_from": f"daily/{d['date']}.html#{f.get('id')}"})
    docs.sort(key=lambda x: x.get("_date", ""), reverse=True)
    return docs

def doc_row(doc, prefix):
    t = doc.get("doc_type") or "other"
    text = " ".join(str(doc.get(k, "")) for k in ("title", "publisher", "country", "note", "use_for")).lower()
    pages = f" · {doc['pages']} pp" if doc.get("pages") else ""
    is_pdf = str(doc.get("url", "")).lower().split("?")[0].endswith(".pdf") or doc.get("format") == "pdf"
    badge = '<span class="pdf">PDF</span>' if is_pdf else '<span class="pdf web">WEB</span>'
    from_link = f' · <a href="{prefix}{esc(doc["_from"])}">finding</a>' if doc.get("_from") else ""
    return (f'<li data-stream="{esc(t)}" data-text="{esc(text)}"><div class="row"><span class="when">{esc(fmt_date(doc.get("date", "")))}</span>'
            f'<span class="chip"><span class="dot d-library"></span>{esc(DOC_TYPES.get(t, t))}</span>'
            f'{chip(esc(doc.get("country", "")))}</div>'
            f'<div>{badge}<a href="{esc(doc.get("url"))}" target="_blank" rel="noopener"><b>{esc(doc.get("title"))}</b> ↗</a></div>'
            f'<div class="note">{esc(doc.get("publisher", ""))}{esc(pages)}{". " + esc(doc.get("note")) if doc.get("note") else ""}'
            f'{" · Use for: " + esc(doc.get("use_for")) if doc.get("use_for") else ""}{from_link}</div></li>')

# ----------------------------------------------------------------------------- pages
def day_page(repo, d, prefix, latest_week, is_index=False):
    fs = d.get("findings", [])
    by = defaultdict(list)
    for f in fs:
        by[f.get("stream", "dest")].append(f)
    i = repo.days.index(d)
    prev_d = repo.days[i - 1]["date"] if i > 0 else None
    next_d = repo.days[i + 1]["date"] if i + 1 < len(repo.days) else None
    dprefix = prefix if is_index else ""
    link_day = (lambda x: f"{prefix}daily/{x}.html") if is_index else (lambda x: f"{x}.html")
    cov = d.get("coverage") or {}
    in_window = sum(1 for f in fs if f.get("_age") == "window")
    countries = sorted({f.get("country") for f in fs if f.get("country") and f.get("country") not in ("Global", "GCC", "MENA")})
    nsrc = len({s.get("url") for f in fs for s in f.get("sources", [])})
    ndir = sum(1 for f in fs if f.get("directory"))
    wk = iso_week(parse_iso(d["date"]))
    prev_a = f'<a href="{link_day(prev_d)}">← {esc(fmt_date(prev_d))}</a>' if prev_d else "<span>← earlier</span>"
    next_a = f'<a href="{link_day(next_d)}">{esc(fmt_date(next_d))} →</a>' if next_d else "<span>later →</span>"
    eyebrow = ("Today's edition" if is_index else "Daily edition") + (" · migrated from the earlier reports" if d.get("legacy") else "")
    runs = f" · searches run: {d['searches_run']}" if d.get("searches_run") else ""
    h = [f'<div class="head"><div class="eyebrow">{esc(eyebrow)}</div>'
         f'<h1>Daily Intelligence · {esc(fmt_date(d["date"], long=True))}</h1>'
         f'<div class="meta">Covers <b>{esc(cov.get("label") or "not recorded")}</b> · {len(fs)} findings · {nsrc} sources{esc(runs)}</div>'
         f'<div class="pager">{prev_a}<a href="{prefix}weekly/{wk}.html">Week {esc(wk[-2:])} summary</a>{next_a}</div></div>']
    if d.get("status") == "quiet":
        h.append('<div class="banner"><b>Quiet day.</b> Fewer than three verified items were published in the coverage window. '
                 'Below: what did clear the bar, recent background that is new to this site, and the watch list.</div>')
    tiles = [kpi(STREAMS[k]["short"], len(by.get(k, [])) + (len(d.get("library", [])) if k == "library" else 0),
                 "documents" if k == "library" else "", dot=k) for k in STREAMS]
    tiles += [kpi("In coverage window", in_window, f"of {len(fs)}"), kpi("Directory actions", ndir, "for the 2027 Directory", dot="dir"),
              kpi("Countries", len(countries), ", ".join(countries[:4]) + ("…" if len(countries) > 4 else ""))]
    h.append(f'<section class="kpis" aria-label="Today in numbers">{"".join(tiles)}</section>')
    if d.get("brief"):
        h.append('<section class="panel brief"><h2>In brief</h2><ul>' + "".join(f"<li>{esc(b)}</li>" for b in d["brief"]) + "</ul></section>")
    if fs:
        h.append(filter_bar(by.keys()))
    for k, s in STREAMS.items():
        items = by.get(k, [])
        if not items:
            continue
        items.sort(key=lambda f: ({"window": 0, "recent": 1, "unverified": 2, "background": 3}.get(f.get("_age"), 2), f.get("country", "")))
        h.append(f'<section class="stream" data-group="{k}"><header><span class="bar d-{k}"></span><span class="ico">{s["icon"]}</span>'
                 f'<h2>{esc(s["label"])}</h2><span class="count">{len(items)}</span></header><div class="cards">'
                 + "".join(card(f) for f in items) + "</div></section>")
    dirs = [f for f in fs if f.get("directory")]
    if dirs:
        rows = []
        for f in dirs:
            dx = f["directory"]; sh = str(dx.get("sheet"))
            what = dx.get("action") if sh == "10" else (f"Update · {dx.get('priority')}" if sh == "11" else "Article idea")
            detail = dx.get("change") or dx.get("next") or dx.get("angle") or ""
            name = dx.get("property") or dx.get("listed_as") or dx.get("headline") or f.get("entity") or f["title"]
            rows.append(f'<tr><td>{esc(sh)}</td><td>{esc(what)}</td><td><a href="#{esc(f["id"])}">{esc(name)}</a></td>'
                        f'<td>{esc(f.get("country", ""))}</td><td>{esc(detail)}</td></tr>')
        h.append('<section class="panel"><h2>For the 2027 Directory <span class="count">' + str(len(dirs)) + '</span></h2>'
                 '<p class="note">Rows in the tracker\'s own columns are in the <a href="' + prefix + 'pipeline.html">Directory feed</a> '
                 '(sheet 10 = new properties, 11 = updates to listed properties, 12 = article ideas).</p>'
                 '<div class="tbl-wrap"><table><thead><tr><th>Sheet</th><th>Action</th><th>Property / idea</th><th>Country</th><th>Next step</th></tr></thead><tbody>'
                 + "".join(rows) + "</tbody></table></div></section>")
    vx = d.get("verification")
    if vx:
        unv = vx.get("unverifiable") or []
        h.append('<section class="panel"><h2>✅ Directory verification batch</h2>'
                 f'<p>{esc(vx.get("batch", ""))}: <b>{esc(vx.get("checked", 0))}</b> listings checked against primary sources, '
                 f'{esc(vx.get("unchanged", 0))} unchanged, {esc(vx.get("changed", 0))} changed (shown above as status findings).</p>'
                 + (f'<p class="note">No primary source found for: {esc(", ".join(unv))}.</p>' if unv else "")
                 + (f'<p class="note">{esc(vx.get("note"))}</p>' if vx.get("note") else "") + "</section>")
    if d.get("library"):
        h.append('<section class="panel"><h2>📚 Documents found today <span class="count">' + str(len(d["library"])) + '</span></h2><ul class="plain">'
                 + "".join(doc_row({**doc, "_date": d["date"]}, prefix) for doc in d["library"]) + "</ul></section>")
    if d.get("watch"):
        lis = []
        for w in d["watch"]:
            if isinstance(w, dict):
                lis.append(f'<li><b>{esc(w.get("item"))}</b>{": " + esc(w.get("note")) if w.get("note") else ""}'
                           f'{" <span class=muted>(since " + esc(fmt_date(w.get("since"))) + ")</span>" if w.get("since") else ""}</li>')
            else:
                lis.append(f"<li>{esc(w)}</li>")
        h.append('<section class="panel"><h2>👀 Watch list</h2><ul class="plain">' + "".join(lis) + "</ul></section>")
    if d.get("no_findings"):
        h.append('<section class="panel"><h2>No findings this run</h2><p class="note">' + esc(", ".join(d["no_findings"])) + "</p></section>")
    if d.get("notes"):
        h.append(f'<p class="note">Run notes: {esc(d["notes"])}</p>')
    title = f"MECSR Intel · {fmt_date(d['date'], long=True)}"
    return page(prefix, "today" if is_index else "archive", latest_week, title, "\n".join(h),
                desc=(d.get("brief") or [SITE_TAG])[0])

def week_page(repo, wid, days, latest_week):
    prefix = "../"
    mon, sun = week_dates(wid)
    fs = [f for d in days for f in d.get("findings", [])]
    by = defaultdict(list)
    for f in fs:
        by[f.get("stream", "dest")].append(f)
    weeks = list(repo.weeks().keys())
    i = weeks.index(wid)
    prev_w = weeks[i - 1] if i > 0 else None
    next_w = weeks[i + 1] if i + 1 < len(weeks) else None
    brief_day = next((d for d in reversed(days) if d.get("weekly_brief")), None)
    countries = Counter(f.get("country") for f in fs if f.get("country"))
    prev_a = f'<a href="{prev_w}.html">← Week {prev_w[-2:]}</a>' if prev_w else "<span>← earlier</span>"
    next_a = f'<a href="{next_w}.html">Week {next_w[-2:]} →</a>' if next_w else "<span>later →</span>"
    nsrc = len({s.get("url") for f in fs for s in f.get("sources", [])})
    top = ", ".join(c for c, _ in countries.most_common(5))
    h = [f'<div class="head"><div class="eyebrow">Weekly summary</div>'
         f'<h1>Week {wid[-2:]} · {esc(fmt_range(mon, sun))}</h1>'
         f'<div class="meta">{len(days)} daily editions · {len(fs)} findings · {nsrc} sources · top markets: {esc(top)}</div>'
         f'<div class="pager">{prev_a}{next_a}</div></div>']
    ndocs = sum(len(d.get("library", [])) for d in days)
    tiles = [kpi(STREAMS[k]["short"], len(by.get(k, [])) + (ndocs if k == "library" else 0), dot=k) for k in STREAMS]
    tiles.append(kpi("Directory actions", sum(1 for f in fs if f.get("directory")), dot="dir"))
    h.append(f'<section class="kpis k6">{"".join(tiles)}</section>')
    if brief_day:
        wb = brief_day["weekly_brief"]
        bl = wb if isinstance(wb, list) else wb.get("bullets", [])
        h.append('<section class="panel brief"><h2>The week in brief</h2><ul>' + "".join(f"<li>{esc(b)}</li>" for b in bl) + "</ul></section>")
    h.append(filter_bar(by.keys(), "Filter this week…"))
    for k, s in STREAMS.items():
        items = by.get(k, [])
        if not items:
            continue
        lis = []
        for f in sorted(items, key=lambda f: (f.get("country", ""), f["_date"])):
            text = " ".join(str(f.get(x, "")) for x in ("title", "summary", "entity", "country")).lower()
            lis.append(f'<li data-stream="{k}" data-text="{esc(text)}"><div class="row"><span class="when">{esc(fmt_date(f["_date"]))}</span>'
                       f'{chip(esc(f.get("country", "")))}{age_pill(f)}{dir_chip(f)}</div>'
                       f'<div><a href="../daily/{f["_date"]}.html#{esc(f["id"])}"><b>{esc(f["title"])}</b></a></div>'
                       f'{source_links(f.get("sources"))}</li>')
        h.append(f'<section class="stream" data-group="{k}"><header><span class="bar d-{k}"></span><span class="ico">{s["icon"]}</span>'
                 f'<h2>{esc(s["label"])}</h2><span class="count">{len(items)}</span></header><div class="panel"><ul class="plain">'
                 + "".join(lis) + "</ul></div></section>")
    docs = [doc for d in days for doc in d.get("library", [])]
    if docs:
        h.append('<section class="panel"><h2>📚 Documents found this week</h2><ul class="plain">'
                 + "".join(doc_row(doc, prefix) for doc in docs) + "</ul></section>")
    h.append('<section class="panel"><h2>Daily editions</h2><ul class="plain">' + "".join(
        f'<li class="row"><span class="when">{esc(fmt_date(d["date"]))}</span><a href="../daily/{d["date"]}.html">{esc(parse_iso(d["date"]).strftime("%A"))}</a>'
        f'<span class="muted">{len(d.get("findings", []))} findings{" · quiet day" if d.get("status") == "quiet" else ""}</span></li>' for d in days) + "</ul></section>")
    return page(prefix, "week" if wid == latest_week else "archive", latest_week, f"MECSR Intel · Week {wid}", "\n".join(h))

def archive_page(repo, latest_week):
    weeks = repo.weeks()
    blocks = []
    for wid in reversed(list(weeks)):
        days = weeks[wid]
        mon, sun = week_dates(wid)
        n = sum(len(d.get("findings", [])) for d in days)
        blocks.append(f'<div class="week"><h3><a href="weekly/{wid}.html">Week {wid[-2:]} · {esc(fmt_range(mon, sun))}</a></h3>'
                      f'<div class="note">{len(days)} editions · {n} findings</div><div class="days">'
                      + "".join(f'<a href="daily/{d["date"]}.html" title="{len(d.get("findings", []))} findings">{esc(parse_iso(d["date"]).strftime("%a %d"))}</a>' for d in days)
                      + "</div></div>")
    total = sum(len(d.get("findings", [])) for d in repo.days)
    body = (f'<div class="head"><div class="eyebrow">Archive</div><h1>Every edition, every source link</h1>'
            f'<div class="meta">{len(repo.days)} daily editions · {len(weeks)} weeks · {total} findings since {esc(fmt_date(repo.days[0]["date"]))}</div></div>'
            '<section class="panel"><h2>Search all findings</h2>'
            '<input id="archive-search" class="search" style="width:100%" type="search" data-src="data/search.json" '
            'placeholder="Search a mall, company, country or topic, e.g. Westfield, Primark, Riyadh, chatbot" aria-label="Search the archive">'
            '<div id="archive-results" class="results"></div></section>'
            '<section><h2 style="margin:18px 0 10px">Weekly summaries</h2><div class="weeks">' + "".join(blocks) + "</div></section>")
    return page("", "archive", latest_week, "MECSR Intel · Archive", body)

def library_page(repo, docs, latest_week):
    present = []
    for t in DOC_TYPES:
        if any((d.get("doc_type") or "other") == t for d in docs):
            present.append(t)
    btns = ['<button class="chipbtn" type="button" data-filter="all" aria-pressed="true">All</button>'] + [
        f'<button class="chipbtn" type="button" data-filter="{t}" aria-pressed="false">{esc(DOC_TYPES[t])}</button>' for t in present]
    body = ('<div class="head"><div class="eyebrow">Reference library</div><h1>Reports, PDFs and manuals</h1>'
            f'<div class="meta">{len(docs)} documents: market reports, annual reports and investor decks, exchange filings, tenant fit-out manuals, '
            'design and regulatory guidelines, CX standards. Each run adds what it finds; links go to the publisher\'s own copy.</div></div>'
            f'<div class="tools">{"".join(btns)}<input class="search" type="search" placeholder="Filter documents…" aria-label="Filter"></div>'
            '<section class="panel"><ul class="plain">' + "".join(doc_row(doc, "") for doc in docs) + "</ul>"
            + ("" if docs else '<p class="note">No documents yet.</p>') + "</section>")
    return page("", "library", latest_week, "MECSR Intel · Library", body)

def pipeline_page(repo, feed, latest_week):
    def table(sh, cols, rows):
        if not rows:
            return '<p class="note">Nothing yet.</p>'
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = []
        for r in rows:
            cells = []
            for c in cols:
                v = r.get(c, "")
                if c in ("LINK", "MAIN LINK") and v:
                    cells.append(f'<td><a href="{esc(v)}" target="_blank" rel="noopener">{esc(domain(v))} ↗</a></td>')
                elif c in ("PROPERTY", "PROPERTY (AS LISTED)", "WORKING HEADLINE") and r.get("_id"):
                    cells.append(f'<td><a href="daily/{esc(r["_date"])}.html#{esc(r["_id"])}"><b>{esc(v)}</b></a></td>')
                elif c in ("REPORTS",):
                    cells.append(f'<td class="num">{esc(v)}</td>')
                elif c in ("LAST SEEN", "FIRST SEEN"):
                    cells.append(f'<td class="nw">{esc(fmt_date(v))}</td>')
                elif c in ("ACTION", "PRIORITY", "COUNTRY", "OPENING"):
                    cells.append(f'<td class="nw">{esc(v)}</td>')
                elif c in ("NEXT STEP", "INTEL SAYS", "CHANGE TO MAKE", "ANGLE", "STATUS", "WHAT THE INTEL SAYS"):
                    cells.append(f'<td class="txt">{esc(v)}</td>')
                else:
                    cells.append(f"<td>{esc(v)}</td>")
            text = " ".join(str(v) for v in r.values()).lower()
            body.append(f'<tr data-stream="s{sh}" data-text="{esc(text)}">{"".join(cells)}</tr>')
        return f'<div class="tbl-wrap"><table class="wide"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    show = {"10": ["ACTION", "PROPERTY", "CITY", "COUNTRY", "DEVELOPER / OWNER", "STATUS", "OPENING", "SIZE (AS REPORTED)", "NEXT STEP", "LAST SEEN", "REPORTS", "LINK"],
            "11": ["PRIORITY", "PROPERTY (AS LISTED)", "COUNTRY", "FIELD", "INTEL SAYS", "CHANGE TO MAKE", "LAST SEEN", "LINK"],
            "12": ["WORKING HEADLINE", "ANGLE", "WHERE IT FITS", "MARKETS", "CAUTION", "LAST SEEN", "MAIN LINK"]}
    btns = '<button class="chipbtn" type="button" data-filter="all" aria-pressed="true">All</button>' + "".join(
        f'<button class="chipbtn" type="button" data-filter="s{k}" aria-pressed="false">Sheet {k} · {esc(v)}</button>' for k, v in SHEETS.items())
    parts = ['<div class="head"><div class="eyebrow">Directory feed</div><h1>Intel for the 2027 Directory</h1>'
             '<div class="meta">New and pipeline malls, changes to listed properties and article ideas found by the daily intel, in the same columns as the '
             f'2027 Directory Content Tracker (sheets 10, 11 and 12). The Directory working session reviews these and moves them into the tracker; '
             f'nothing here changes the directory by itself. <a href="{FLAT_PLAN_URL}">Open the flat plan ↗</a></div>'
             '<div class="pager"><a href="data/directory_feed_sheet10.csv">Sheet 10 CSV</a><a href="data/directory_feed_sheet11.csv">Sheet 11 CSV</a>'
             '<a href="data/directory_feed_sheet12.csv">Sheet 12 CSV</a><a href="data/directory_feed.json">JSON</a></div></div>',
             f'<div class="tools">{btns}<input class="search" type="search" placeholder="Filter rows…" aria-label="Filter"></div>']
    for k, label in SHEETS.items():
        parts.append(f'<section class="stream" data-group="s{k}"><header><span class="bar d-dir"></span><h2>Sheet {k} · {esc(label)}</h2>'
                     f'<span class="count">{len(feed[k])}</span></header>{table(k, show[k], feed[k])}</section>')
    return page("", "pipeline", latest_week, "MECSR Intel · Directory feed", "\n".join(parts))

def method_page(latest_week):
    body = f"""<div class="head"><div class="eyebrow">Method</div><h1>How this intelligence is researched</h1>
<div class="meta">One research run every weekday at 08:00 Dubai. Friday's run adds the weekly summary and a verification batch of directory listings.</div></div>
<section class="panel"><h2>What each run covers</h2><ul>
<li><b>🏬 Shopping destinations & pipeline</b>: new malls, mixed-use schemes, outlet centres and retail parks, expansions, openings, closures and supply data across the 24+ markets of the MECSR Directory.</li>
<li><b>🏢 Member company news</b>: projects, results, leadership, deals and awards for MECSR member organisations.</li>
<li><b>📞 Customer experience & service</b>: GCC customer-experience programmes, awards, contact-centre and service news.</li>
<li><b>🤖 AI & retail technology</b>: AI agents, voice and chat, personalisation and retail-tech launches in the region, plus a few global items that matter here.</li>
<li><b>📚 Reports, PDFs & manuals</b>: market reports, annual reports and investor presentations, exchange filings, tenant fit-out manuals, design and regulatory guidelines, CX standards.</li>
</ul></section>
<section class="panel"><h2>Sources</h2><ul>
<li><b>Tier A</b>: the operator or developer itself, exchange filings and annual reports, government and regulators, JLL / CBRE / Knight Frank / Cushman &amp; Wakefield / Colliers / Savills, named trade press (Retail ME, Arabian Business, Gulf Business, Zawya).</li>
<li><b>Tier B</b>: established regional and international media with named editorial teams; needs a second source for figures.</li>
<li><b>Tier C</b>: discovery only (portals, social posts, aggregators): used to find a story, never cited for it.</li>
<li><b>Tier D</b>: never used: lead-database and scraper sites, unattributed or machine-generated pages, and MECSR's own directory (no circular citation).</li>
</ul></section>
<section class="panel"><h2>Dates</h2><p>Every item is dated from the article itself: the page's published-time metadata, its byline or a dated URL, never from the search snippet.
Items are labelled <span class="age win">in window</span> (published in the run's coverage window), <span class="age rec">recent</span> (up to 90 days)
or <span class="age old">background</span> (older). Monday covers Friday to Sunday; Tuesday to Friday cover the previous day; a missed day is picked up by the next run.</p></section>
<section class="panel"><h2>Quiet days</h2><p>A day with fewer than three verified items still gets a page, marked as a quiet day, with whatever cleared the bar and the watch list.
Nothing unverified is added to make a page look fuller.</p></section>
<section class="panel"><h2>What is not on this site</h2><p>No personal contact data, no e-mail addresses or phone numbers, and no membership-prospect or CRM information.
Those stay in MECSR's internal files.</p></section>"""
    return page("", "method", latest_week, "MECSR Intel · Method", body)

def search_index(repo):
    out = []
    for d in repo.days:
        for f in d.get("findings", []):
            s0 = (f.get("sources") or [{}])[0]
            out.append({"d": d["date"], "k": f.get("stream"), "n": STREAMS.get(f.get("stream"), {}).get("short", ""),
                        "c": f.get("country", ""), "t": f.get("title", ""), "s": (f.get("summary") or "")[:220],
                        "e": f.get("entity", ""), "o": src_label(s0) if s0 else "", "u": s0.get("url", ""),
                        "p": f"daily/{d['date']}.html#{f.get('id')}"})
    out.sort(key=lambda r: r["d"], reverse=True)
    return out

def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

def cmd_build(args):
    repo = Repo(args.repo)
    if not repo.days:
        sys.exit("No data/daily/*.json files - nothing to build.")
    errors = []
    for d in repo.days:
        e, _ = validate_day(d, d["_file"])
        errors += e
    if errors and not args.force:
        print("\n".join(errors[:60]))
        sys.exit(f"build refused: {len(errors)} validation error(s). Fix them (or --force for a draft).")
    weeks = repo.weeks()
    latest_week = list(weeks)[-1]
    R = repo.root
    for d in repo.days:
        write(os.path.join(R, "daily", f"{d['date']}.html"), day_page(repo, d, "../", latest_week))
    write(os.path.join(R, "index.html"), day_page(repo, repo.days[-1], "", latest_week, is_index=True))
    for wid, days in weeks.items():
        write(os.path.join(R, "weekly", f"{wid}.html"), week_page(repo, wid, days, latest_week))
    feed = build_feed(repo)
    write_feed(repo, feed)
    docs = build_library(repo)
    with open(os.path.join(R, "data", "library.json"), "w", encoding="utf-8") as fh:
        json.dump([{k: v for k, v in x.items() if not k.startswith("_")} | {"found": x.get("_date")} for x in docs], fh, ensure_ascii=False, indent=1)
    with open(os.path.join(R, "data", "search.json"), "w", encoding="utf-8") as fh:
        json.dump(search_index(repo), fh, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(R, "data", "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "latest": repo.days[-1]["date"], "days": [
            {"date": d["date"], "status": d.get("status", "full"), "findings": len(d.get("findings", [])),
             "legacy": bool(d.get("legacy")), "week": iso_week(parse_iso(d["date"]))} for d in repo.days]}, fh, indent=1)
    write(os.path.join(R, "archive.html"), archive_page(repo, latest_week))
    write(os.path.join(R, "library.html"), library_page(repo, docs, latest_week))
    write(os.path.join(R, "pipeline.html"), pipeline_page(repo, feed, latest_week))
    write(os.path.join(R, "method.html"), method_page(latest_week))
    write(os.path.join(R, ".nojekyll"), "")
    # final privacy sweep over everything that will be published
    leaks = []
    for p in glob.glob(os.path.join(R, "**", "*"), recursive=True):
        if os.path.isfile(p) and p.endswith((".html", ".json", ".csv")) and "/.git/" not in p:
            t = open(p, encoding="utf-8", errors="replace").read()
            t = re.sub(r'href="[^"]*"', "", t)
            m = EMAIL_RX.search(t)
            if m:
                leaks.append(f"{os.path.relpath(p, R)}: {m.group(0)}")
    if leaks:
        print("\n".join(leaks))
        sys.exit("PRIVACY STOP: e-mail address found in published output. Remove it from the data and rebuild.")
    print(f"built {len(repo.days)} daily pages, {len(weeks)} weekly pages, feed rows "
          f"{', '.join(f'{k}:{len(v)}' for k, v in feed.items())}, library {len(docs)} docs; latest {repo.days[-1]['date']}")

def cmd_validate(args):
    bad = 0
    for p in args.files:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        e, w = validate_day(d, os.path.basename(p))
        for x in w:
            print("warn:", x)
        for x in e:
            print("ERROR:", x)
        bad += len(e)
        print(f"{os.path.basename(p)}: {len(d.get('findings', []))} findings, {len(d.get('library', []))} documents, "
              f"{len(e)} errors, {len(w)} warnings")
    sys.exit(1 if bad else 0)

def cmd_last(args):
    repo = Repo(args.repo)
    today = parse_iso(args.today) if args.today else dt.date.today()
    last = parse_iso(repo.days[-1]["date"]) if repo.days else None
    yday = today - dt.timedelta(days=1)
    start = (last if last else yday - dt.timedelta(days=2))
    if last == today:
        print(json.dumps({"today": today.isoformat(), "already_published": True, "last": last.isoformat()}))
        return
    frm = max(start, today - dt.timedelta(days=7))
    if today.weekday() == 0:          # Monday: Friday..Sunday at least
        frm = min(frm, today - dt.timedelta(days=3))
    print(json.dumps({"today": today.isoformat(), "weekday": today.strftime("%A"), "last_published": last.isoformat() if last else None,
                      "coverage_from": frm.isoformat(), "coverage_to": yday.isoformat(),
                      "label": (f"{frm.strftime('%a')} {frm.day} {frm.strftime('%b')} – {yday.strftime('%a')} {yday.day} {yday.strftime('%b %Y')}"
                                if frm != yday else f"{yday.strftime('%A')} {yday.day} {yday.strftime('%B %Y')}"),
                      "is_friday": today.weekday() == 4, "iso_week": iso_week(today)}, indent=1))

def cmd_seen(args):
    repo = Repo(args.repo)
    words = [w.lower() for w in args.words]
    cutoff = (dt.date.today() - dt.timedelta(days=args.days)).isoformat() if args.days else ""
    n = 0
    for d in reversed(repo.days):
        if d["date"] < cutoff:
            break
        for f in d.get("findings", []):
            hay = " ".join(str(f.get(k, "")) for k in ("title", "summary", "entity", "company")).lower()
            hay += " " + " ".join(s.get("url", "") for s in f.get("sources", [])).lower()
            if all(w in hay for w in words):
                s0 = (f.get("sources") or [{}])[0]
                print(f"{d['date']}  [{f.get('stream')}] {f.get('title')}  <{s0.get('url', '')}>  article {f.get('article_date')}")
                n += 1
    print(f"-- {n} earlier finding(s) mention: {' + '.join(args.words)}")

def cmd_match(args):
    with open(args.index, encoding="utf-8") as fh:
        idx = json.load(fh)
    q = norm_name(args.name)
    cands = []
    for kind in ("malls", "brands", "services"):
        for m in idx.get(kind, []):
            if args.country and m.get("country") and args.country.lower() not in m["country"].lower():
                continue
            n = norm_name(m["name"])
            r = difflib.SequenceMatcher(None, q, n).ratio()
            tq, tn = set(q.split()), set(n.split())
            jacc = len(tq & tn) / max(1, len(tq | tn))
            score = max(r, jacc)
            cands.append((score, kind, m))
    cands.sort(key=lambda x: -x[0])
    for score, kind, m in cands[:args.top]:
        print(f"{score:.2f}  {kind[:-1]:7} {m['name']}  | {m.get('city', '')}, {m.get('country', '')} | {m.get('status', '')} | "
              f"{m.get('type', '')} | GLA {m.get('gla_sqm', '-')} | {m.get('slug', '')}")
    best = cands[0][0] if cands else 0
    print("-- verdict:", "LISTED (check the match)" if best >= 0.86 else "POSSIBLE MATCH - check by hand" if best >= 0.7 else "NOT LISTED")

def cmd_week(args):
    d = parse_iso(args.date) if args.date else dt.date.today()
    w = iso_week(d)
    mon, sun = week_dates(w)
    print(json.dumps({"date": d.isoformat(), "week": w, "monday": mon.isoformat(), "sunday": sun.isoformat()}))

def cmd_tracker(args):
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl is not installed here; run this on the computer (python3 has it there).")
    wb = openpyxl.load_workbook(args.xlsx, read_only=True, data_only=True)
    out = {}
    for sh, name_col, extra in (("10 Intel New Properties", 2, 4), ("11 Intel Listing Updates", 2, 3), ("12 Intel Article Ideas", 1, 3)):
        if sh not in wb.sheetnames:
            continue
        rows = []
        for r in wb[sh].iter_rows(min_row=5, values_only=True):
            if r and len(r) > name_col and r[name_col] and (sh[:2] != "12" or r[0]):
                rows.append({"tag": r[1], "name": r[name_col], "country_or_fit": r[extra] if len(r) > extra else None})
        out[sh] = rows
    print(json.dumps(out, ensure_ascii=False, indent=0, default=str))

def cmd_prospects(args):
    out_dir, repo_dir = os.path.abspath(args.out), os.path.abspath(args.repo)
    if out_dir == repo_dir or out_dir.startswith(repo_dir + os.sep):
        sys.exit("REFUSED: prospects are internal and must never be written inside the public repository.")
    rows = OrderedDict()
    for p in sorted(glob.glob(os.path.join(args.src, "*.json"))):
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
        for x in d.get("prospects", []):
            k = norm_name(x.get("company", ""))
            if not k:
                continue
            r = rows.setdefault(k, {**x, "first_seen": d.get("date"), "last_seen": d.get("date"), "triggers": []})
            r.update({kk: vv for kk, vv in x.items() if vv})
            r["last_seen"] = d.get("date")
            r["triggers"].append(f"{d.get('date')}: {x.get('trigger', '')} <{x.get('source_url', '')}>")
    cols = ["priority", "company", "country", "segment", "status_hint", "suggested", "trigger", "source_url", "first_seen", "last_seen"]
    items = sorted(rows.values(), key=lambda r: ({"High": 0, "Medium": 1, "Low": 2}.get(r.get("priority"), 3), r.get("last_seen", "")), reverse=False)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "MECSR_Intel_Prospects.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([c.upper() for c in cols] + ["ALL TRIGGERS"])
        for r in items:
            w.writerow([r.get(c, "") for c in cols] + [" | ".join(r["triggers"])])
    trs = "".join("<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" if c != "source_url" else
                                   f'<td><a href="{esc(r.get(c, ""))}">{esc(domain(r.get(c, "")))}</a></td>' for c in cols) + "</tr>" for r in items)
    doc = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>MECSR Intel · Membership & sales prospects (INTERNAL)</title>"
           "<style>body{font:14px/1.5 system-ui,Segoe UI,Arial;margin:16px;color:#17150f;background:#fff}h1{font-size:20px}"
           "table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #e3e0d8;padding:6px 8px;text-align:left;vertical-align:top}"
           "th{background:#f0eee8;font-size:12px}.warn{background:#fee2e2;color:#7f1d1d;padding:8px 12px;border-radius:8px}</style>"
           f"<h1>Membership &amp; sales prospects from the daily intel (INTERNAL)</h1>"
           f"<p class=warn>Internal to MECSR. Do not publish, forward outside MECSR or commit to GitHub. Built {dt.date.today().isoformat()} from {len(items)} companies.</p>"
           "<table><thead><tr>" + "".join(f"<th>{esc(c.replace('_', ' ').upper())}</th>" for c in cols) + "</tr></thead><tbody>" + trs + "</tbody></table>")
    with open(os.path.join(out_dir, "MECSR_Intel_Prospects.html"), "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"prospects: {len(items)} companies -> {out_dir}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build"); b.add_argument("--repo", default=here); b.add_argument("--force", action="store_true"); b.set_defaults(fn=cmd_build)
    v = sp.add_parser("validate"); v.add_argument("files", nargs="+"); v.set_defaults(fn=cmd_validate)
    l = sp.add_parser("last"); l.add_argument("--repo", default=here); l.add_argument("--today"); l.set_defaults(fn=cmd_last)
    s = sp.add_parser("seen"); s.add_argument("words", nargs="+"); s.add_argument("--repo", default=here); s.add_argument("--days", type=int, default=0); s.set_defaults(fn=cmd_seen)
    m = sp.add_parser("match"); m.add_argument("name"); m.add_argument("--country"); m.add_argument("--index", required=True); m.add_argument("--top", type=int, default=5); m.set_defaults(fn=cmd_match)
    w = sp.add_parser("week"); w.add_argument("date", nargs="?"); w.set_defaults(fn=cmd_week)
    t = sp.add_parser("tracker"); t.add_argument("--xlsx", required=True); t.set_defaults(fn=cmd_tracker)
    p = sp.add_parser("prospects"); p.add_argument("--src", required=True); p.add_argument("--out", required=True); p.add_argument("--repo", default=here); p.set_defaults(fn=cmd_prospects)
    args = ap.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
