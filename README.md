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

Each weekday edition is prepared in the early morning, Dubai time, by a scheduled Claude run on MECSR's
office PC (or by hand in a Claude session when that run cannot run), under the MECSR Directory Source
Policy v1.0. The run writes one file, `data/daily/<date>.json`, rebuilds every page with
`tools/intel.py build` (standard-library Python, no dependencies) and leaves an upload folder of the
changed files, which MECSR checks and uploads here. Nothing on the site is edited by hand. When a
published item is corrected, that edition's run notes carry a dated line.

- `python3 tools/intel.py build` rebuilds the site
- `python3 tools/intel.py validate data/daily/<date>.json` checks a day file (`--members <file>` also
  warns when a member flag disagrees with a member file)
- `python3 tools/intel.py seen <words>` finds earlier findings (duplicate check)
- `python3 tools/intel.py month <YYYY-MM>` lists the month's findings for the What's Up Retail newsletter

## What is never in this repository

GitHub Pages is readable by anyone with the link, so this repository holds public news and public
documents only. No personal contact data, e-mail addresses or phone numbers; no membership status,
prospect lists or CRM data; nothing from the tracker's sheets 07, 08 or 09. The build stops if an
e-mail address reaches the output, and `validate` rejects internal-only fields. Membership prospects
are kept in MECSR's internal OneDrive folder.

## Publishing (GitHub web upload)

The run cannot push to GitHub, so each edition's upload folder goes up through the GitHub website,
**one folder at a time**: uploading everything on the top-level page flattens the folders.

| Folder in the upload | Upload page |
|---|---|
| `daily` (html) | https://github.com/orient-alt/mecsr-intel/upload/main/daily |
| `data/daily` (json) | https://github.com/orient-alt/mecsr-intel/upload/main/data/daily |
| `weekly` (html) | https://github.com/orient-alt/mecsr-intel/upload/main/weekly |
| `data` (files only, not the daily subfolder) | https://github.com/orient-alt/mecsr-intel/upload/main/data |
| `tools` (only when the upload has it) | https://github.com/orient-alt/mecsr-intel/upload/main/tools |
| top level (html and README.md) | https://github.com/orient-alt/mecsr-intel/upload/main |

After the last commit, open https://orient-alt.github.io/mecsr-intel/data/index.json: `"latest"`
should show the new date, and no new file should sit at the repository root.
