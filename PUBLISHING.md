# Publishing this paper

**Not legal advice.** This is how to make the paper count as published, so it works as prior art, and how to make that easy to prove later.

## What makes it "officially" published?

There's no official stamp. What counts, in both the US and Europe, is that:

1. **The public can get at it.** It must be somewhere anyone interested could find and read it without signing anything. In the US the test is that a person interested in the subject, searching with reasonable care, could find it. In Europe it's that it was "made available to the public": no confidentiality, anyone could have looked.
2. **You can prove when.** The date that matters is the first day it was publicly available. Git commit dates can be edited, so they're weak evidence on their own. A record kept by someone else is strong evidence: a DOI from Zenodo, the publication date on Technical Disclosure Commons, or an Internet Archive snapshot.
3. **It describes the thing well enough to build it.** That's section 9 of the paper.

So the plan is to put it in several independent places on the same day.

## Steps (in this order)

**1. GitHub** (the home of the paper)

1. Unzip `a-bonding-experience.zip`. In GitHub Desktop: *File > Add local repository*, pick the `a-bonding-experience` folder, and say yes to creating a repository there.
2. Commit everything, then *Publish repository*. **Untick "Keep this code private".** Name it `a-bonding-experience` so the links in the paper work.
3. On github.com, open the repository's *Settings > Pages* and set *Source* to "Deploy from a branch", branch `main`, folder `/docs`. The web version appears at `https://the-dorkknight.github.io/a-bonding-experience/` after a minute or two.

This is separate from the private LoK Walls repository. Nothing about Shift-LoK's code is in here.

**2. Zenodo** (a permanent copy with a DOI, kept by CERN)

1. Go to <https://zenodo.org>, *Log in with GitHub*.
2. In Zenodo, open *GitHub* from your account menu, find `a-bonding-experience` in the list and switch it **on**. Do this *before* step 3.
3. On GitHub: *Releases > Draft a new release*, tag `v1.0`, title "A Bonding Experience v1.0", attach `a-bonding-experience-v1.0.pdf`, and publish.
4. Zenodo archives the release by itself and gives it a DOI (it reads `.zenodo.json` for the title, author and licence). Put the DOI in `README.md` and `CITATION.cff` in a later commit.

**3. Technical Disclosure Commons** (made for defensive publications, free)

1. Go to <https://www.tdcommons.org>, create an account and submit the PDF.
2. It gets a publication date stamped on its page and on the PDF's front page. It is designed to be indexed by Google Patents, which helps examiners find it.

**4. Internet Archive** (an independent dated snapshot)

Paste each of these into <https://web.archive.org/save> and save:

- the GitHub repository page;
- `PAPER.md` on GitHub;
- the Pages web version;
- the Zenodo record.

**5. Tell people** (makes it findable, and the jokes deserve an audience)

Post `DEVTO_POST.md` on dev.to, linking the repository and the DOI. Optional extras: Reddit r/3Dprinting, the Printables or Prusa forums, the OrcaSlicer discussions. More readers means more people who saw it, on a date.

## Keep for your records

- The DOI, the TDCommons link, the Wayback snapshot links and the date.
- A copy of the PDF exactly as published.

## Later versions

Change the paper, bump the version (v1.1…), and make a new GitHub release. Zenodo gives each version its own DOI under one "concept" DOI. Never edit the history of v1.0: its date is the point.
