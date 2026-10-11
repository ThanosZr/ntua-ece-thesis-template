#!/usr/bin/env python3
"""Build the files under docs/ from the current template.

    python3 docs/build_docs.py              # use tests/last_results.json
    python3 docs/build_docs.py --run-tests  # run the test suite first

Produces:
    docs/overleaf-template.zip   the template, ready for Overleaf "Upload Project"
    docs/report.pdf              description of the fixes + proof of operation
    docs/report-src/meta.tex, results.tex, timings.tex  (generated tables)

Needs TeX Live (pdflatex, xelatex, lualatex, latexmk) and poppler-utils.
"""
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
SRC = os.path.join(DOCS, "report-src")
ORIGINAL_JSON = os.path.join(SRC, "original-errors.json")

SHIPPED_OPTS = "modern,hyperref,watermark,histinit,noindex,plain,newlogo"
FULL_OPTS = "modern,hyperref,watermark,histinit,newlogo"
ENGINES = [("pdf", "pdfLaTeX", "pdflatex"), ("xe", "XeLaTeX", "xelatex"),
           ("lua", "LuaLaTeX", "lualatex")]
TEMPLATE_FILES = ["main.tex", "ntua-thesis.cls", "ntua.bst", "references.bib",
                  "LICENSE", "README.md"]
TEMPLATE_DIRS = ["front_matter", "body_matter", "back_matter", "figures", "logo"]

DESCRIPTIONS = {
    "01": "Το main.tex όπως διανέμεται (plain, noindex)",
    "02": "Όλες οι επιλογές (TikZ, υδατογράφημα, ευρετήριο) + κεφάλαιο ελέγχου με \\verb|\\en{}|",
    "03": "Όλες οι επιλογές, αγγλικά \\emph{χωρίς} \\verb|\\en{}|",
    "04": "Όλες οι επιλογές, αγγλικά \\emph{χωρίς} \\verb|\\en{}|",
    "05": "Γραμματοσειρά classic",
    "06": "Γραμματοσειρά classic, χωρίς \\verb|\\en{}|",
    "07": "Ασπρόμαυρη έκδοση (printer), χωρίς hyperref",
    "08": "Ελάχιστες επιλογές (μόνο modern)",
    "09": "Δύο φοιτητές, λατινικά ονόματα, μεγάλος τίτλος, κενός υπότιτλος",
    "10": "Δύο φοιτητές, λατινικά ονόματα, μεγάλος τίτλος, κενός υπότιτλος",
    "11": "Εικόνα εξωφύλλου σε TikZ (κώδικας με «;»)",
    "12": "Εικόνα εξωφύλλου σε TikZ (κώδικας με «;»)",
    "13": "Δική μας γραμματοσειρά (\\verb|\\setmainfont|, CMU Serif)",
    "14": "Αλλαγή compiler με παλιά βοηθητικά αρχεία",
    "15": "Αλλαγή compiler με παλιά βοηθητικά αρχεία",
    "16": "Παλιό στυλ: παντού \\verb|\\en{}|",
    "17": "Το main.tex όπως διανέμεται (plain, noindex)",
    "18": "Μόνο λατινικό ονοματεπώνυμο, χωρίς εικόνα εξωφύλλου",
    "19": "Μόνο λατινικό ονοματεπώνυμο, χωρίς εικόνα εξωφύλλου",
}
ENGINE_NAMES = {"pdf": "pdfLaTeX", "xe": "XeLaTeX", "lua": "LuaLaTeX"}


def run(cmd, cwd, timeout=900):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          errors="replace", timeout=timeout)


def set_options(tex, opts):
    return re.sub(r"\\documentclass\[[^\]]*\]\{ntua-thesis\}",
                  lambda m: "\\documentclass[%s]{ntua-thesis}" % opts, tex, count=1)


def copy_template(dest):
    for f in TEMPLATE_FILES:
        shutil.copy2(os.path.join(ROOT, f), dest)
    for d in TEMPLATE_DIRS:
        shutil.copytree(os.path.join(ROOT, d), os.path.join(dest, d),
                        ignore=shutil.ignore_patterns(".DS_Store"))


def with_options(dest, opts):
    main = os.path.join(dest, "main.tex")
    tex = open(main, encoding="utf-8").read()
    open(main, "w", encoding="utf-8").write(set_options(tex, opts))


# --------------------------------------------------------------------------
def build_zip():
    out = os.path.join(DOCS, "overleaf-template.zip")
    with tempfile.TemporaryDirectory() as tmp:
        copy_template(tmp)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _, files in os.walk(tmp):
                for f in sorted(files):
                    full = os.path.join(base, f)
                    z.write(full, os.path.relpath(full, tmp))
        # the zip must compile as-is
        with zipfile.ZipFile(out) as z:
            z.extractall(os.path.join(tmp, "check"))
        r = run(["latexmk", "-xelatex", "-interaction=nonstopmode",
                 "-halt-on-error", "main.tex"], os.path.join(tmp, "check"))
        if r.returncode != 0:
            sys.exit("overleaf-template.zip does not compile with XeLaTeX")
    print("wrote", out, "(%d kB, compiles with XeLaTeX)" % (os.path.getsize(out) // 1024))


def time_passes():
    """Seconds for one engine pass with ready auxiliary files (median of 3)."""
    rows = []
    for key, name, binary in ENGINES:
        for label, opts in [("plain,noindex", SHIPPED_OPTS), ("όλες", FULL_OPTS)]:
            with tempfile.TemporaryDirectory() as tmp:
                copy_template(tmp)
                with_options(tmp, opts)
                r = run(["latexmk", "-" + ("pdf" if key == "pdf" else binary),
                         "-interaction=nonstopmode", "main.tex"], tmp)
                if r.returncode != 0:
                    sys.exit("timing build failed: %s %s" % (name, label))
                secs = []
                for _ in range(3):
                    t0 = time.time()
                    run([binary, "-interaction=nonstopmode", "main.tex"], tmp)
                    secs.append(time.time() - t0)
                pages = re.search(r"Pages:\s*(\d+)",
                                  run(["pdfinfo", "main.pdf"], tmp).stdout).group(1)
                rows.append((name, label, statistics.median(secs), pages))
                print("timing %-9s %-14s %.2fs" % (name, label, statistics.median(secs)))
    return rows


def original_errors():
    """Count TeX errors of the original template (git HEAD of estamos' repo).

    Uses the commit history when available; otherwise keeps the numbers
    stored in report-src/original-errors.json."""
    try:
        cls = subprocess.check_output(["git", "show", "HEAD:ntua-thesis.cls"],
                                      cwd=ROOT, stderr=subprocess.DEVNULL)
    except Exception:
        cls = b""
    if b"Diplwmatik'h Ergas'ia" not in cls:
        return json.load(open(ORIGINAL_JSON, encoding="utf-8"))
    result = {}
    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.check_output(["git", "archive", "HEAD"], cwd=ROOT)
        subprocess.run(["tar", "-x", "-C", tmp], input=archive, check=True)
        with_options(tmp, FULL_OPTS)
        for key, binary in [("pdf", "pdflatex"), ("xe", "xelatex")]:
            for f in os.listdir(tmp):
                if f.startswith("main.") and f != "main.tex":
                    os.remove(os.path.join(tmp, f))
            run([binary, "-interaction=nonstopmode", "main.tex"], tmp)
            log = open(os.path.join(tmp, "main.log"), encoding="utf-8",
                       errors="replace").read()
            result[key] = sum(1 for l in log.splitlines() if l.startswith("!"))
    json.dump(result, open(ORIGINAL_JSON, "w", encoding="utf-8"))
    print("original template errors:", result)
    return result


# --------------------------------------------------------------------------
def write_tables(results, timings, orig):
    res = results["results"]
    passed = sum(r["passed"] for r in res)
    pages = max(int(r["pages"]) for r in res if r["pages"].isdigit())
    tex_version = re.sub(r"\s*\(.*", "", results["tex"])
    with open(os.path.join(SRC, "meta.tex"), "w", encoding="utf-8") as f:
        f.write("\\newcommand{\\testcount}{%d}\n" % len(res))
        f.write("\\newcommand{\\testpassed}{%d}\n" % passed)
        f.write("\\newcommand{\\pagesample}{%d}\n" % pages)
        f.write("\\newcommand{\\testdate}{%s}\n" % results["date"])
        f.write("\\newcommand{\\texversion}{%s}\n" % results["tex"].replace("_", "\\_"))
        f.write("\\newcommand{\\origpdferrors}{%d}\n" % orig["pdf"])
        f.write("\\newcommand{\\origxeerrors}{%d}\n" % orig["xe"])
        f.write("\\date{Έλεγχοι: %s · %s}\n" % (results["date"], tex_version))

    with open(os.path.join(SRC, "results.tex"), "w", encoding="utf-8") as f:
        f.write("\\begin{longtable}{@{}r>{\\raggedright}p{0.47\\linewidth}lrrl@{}}\n"
                "\\toprule\n\\# & \\textbf{Σενάριο} & \\textbf{Μηχανή} & "
                "\\textbf{Χρόνος} & \\textbf{Σελ.} & \\\\\n\\midrule\\endhead\n")
        for r in res:
            num = r["name"][:2]
            eng = " → ".join(ENGINE_NAMES[e] for e in r["engines"].split("->"))
            f.write("%s & %s & %s & %.1f\\,s & %s & %s\\\\\n" % (
                num, DESCRIPTIONS.get(num, r["name"]), eng, r["seconds"],
                r["pages"], "\\PASS" if r["passed"] else "\\FAIL"))
            for fail in r["failures"]:
                f.write("& \\multicolumn{5}{l}{\\footnotesize\\detokenize{%s}}\\\\\n" % fail)
        f.write("\\bottomrule\n\\end{longtable}\n")
        f.write("\\noindent Αποτέλεσμα: \\textbf{%d από %d} σενάρια πέρασαν. "
                "Ο χρόνος είναι για πλήρη μεταγλώττιση από την αρχή "
                "(όλα τα περάσματα, BibTeX, ευρετήριο).\n" % (passed, len(res)))

    with open(os.path.join(SRC, "timings.tex"), "w", encoding="utf-8") as f:
        f.write("\\begin{center}\\begin{tabular}{@{}llrr@{}}\n\\toprule\n"
                "\\textbf{Μηχανή} & \\textbf{Επιλογές} & \\textbf{Ένα πέρασμα} & "
                "\\textbf{Σελίδες}\\\\\n\\midrule\n")
        for name, label, secs, pg in timings:
            f.write("%s & %s & %.1f\\,s & %s\\\\\n" % (name, label, secs, pg))
        f.write("\\bottomrule\n\\end{tabular}\\end{center}\n")


def render_cover():
    """Page 1 of the shipped main.tex with XeLaTeX, for the project page."""
    with tempfile.TemporaryDirectory() as tmp:
        copy_template(tmp)
        r = run(["latexmk", "-xelatex", "-interaction=nonstopmode",
                 "-halt-on-error", "main.tex"], tmp)
        if r.returncode != 0:
            sys.exit("cover build failed")
        run(["pdftoppm", "-f", "1", "-l", "1", "-png", "-singlefile",
             "-scale-to-x", "620", "-scale-to-y", "-1", "main.pdf",
             os.path.join(DOCS, "img", "cover_page")], tmp)
    print("wrote", os.path.join(DOCS, "img", "cover_page.png"))


def update_index(results):
    """Keep the test score on the project page in sync with the results."""
    path = os.path.join(DOCS, "index.html")
    html = open(path, encoding="utf-8").read()
    res = results["results"]
    passed = sum(r["passed"] for r in res)
    new = re.sub(r'(<div class="score" id="score">)\d+<small>από \d+ περνούν</small>',
                 lambda m: "%s%d<small>από %d περνούν</small>" % (m.group(1), passed, len(res)),
                 html)
    open(path, "w", encoding="utf-8").write(new)
    print("index.html: %d/%d" % (passed, len(res)))


def build_report():
    r = run(["latexmk", "-xelatex", "-interaction=nonstopmode", "-halt-on-error",
             "report.tex"], SRC)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        sys.exit("report.tex failed to compile")
    shutil.copy2(os.path.join(SRC, "report.pdf"), os.path.join(DOCS, "report.pdf"))
    run(["latexmk", "-c", "report.tex"], SRC)
    for f in ["report.pdf", "report.xdv"]:
        p = os.path.join(SRC, f)
        if os.path.exists(p):
            os.remove(p)
    print("wrote", os.path.join(DOCS, "report.pdf"))


def main():
    if "--run-tests" in sys.argv:
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_tests.py")])
    results = json.load(open(os.path.join(ROOT, "tests", "last_results.json"),
                             encoding="utf-8"))
    build_zip()
    orig = original_errors()
    timings = time_passes()
    write_tables(results, timings, orig)
    render_cover()
    update_index(results)
    build_report()


if __name__ == "__main__":
    main()
