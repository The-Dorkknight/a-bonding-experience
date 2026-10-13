#!/bin/sh
# Rebuilds docs/index.html and the PDF from PAPER.md (needs pandoc and Python Playwright with Chromium).
set -e
cd "$(dirname "$0")/.."
python3 - <<'PY'
t=open('PAPER.md').read()
base="https://github.com/The-Dorkknight/a-bonding-experience/blob/main/"
tree="https://github.com/The-Dorkknight/a-bonding-experience/tree/main/"
t=t.replace("](LICENSE.md)","]("+base+"LICENSE.md)").replace("](LICENSE-CODE.md)","]("+base+"LICENSE-CODE.md)")
t=t.replace("[`model/`](model/)","[`model/`]("+tree+"model)")
open('build/paper_web.md','w').write(t)
PY
pandoc build/paper_web.md -f gfm -t html5 -s --metadata pagetitle="A Bonding Experience" --css style.css --embed-resources --resource-path=.:build -o docs/index.html
python3 - <<'PY'
t=open('docs/index.html').read()
import re
t=re.sub(r'<html[^>]*>','<html lang="en-GB">',t,1)
t=t.replace('<head>','<head>\n  <meta name="description" content="A hobbyist\'s field guide to Z-strength in FDM printing without tripping over patents, and a defensive publication of PinLoK (pinned infill). Matthew Armstrong, 13 October 2026.">\n  <meta name="author" content="Matthew Armstrong">\n  <meta name="citation_title" content="A Bonding Experience">\n  <meta name="citation_author" content="Armstrong, Matthew">\n  <meta name="citation_publication_date" content="2026/10/13">',1)
open('docs/index.html','w').write(t)
from playwright.sync_api import sync_playwright
import pathlib
p=pathlib.Path('docs/index.html').resolve()
with sync_playwright() as pw:
    b=pw.chromium.launch()
    pg=b.new_page(); pg.emulate_media(media="print", color_scheme="light")
    pg.goto(p.as_uri()); pg.wait_for_timeout(500)
    pg.pdf(path='a-bonding-experience-v1.0.pdf', format='A4', margin=dict(top='18mm',bottom='18mm',left='16mm',right='16mm'), print_background=True,
           display_header_footer=True, header_template='<div></div>',
           footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#666">A Bonding Experience · M. Armstrong · v1.0, 13 October 2026 · CC BY-SA 4.0 · strength figures are theoretical (simulated) · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>')
    b.close()
PY
echo built
