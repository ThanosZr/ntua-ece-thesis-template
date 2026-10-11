#!/usr/bin/env python3
"""Edge-case test suite for the ntua-thesis class.

Each test copies the template to a fresh temporary directory, applies
modifications to main.tex, builds it with latexmk and checks the result.

Usage:  python3 tests/run_tests.py [test-name-substring ...]
Needs:  TeX Live (pdflatex, xelatex, lualatex, latexmk, bibtex, makeindex),
        poppler-utils (pdftotext, pdffonts, pdfinfo).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "edgecases.tex")
ENGINE_FLAG = {"pdf": "-pdf", "xe": "-xelatex", "lua": "-lualatex"}
SHIPPED_OPTS = "modern,hyperref,watermark,histinit,noindex,plain,newlogo"
FULL_OPTS = "modern,hyperref,watermark,histinit,newlogo"


# --------------------------------------------------------------------------
# helpers that modify main.tex
# --------------------------------------------------------------------------
def set_options(opts):
    def f(tex):
        return re.sub(r"\\documentclass\[[^\]]*\]\{ntua-thesis\}",
                      lambda m: "\\documentclass[%s]{ntua-thesis}" % opts,
                      tex, count=1)
    return f


def replace(old, new):
    def f(tex):
        assert old in tex, "pattern not found in main.tex: %r" % old
        return tex.replace(old, new, 1)
    return f


def preamble(code):
    return replace("\\begin{document}", code + "\n\\begin{document}")


def with_fixture(tex):
    return tex.replace("\t\\include{body_matter/intro}",
                       "\t\\include{body_matter/intro}\n"
                       "\t\\include{body_matter/edgecases}", 1)


def fixture_text(wrap_latin):
    src = open(FIXTURE, encoding="utf-8").read()
    if wrap_latin:
        return re.sub(r"\[\[(.+?)\]\]", r"\\en{\1}", src)
    return re.sub(r"\[\[(.+?)\]\]", r"\1", src)


# --------------------------------------------------------------------------
# build + checks
# --------------------------------------------------------------------------
def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          errors="replace")


def build(workdir, engine):
    t0 = time.time()
    r = run(["latexmk", ENGINE_FLAG[engine], "-interaction=nonstopmode",
             "-halt-on-error", "main.tex"], workdir)
    return r.returncode, time.time() - t0


def fold(text):
    """Upper-case and strip accents (Greek capitals carry no tonos)."""
    import unicodedata
    d = unicodedata.normalize("NFD", text.upper())
    return "".join(c for c in d if c not in "\u0301\u0308\u0342")


def checks_for(workdir, engine, expect, forbid, strict_fonts):
    """Return a list of failure messages (empty list = pass)."""
    fails = []
    log = open(os.path.join(workdir, "main.log"), encoding="utf-8",
               errors="replace").read()
    pdf = os.path.join(workdir, "main.pdf")
    if not os.path.exists(pdf):
        return ["no PDF produced"]

    errors = [l for l in log.splitlines() if l.startswith("!")]
    if errors:
        fails.append("TeX errors: %s" % errors[:3])

    missing = sorted(set(re.findall(r"Missing character: There is no (.+?) in font ([^!]+)!", log)))
    if missing:
        fails.append("missing glyphs: %s" % missing[:6])

    for pat, msg in [
        (r"There were undefined references", "undefined references"),
        (r"Citation `[^']+' .*undefined", "undefined citations"),
        (r"Reference `[^']+' .*undefined", "undefined references"),
        (r"There were multiply-defined labels", "multiply-defined labels"),
    ]:
        if re.search(pat, log):
            fails.append(msg)

    if strict_fonts:
        subs = sorted(set(re.findall(r"Font shape `(TU/[^']+)' undefined", log)))
        if subs:
            fails.append("font shape substitutions: %s" % subs[:5])

    # TeX bitmap fonts (.pk) look blurry and are rejected by some archives.
    # (The sample figure peerArchitecture.eps carries its own Type 3 font,
    # which is part of the figure, not of the class, so only .pk is checked.)
    pk = sorted(set(re.findall(r"([\w-]+)\.\d+pk", log)))
    if pk:
        fails.append("bitmap (.pk) fonts used: %s" % pk[:5])

    text = run(["pdftotext", "-enc", "UTF-8", pdf, "-"], workdir).stdout
    norm = text.replace("\u037e", ";")  # Greek question mark -> ;
    norm = norm.replace("\u0387", "\u00b7")  # ano teleia -> middle dot
    norm = norm.replace("\u2423", " ")   # listings visible space
    if engine == "pdf":
        # Kerkis/CB fonts map some glyphs to look-alike code points when
        # text is extracted (µ for μ, ϱ for ρ, ϕ for φ, tonos as a separate
        # mark before capitals). Normalise so the checks compare letters.
        for a, b in [("\u00b5", "μ"), ("\u03f1", "ρ"), ("\u03d5", "φ"),
                     ("\u2206", "Δ"), ("\u2126", "Ω"),
                     ("\u0384Α", "Ά"), ("\u0384Ε", "Έ"), ("\u0384Η", "Ή"),
                     ("\u0384Ι", "Ί"), ("\u0384Ο", "Ό"), ("\u0384Υ", "Ύ"),
                     ("\u0384Ω", "Ώ")]:
            norm = norm.replace(a, b)
    norm = re.sub(r"-\n", "", norm)       # undo end-of-line hyphenation
    norm = re.sub(r"\s+", " ", norm)
    squeezed = norm.replace(" ", "")
    caps = fold(norm)
    for s in expect:
        if s in norm:
            continue
        # headings typeset in (small) capitals drop the Greek accents
        if fold(s) in caps:
            continue
        # pdfLaTeX fixed-column listings put each Greek letter in its own
        # cell, so pdftotext inserts spaces; compare without spaces there.
        if engine == "pdf" and s.replace(" ", "") in squeezed:
            continue
        # single tokens such as URLs may be broken across lines
        if " " not in s and s in squeezed:
            continue
        fails.append("expected text not found: %r" % s)
    for s in forbid:
        if s in norm:
            fails.append("forbidden text found: %r" % s)
    return fails


# --------------------------------------------------------------------------
# test definitions
# --------------------------------------------------------------------------
COMMON_EXPECT = ["Εθνικό Μετσόβιο Πολυτεχνείο", "Περιεχόμενα"]
COMMON_FORBID = ["Kat'alogoc", "Kat’alogoc", "Diplwmatik", "Eik'ona", "Eik’ona"]
LATIN_ONLY_AUTHORS = [
    replace("\\authorNameCapitalGR{ΝΙΚΟΥ ΜΑΤΣΑΜΠΛΟΣΚΟΥ}", "\\authorNameCapitalGR{}"),
    replace("\\authorNameGR{Νικόλαος Ματσαμπλόκος}", "\\authorNameGR{}"),
    replace("%\\authorNameEN{Albert Einstein}", "\\authorNameEN{John Smith}"),
    replace("\n     \\coverpageimage{0.8}{figures/rdf.png}", "\n%     no cover image"),
]
FIXTURE_EXPECT = [
    "Machine Learning", "Python 3.12", "PyTorch", "scikit-learn",
    "Τι είναι το Deep Learning;", "αϊδόνι", "προϊόν", "«εισαγωγικά»",
    "Άλφα Έψιλον Ήτα", "Peer-to-Peer systems", "Related Work",
    "English text", "Supercalifragilisticexpialidocious", "Τρίγωνο",
    "Triangle", "mixed table", "σχόλιο στα ελληνικά", "Γειά σου",
    "Semantic Web", "Ευρετήριο ελληνικών όρων", "def hello",
    "https://www.ece.ntua.gr/el/undergraduate/courses?x=1&y=2",
    "ναι· σωστά", "γιατί;",
    # bibliography strings produced by ntua.bst
    "Συστήματα Υπολογιστών", "έκδοση", "Πτυχιακή εργασία", "Samarin",
]
FIXTURE_FORBID = [
    "ηττπ", "δεφ", "δεϕ", "ηελλο", "πριντ",   # Latin printed as Greek
    "Deep Learning·", "Deep Learning ·",       # ";" printed as ano teleia
    "σχόλιοσταελληνικά",                        # spaces lost in listings
    "ekdosh", "Ptuqiak", " kai ", "Sto ",      # LGR transliteration in .bst
]


def T(name, engine, mods, expect=(), forbid=(), fixture=None,
      strict_fonts=None, then=None, extra_files=None):
    return dict(name=name, engine=engine, mods=mods, expect=list(expect),
                forbid=list(forbid), fixture=fixture,
                strict_fonts=(engine != "pdf") if strict_fonts is None else strict_fonts,
                then=then, extra_files=extra_files or {})


MULTI_AUTHORS = [
    replace("\\toutis{του}", "\\toutis{των}"),
    replace("\\authorNameCapitalGR{ΝΙΚΟΥ ΜΑΤΣΑΜΠΛΟΣΚΟΥ}",
            "\\authorNameCapitalGR{ΚΩΝΣΤΑΝΤΙΝΟΥ Δ. ΔΗΜΗΤΡΙΟΥ, ΓΕΩΡΓΙΟΥ Π. ΠΑΝΑΓΑΚΗ}"),
    replace("\\authorNameGR{Νικόλαος Ματσαμπλόκος}",
            "\\authorNameGR{Κωνσταντίνος Δημητρίου, Γεώργιος Παναγάκης}"),
    replace("%\\authorNameEN{Albert Einstein}",
            "\\authorNameEN{Albert Einstein, Marie Curie}"),
]
LONG_TITLE = replace(
    "\\title{Πρότυπο Σύστημα Ομότιμων Κόμβων \\\\Βασισμένο σε Σχήματα \\en{RDF}}",
    "\\title[Ένας Πολύ Μεγάλος Τίτλος \\\\ για Deep Learning Μοντέλα]"
    "{Ένας Πολύ Μεγάλος Τίτλος για Deep Learning Μοντέλα \\\\ "
    "σε Συστήματα Ομότιμων Κόμβων και Σημασιολογικού Ιστού}")
TIKZ_COVER = replace(
    "\n     \\coverpageimage{0.8}{figures/rdf.png}",
    "\n     \\coverpageimage[tikz]{0.5}{\n"
    "  \\draw[thick, gray] \\foreach \\x in {18,90,...,306} {\n"
    "    (\\x:4) node{} -- (\\x+72:4)\n"
    "    (\\x:4) -- (\\x:3) node{}\n"
    "  };\n"
    "}")
NO_SUBTITLE = replace("\t\\subtitle{Μελέτη και υλοποίηση}", "\t\\subtitle{}")
CMU_FONT = preamble(
    "\\setmainfont{cmun}[Extension=.otf, UprightFont=*rm, BoldFont=*bx,\n"
    "  ItalicFont=*ti, BoldItalicFont=*bi]")

TESTS = [
    # 1. Exactly what the repository ships (plain + noindex), pdfLaTeX.
    T("01-shipped-main-pdflatex", "pdf", [set_options(SHIPPED_OPTS)],
      expect=COMMON_EXPECT + ["Πρότυπο Σύστημα Ομότιμων Κόμβων"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 2. All features on (TikZ cover, chapter art, watermark, index) - the
    #    combination that used to fail with 76 TikZ errors.
    T("02-all-features-pdflatex", "pdf", [set_options(FULL_OPTS), with_fixture],
      fixture="wrap", expect=COMMON_EXPECT + FIXTURE_EXPECT + ["Διπλωματική Εργασία"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 3-4. Same with the Unicode engines and *bare* Latin text (no \en{}).
    T("03-all-features-xelatex-bare-latin", "xe", [set_options(FULL_OPTS), with_fixture],
      fixture="bare", expect=COMMON_EXPECT + FIXTURE_EXPECT + ["Διπλωματική Εργασία"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    T("04-all-features-lualatex-bare-latin", "lua", [set_options(FULL_OPTS), with_fixture],
      fixture="bare", expect=COMMON_EXPECT + FIXTURE_EXPECT + ["Διπλωματική Εργασία"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 5-6. "classic" font option on both engine families.
    T("05-classic-pdflatex", "pdf",
      [set_options(FULL_OPTS.replace("modern", "classic")), with_fixture],
      fixture="wrap", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    T("06-classic-xelatex", "xe",
      [set_options(FULL_OPTS.replace("modern", "classic")), with_fixture],
      fixture="bare", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 7. Grayscale printer version without hyperref, XeLaTeX.
    T("07-printer-nohyperref-xelatex", "xe",
      [set_options("modern,printer,watermark,histinit,newlogo"), with_fixture],
      fixture="bare", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 8. Minimal options (no hyperref, no watermark, no initials), pdfLaTeX.
    T("08-minimal-options-pdflatex", "pdf",
      [set_options("modern"), with_fixture],
      fixture="wrap", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 9. Two students, Latin names too, long title with different cover
    #    line breaks and bare English words in the title, empty subtitle.
    T("09-two-authors-long-title-xelatex", "xe",
      [set_options(FULL_OPTS)] + MULTI_AUTHORS + [LONG_TITLE, NO_SUBTITLE],
      expect=["ΚΩΝΣΤΑΝΤΙΝΟΥ Δ. ΔΗΜΗΤΡΙΟΥ", "Γεώργιος Παναγάκης",
              "ALBERT EINSTEIN", "Marie Curie", "Deep Learning Μοντέλα"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    T("10-two-authors-long-title-pdflatex", "pdf",
      [set_options(FULL_OPTS)] + MULTI_AUTHORS + [
          replace("\\title{Πρότυπο Σύστημα Ομότιμων Κόμβων \\\\Βασισμένο σε Σχήματα \\en{RDF}}",
                  "\\title[Ένας Πολύ Μεγάλος Τίτλος \\\\ για \\en{Deep Learning} Μοντέλα]"
                  "{Ένας Πολύ Μεγάλος Τίτλος για \\en{Deep Learning} Μοντέλα \\\\ "
                  "σε Συστήματα Ομότιμων Κόμβων}"), NO_SUBTITLE],
      expect=["ΚΩΝΣΤΑΝΤΙΝΟΥ Δ. ΔΗΜΗΤΡΙΟΥ", "ALBERT EINSTEIN", "Deep Learning Μοντέλα"],
      forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 11-12. TikZ cover image (code with ";" inside the Greek document).
    T("11-tikz-cover-pdflatex", "pdf", [set_options(FULL_OPTS), TIKZ_COVER],
      expect=COMMON_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    T("12-tikz-cover-lualatex", "lua", [set_options(FULL_OPTS), TIKZ_COVER],
      expect=COMMON_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 13. Student overrides the main font from main.tex (CMU Serif).
    T("13-font-override-xelatex", "xe", [set_options(FULL_OPTS), CMU_FONT, with_fixture],
      fixture="bare", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 14-15. Switching compiler on Overleaf leaves old .aux files behind.
    T("14-stale-aux-pdflatex-then-xelatex", "pdf",
      [set_options(FULL_OPTS), with_fixture], fixture="wrap",
      then="xe", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    T("15-stale-aux-xelatex-then-pdflatex", "xe",
      [set_options(FULL_OPTS), with_fixture], fixture="wrap",
      then="pdf", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 16. Old-style \en{} everywhere must keep working under XeLaTeX.
    T("16-legacy-en-wrappers-xelatex", "xe", [set_options(FULL_OPTS), with_fixture],
      fixture="wrap", expect=COMMON_EXPECT + FIXTURE_EXPECT, forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 17. Shipped options under LuaLaTeX (plain + noindex fast path).
    T("17-shipped-main-lualatex", "lua", [set_options(SHIPPED_OPTS)],
      expect=COMMON_EXPECT + ["Πρότυπο Σύστημα Ομότιμων Κόμβων"], forbid=COMMON_FORBID + FIXTURE_FORBID),
    # 18. Exchange student: only a Latin-script name, no Greek name, no
    #     cover image, empty subtitle.
    T("18-latin-name-only-no-cover-xelatex", "xe",
      [set_options(FULL_OPTS)] + LATIN_ONLY_AUTHORS + [NO_SUBTITLE],
      expect=["JOHN SMITH", "John Smith"], forbid=COMMON_FORBID),
    T("19-latin-name-only-no-cover-pdflatex", "pdf",
      [set_options(FULL_OPTS)] + LATIN_ONLY_AUTHORS + [NO_SUBTITLE],
      expect=["JOHN SMITH", "John Smith"], forbid=COMMON_FORBID),
]


def pdf_title(workdir):
    out = run(["pdfinfo", "main.pdf"], workdir).stdout
    m = re.search(r"^Title:\s*(.*)$", out, re.M)
    return m.group(1).strip() if m else ""


def run_test(t, keep):
    work = tempfile.mkdtemp(prefix="ntua-%s-" % t["name"])
    shutil.copytree(ROOT, work, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "tests", "*.aux",
                                                  "*.log", "main.pdf", "*.bbl",
                                                  "*.fls", "*.fdb_latexmk"))
    main = os.path.join(work, "main.tex")
    tex = open(main, encoding="utf-8").read()
    for m in t["mods"]:
        tex = m(tex)
    open(main, "w", encoding="utf-8").write(tex)
    if t["fixture"]:
        with open(os.path.join(work, "body_matter", "edgecases.tex"), "w",
                  encoding="utf-8") as fh:
            fh.write(fixture_text(t["fixture"] == "wrap"))

    rc, secs = build(work, t["engine"])
    engines = t["engine"]
    if t["then"] and rc == 0:
        # switch engine without cleaning auxiliary files (like Overleaf);
        # force a rebuild because latexmk would otherwise reuse main.pdf
        os.remove(os.path.join(work, "main.pdf"))
        rc, secs2 = build(work, t["then"])
        secs += secs2
        engines += "->" + t["then"]
    fails = [] if rc == 0 else ["latexmk exit code %d" % rc]
    fails += checks_for(work, t["then"] or t["engine"], t["expect"],
                        t["forbid"], t["strict_fonts"])
    title = pdf_title(work)
    opts = re.search(r"\\documentclass\[([^\]]*)\]\{ntua-thesis\}", tex).group(1)
    if "hyperref" in opts.split(",") and not title:
        fails.append("empty PDF title metadata")
    pages = re.search(r"Pages:\s*(\d+)", run(["pdfinfo", "main.pdf"], work).stdout)
    if not keep and not fails:
        shutil.rmtree(work, ignore_errors=True)
    return fails, secs, engines, (pages.group(1) if pages else "?"), title, work


def main():
    keep = "--keep" in sys.argv
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
    tests = [t for t in TESTS if not wanted or any(w in t["name"] for w in wanted)]
    failed = 0
    results = []
    for t in tests:
        fails, secs, engines, pages, title, work = run_test(t, keep)
        results.append(dict(name=t["name"], engines=engines, seconds=round(secs, 1),
                            pages=pages, passed=not fails, failures=fails))
        status = "PASS" if not fails else "FAIL"
        failed += bool(fails)
        print("%s  %-40s %-9s %5.1fs %3s pages  title=%r"
              % (status, t["name"], engines, secs, pages, title[:45]))
        for f in fails:
            print("      - %s" % f)
        if fails:
            print("      workdir kept: %s" % work)
        sys.stdout.flush()
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    import json
    import platform
    tex = run(["pdflatex", "--version"], ROOT).stdout.splitlines()[0]
    with open(os.path.join(ROOT, "tests", "last_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(dict(date=time.strftime("%Y-%m-%d %H:%M"), tex=tex,
                       python=platform.python_version(), results=results),
                  fh, ensure_ascii=False, indent=1)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
