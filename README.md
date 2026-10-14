# MECSR Intel

One page a day of retail, customer-experience and AI intelligence for MECSR and MECSC, with every
earlier day, a weekly summary, a reference library of reports and manuals, and a feed of new and
changed properties for the 2027 MECSR Directory.

Live site: **https://orient-alt.github.io/mecsr-intel/**

| Page | What it shows |
|---|---|
| `index.html` | Today's edition |
| `weekly/<year>-W<week>.html` | The weekly summary: every finding of the week, with its sources |
| `daily/<date>.html` | Every earlier edition, from 16 June 2026 |
| `archive.html` | All weeks and days, plus a search across every finding |
| `library.html` | Market reports, results decks and filings, fit-out manuals, guidelines, CX standards |
| `pipeline.html` | Rows for the 2027 Directory tracker (sheets 10, 11 and 12), with CSV downloads |
| `method.html` | How the intelligence is researched and what is never published |

## How it updates

A scheduled Claude run researches every weekday at 08:00 Dubai under the MECSR Directory Source
Policy v1.0 and writes one file: `data/daily/<date>.json`. Every page is then rebuilt from those
files by `tools/intel.py build` (standard-library Python, no dependencies). Nothing on the site is
edited by hand.

- `python3 tools/intel.py build` rebuilds the site
- `python3 tools/intel.py validate data/daily/<date>.json` checks a day file
- `python3 tools/intel.py seen <words>` finds earlier findings (duplicate check)

## What is never in this repository

GitHub Pages is readable by anyone with the link, so this repository holds public news and public
documents only. No personal contact data, e-mail addresses or phone numbers; no membership status,
prospect lists or CRM data; nothing from the tracker's sheets 07, 08 or 09. The build stops if an
e-mail address reaches the output, and `validate` rejects internal-only fields. Membership prospects
are kept in MECSR's internal OneDrive folder.

## Publishing with GitHub Desktop

The folder `Documents\GitHub\mecsr-intel` is already a Git repository connected to
`orient-alt/mecsr-intel`. One-time setup:

1. GitHub Desktop: **File → Add local repository**, choose `Documents\GitHub\mecsr-intel`, then **Add repository**.
2. Type a summary such as `MECSR Intel site`, press **Commit to main**, then **Publish branch**.
3. On GitHub: **Settings → Pages → Deploy from a branch → main / (root) → Save**. The site is live at the
   address above a few minutes later.

After each run the changed files appear under **Changes**: type a summary such as `Daily intel 15 Oct`,
press **Commit to main**, then **Push origin**. Several days can go in one push.
