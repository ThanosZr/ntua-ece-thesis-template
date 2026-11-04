#!/usr/bin/env python3
"""Offline compiler για το πρότυπο διπλωματικής ΣΗΜΜΥ ΕΜΠ.

Ανοίγει στον browser μια σελίδα με κουμπί Compile, τα σφάλματα με τη γραμμή
τους και προεπισκόπηση του PDF. Δουλεύει χωρίς internet.

Χρειάζεται:
  - Python 3.8 ή νεότερη (μόνο η βασική βιβλιοθήκη, τίποτα για εγκατάσταση)
  - TeX: TeX Live 2023+ (Windows, Linux), MacTeX (macOS) ή MiKTeX (Windows)

Χρήση, μέσα στον φάκελο του προτύπου:
  python compile.py                     ανοίγει τη σελίδα στον browser
  python compile.py --once              ένα compile χωρίς σελίδα
  python compile.py --once --engine pdflatex
  python compile.py --once --bw         ασπρόμαυρο PDF για τη βιβλιοθήκη (main-bw.pdf)
  python compile.py --main other.tex    άλλο κύριο αρχείο αντί για main.tex

Στα Windows αρκεί και διπλό κλικ στο αρχείο. Για να σταματήσει, κλείνεις το
παράθυρο της κονσόλας (ή Ctrl+C).
"""

import argparse
import glob
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ENGINES = [("xelatex", "XeLaTeX"), ("pdflatex", "pdfLaTeX"), ("lualatex", "LuaLaTeX")]
ENGINE_NAMES = dict(ENGINES)
DEFAULT_PORT = 8577
MAX_RUNS = 5
RUN_TIMEOUT = 900

# Files the compile writes next to main.tex. Only these are removed by a clean
# compile; nothing the student wrote is ever deleted.
AUX_EXTS = ["aux", "bbl", "blg", "toc", "lof", "lot", "out", "log", "xdv", "fls",
            "fdb_latexmk", "synctex.gz", "idx", "ind", "ilg", "brf", "nav", "snm"]
INDEX_NAMES = ["greek", "english"]
SKIP_DIRS = {".git", ".github", "docs", "tests", "node_modules", "__pycache__", ".vscode"}
SOURCE_EXTS = {".tex", ".bib", ".cls", ".sty", ".bst", ".png", ".jpg", ".jpeg",
               ".pdf", ".eps", ".svg"}

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Finding TeX
# --------------------------------------------------------------------------
def _extra_bin_dirs():
    """Usual install places, for when TeX is installed but not on PATH."""
    pats = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pats += [os.path.join(pf, "gs", "gs*", "bin"),
                 r"C:\texlive\*\bin\windows", r"C:\texlive\*\bin\win64",
                 r"C:\texlive\*\bin\win32",
                 os.path.join(local, "Programs", "MiKTeX", "miktex", "bin", "x64"),
                 os.path.join(pf, "MiKTeX", "miktex", "bin", "x64")]
    else:
        pats += ["/Library/TeX/texbin", "/usr/local/texlive/*/bin/*",
                 os.path.expanduser("~/texlive/*/bin/*"), "/opt/texlive/*/bin/*",
                 "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"]
    dirs = []
    for p in pats:
        dirs += sorted(glob.glob(p), reverse=True)  # newest year first
    return dirs


def which(prog):
    found = shutil.which(prog)
    if found:
        return found
    for d in _extra_bin_dirs():
        for name in (prog, prog + ".exe"):
            cand = os.path.join(d, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def _popen_kwargs():
    kw = {}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kw


def find_gs():
    for name in ("gs", "gswin64c", "gswin32c"):
        p = which(name)
        if p:
            return p
    return None


def _kill_tree(p):
    """End a step and everything it started (e.g. XeLaTeX and its xdvipdfmx)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                           capture_output=True, **_popen_kwargs())
        else:
            os.killpg(p.pid, signal.SIGTERM)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def find_tex():
    engines = {e: which(e) for e, _ in ENGINES}
    engines = {e: p for e, p in engines.items() if p}
    info = {"engines": engines, "bibtex": which("bibtex"), "distribution": ""}
    first = next(iter(engines.values()), None)
    if first:
        try:
            out = subprocess.run([first, "--version"], capture_output=True, text=True,
                                 timeout=30, errors="replace", **_popen_kwargs()).stdout
            m = re.search(r"\((TeX Live [^)]*|MiKTeX [^)]*)\)", out)
            info["distribution"] = m.group(1) if m else out.splitlines()[0][:80]
        except Exception:
            pass
    return info


# --------------------------------------------------------------------------
# Compiling
# --------------------------------------------------------------------------
class Compiler:
    def __init__(self, main_path):
        self.main_path = os.path.abspath(main_path)
        self.root = os.path.dirname(self.main_path)
        self.base = os.path.splitext(os.path.basename(self.main_path))[0]
        self.job = self.base            # main, or main-bw while the B/W copy compiles
        self.bw_job = self.base + "-bw"
        _ROOT[0] = self.root
        self.tex = find_tex()
        self.lock = threading.Lock()
        self.running = False
        self.step = ""
        self.started = 0.0
        self.result = None
        self.pdf_bytes = None
        self.pdf_version = 0
        self.bw_version = 0
        self.bib_failed = False
        self.proc = None
        self.cancelled = False
        pdf = self.path(self.base + ".pdf")
        if os.path.isfile(pdf):
            with open(pdf, "rb") as f:
                self.pdf_bytes = f.read()
            self.pdf_version = int(os.path.getmtime(pdf))

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    # ---- what changed --------------------------------------------------
    def source_stamp(self):
        """Changes whenever the student saves a source file or adds a figure."""
        newest, count = 0.0, 0
        outputs = {os.path.normcase(self.path(j + ".pdf")) for j in (self.base, self.bw_job)}
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext not in SOURCE_EXTS or f.endswith("-converted-to.pdf"):
                    continue
                full = os.path.join(base, f)
                if os.path.normcase(full) in outputs:
                    continue
                try:
                    newest = max(newest, os.path.getmtime(full))
                    count += 1
                except OSError:
                    pass
        return "%d-%d" % (int(newest * 1000), count)

    def _aux_files(self):
        files = [self.path(self.job + "." + e) for e in ("aux", "toc", "lof", "lot", "out")]
        for base, dirs, names in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            files += [os.path.join(base, n) for n in names
                      if n.endswith(".aux") and os.path.join(base, n) not in files]
        return files

    def _digest(self, files):
        h = hashlib.sha1()
        for f in files:
            try:
                with open(f, "rb") as fh:
                    h.update(f.encode("utf-8", "replace") + fh.read())
            except OSError:
                pass
        return h.hexdigest()

    def _citations_digest(self):
        h = hashlib.sha1()
        for f in self._aux_files():
            if not f.endswith(".aux"):
                continue
            try:
                with open(f, "rb") as fh:
                    for line in fh:
                        if line.startswith((b"\\citation", b"\\bibdata", b"\\bibstyle")):
                            h.update(line)
            except OSError:
                pass
        return h.hexdigest()

    def _needs_bibtex(self):
        try:
            with open(self.path(self.job + ".aux"), "rb") as f:
                return b"\\bibdata" in f.read()
        except OSError:
            return False

    def clean(self):
        removed = 0
        names = [j + "." + e for j in (self.base, self.bw_job) for e in AUX_EXTS]
        names += [n + "." + e for n in INDEX_NAMES for e in ("idx", "ind", "ilg")]
        for n in names:
            p = self.path(n)
            if os.path.isfile(p):
                os.remove(p)
                removed += 1
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            if os.path.normcase(base) == os.path.normcase(self.root):
                continue
            for f in files:
                if f.endswith(".aux"):
                    os.remove(os.path.join(base, f))
                    removed += 1
        return removed

    def _run(self, cmd, label):
        self.step = label
        kw = _popen_kwargs()
        if sys.platform != "win32":
            kw["start_new_session"] = True  # so Stop also ends xdvipdfmx etc.
        try:
            p = subprocess.Popen(cmd, cwd=self.root, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        except OSError as e:
            return -1, "%s: %s" % (label, e)
        self.proc = p
        try:
            data, _ = p.communicate(timeout=RUN_TIMEOUT)
            return p.returncode, data.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            _kill_tree(p)
            data, _ = p.communicate()
            return -1, data.decode("utf-8", "replace") + "\n%s: σταμάτησε μετά από %d s" % (
                label, RUN_TIMEOUT)
        finally:
            self.proc = None

    def stop(self):
        self.cancelled = True
        p = self.proc
        if p is not None and p.poll() is None:
            _kill_tree(p)

    def compile(self, engine="xelatex", clean=False, bw=False):
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.started = time.time()
            self.step = "Ξεκινά"
        threading.Thread(target=self._compile, args=(engine, clean, bw), daemon=True).start()
        return True

    def compile_sync(self, engine="xelatex", clean=False, bw=False):
        with self.lock:
            self.running = True
            self.started = time.time()
        self._compile(engine, clean, bw)
        return self.result

    def _compile(self, engine, clean, bw=False):
        self.job = self.bw_job if bw else self.base
        stamp = self.source_stamp()
        steps, out_all = [], []
        ok, errors, warnings, log_tail = False, [], [], ""
        bib_problems, greyed = [], False
        try:
            self.tex = find_tex()
            exe = self.tex["engines"].get(engine)
            if not exe:
                errors.append({"message": "Δεν βρέθηκε το %s σε αυτόν τον υπολογιστή."
                               % ENGINE_NAMES.get(engine, engine),
                               "hint": "Εγκατάστησε TeX (δες την καρτέλα «TeX» της σελίδας) "
                                       "ή διάλεξε άλλη μηχανή."})
                return
            self.cancelled = False
            prev = self._last_engine()
            if not clean and prev and prev != engine:
                # .aux/.toc written by another engine can contain commands this
                # one does not know (e.g. pdfLaTeX's \\LGR for XeLaTeX)
                clean = True
                steps.append("Καθαρισμός (άλλαξε μηχανή)")
            if clean:
                self.clean()
            cmd = [exe, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
                   "-synctex=1"]
            if bw:
                # The class option "printer" gives the black-and-white copy, as
                # main-bw.pdf, without touching main.tex.
                cmd += ["-jobname=" + self.bw_job,
                        "\\PassOptionsToClass{printer}{ntua-thesis}\\input{%s.tex}" % self.base]
            else:
                cmd += [self.base + ".tex"]
            name = ENGINE_NAMES[engine]
            ran_bibtex = False
            for n in range(1, MAX_RUNS + 1):
                before = self._digest(self._aux_files())
                cites_before = self._citations_digest()
                rc, out = self._run(cmd, "%s, πέρασμα %d" % (name, n))
                steps.append(name)
                out_all.append(out)
                if self.cancelled:
                    errors = [{"message": "Το compile σταμάτησε (Διακοπή).", "hint": ""}]
                    return
                if rc != 0:
                    errors = self._explain(self._read_log(), out, engine)
                    return
                if self._needs_bibtex() and self.tex["bibtex"] and (
                        not ran_bibtex and (
                            clean or self.bib_failed
                            or not os.path.isfile(self.path(self.job + ".bbl"))
                            or self._citations_digest() != cites_before
                            or self._bib_newer())):
                    rc, out = self._run([self.tex["bibtex"], self.job], "BibTeX")
                    steps.append("BibTeX")
                    out_all.append(out)
                    if self.cancelled:
                        errors = [{"message": "Το compile σταμάτησε (Διακοπή).", "hint": ""}]
                        return
                    ran_bibtex = True
                    self.bib_failed = rc >= 2
                    if self.bib_failed:
                        bib_problems = parse_blg(self.path(self.job + ".blg"))
                    continue
                log = self._read_log()
                if self._digest(self._aux_files()) == before and not re.search(
                        r"Rerun to get|Label\(s\) may have changed|Rerun LaTeX", log):
                    break
            ok = True
            warnings = bib_problems + parse_warnings(self._read_log())
            pdf = self.path(self.job + ".pdf")
            if os.path.isfile(pdf) and bw:
                gs = find_gs()
                if gs:
                    # figures too: Ghostscript turns every colour into grey
                    tmp = self.path(self.job + "-grey.pdf")
                    rc, out = self._run([gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
                                         "-sDEVICE=pdfwrite", "-sColorConversionStrategy=Gray",
                                         "-dProcessColorModel=/DeviceGray", "-dCompatibilityLevel=1.5",
                                         "-o", tmp, pdf], "Ghostscript: γκρι εικόνες")
                    steps.append("Ghostscript")
                    if rc == 0 and os.path.isfile(tmp):
                        os.replace(tmp, pdf)
                        greyed = True
                    else:
                        warnings = ["Το Ghostscript δεν μπόρεσε να κάνει γκρι τις εικόνες· το PDF "
                                    "έχει μόνο τα στοιχεία του προτύπου ασπρόμαυρα."] + warnings
                else:
                    warnings = ["Οι εικόνες έμειναν όπως είναι: για να γίνουν κι αυτές γκρι, "
                                "εγκαταστήστε το Ghostscript (ghostscript.com)."] + warnings
                self.bw_version += 1
            elif os.path.isfile(pdf):
                with open(pdf, "rb") as f:
                    self.pdf_bytes = f.read()
                self.pdf_version += 1
            else:
                ok = False
                errors = [{"message": "Το compile τελείωσε αλλά δεν βγήκε PDF.",
                           "hint": "Δες το πλήρες log παρακάτω."}]
        except Exception as e:  # never leave the page stuck on "running"
            errors = [{"message": "Απρόσμενο σφάλμα: %s" % e, "hint": ""}]
        finally:
            log_tail = "\n".join(self._read_log().splitlines()[-400:])
            if out_all:
                tail = "\n".join(out_all[-1].splitlines()[-80:])
                log_tail += ("\n\n----- Έξοδος του τελευταίου βήματος "
                             "(τελευταίες γραμμές) -----\n" + tail)
            self.result = {"ok": ok and not errors, "engine": engine, "steps": steps,
                           "bw": bw, "greyed": greyed,
                           "seconds": round(time.time() - self.started, 1),
                           "errors": errors, "warnings": warnings, "log": log_tail,
                           "stamp": stamp, "finished": time.time()}
            self.job = self.base
            self.running = False
            self.step = ""

    def _explain(self, log, out, engine):
        errors = parse_log(log)
        if errors:
            return self._locate(errors)
        # Nothing in the log: the engine or the PDF driver stopped on its own.
        # What it said is in its output, not in the log.
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        text = log + "\n" + out
        driver = [l for l in lines if re.search(
            r"xdvipdfmx:fatal|\*\* ERROR \*\*|Image format conversion|PSfile|[Gg]hostscript|"
            r"rungs|gswin|mgs\.exe", l)]
        miktex = [l for l in lines if re.search(
            r"did not succeed|major issue|required file|could not be installed|MiKTeX", l)]
        eps = self._eps_used()
        for f in re.findall(r"File: (\S+?\.eps) Graphic file \(type eps\)", text, re.I):
            if not any(os.path.normcase(f) == os.path.normcase(x["eps"]) for x in eps):
                eps.append({"eps": f})
        # XeLaTeX hands .eps figures to Ghostscript while it writes the PDF; when
        # that fails, XeLaTeX just stops, with nothing in the log.
        if eps and (driver or "xdvipdfmx" in text or engine == "xelatex"):
            first = eps[0]
            detail = (driver or miktex)[-1:] 
            e = {"message": ("Το compile σταμάτησε στη μετατροπή της εικόνας %s. Οι εικόνες "
                             ".eps θέλουν Ghostscript, που δεν βρέθηκε ή απέτυχε." % first["eps"])
                            + ((" (%s)" % detail[0][:160]) if detail else ""),
                 "hint": ("Μετάτρεψέ την μία φορά σε .pdf ή .png (π.χ. με έναν online μετατροπέα "
                          "EPS σε PDF), βάλ' τη στο figures/ και άλλαξε την κατάληξη στο "
                          "\\includegraphics. Αλλιώς εγκατάστησε Ghostscript "
                          "(ghostscript.com) και ξαναπάτα Compile.")}
            for k in ("file", "line", "context"):
                if k in first:
                    e[k] = first[k]
            return [e]
        if miktex:
            return [{"message": " ".join(miktex[:3])[:400],
                     "hint": ("Άνοιξε το MiKTeX Console: Updates → ενημέρωσε όλα, και Settings → "
                              "«Always install missing packages on-the-fly». Μετά πάτα "
                              "«Καθαρό compile».")}]
        return [{"message": "Η μηχανή σταμάτησε χωρίς μήνυμα στο log. Οι τελευταίες γραμμές που "
                            "έγραψε:",
                 "context": "\n".join((driver or lines)[-6:])[:600],
                 "hint": "Δοκίμασε «Καθαρό compile» ή άλλη μηχανή. Το πλήρες log είναι παρακάτω."}]

    def _eps_used(self):
        """\\includegraphics of .eps files: by extension, or a name with only an .eps file."""
        found = []
        pat = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}")
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in sorted(files):
                if not f.endswith(".tex"):
                    continue
                full = os.path.join(base, f)
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        for n, line in enumerate(fh, 1):
                            for m in pat.finditer(line.split("%")[0]):
                                name = m.group(1).strip()
                                stem, ext = os.path.splitext(name)
                                if ext.lower() == ".eps":
                                    hit = name
                                elif not ext and os.path.isfile(self.path(name + ".eps")) and not any(
                                        os.path.isfile(self.path(name + x))
                                        for x in (".pdf", ".png", ".jpg", ".jpeg")):
                                    hit = name + ".eps"
                                else:
                                    continue
                                found.append({"eps": hit, "line": n, "context": line.strip()[:200],
                                              "file": _rel(os.path.relpath(full, self.root))})
                except OSError:
                    pass
        return found

    def _find_line(self, e, pat):
        for base, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for f in sorted(files):
                if not f.endswith(".tex"):
                    continue
                full = os.path.join(base, f)
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        for n, line in enumerate(fh, 1):
                            if pat.search(line.split("%")[0]):
                                e["file"] = _rel(os.path.relpath(full, self.root))
                                e["line"] = n
                                e["context"] = line.strip()[:200]
                                return True
                except OSError:
                    pass
        return False

    def _locate(self, errors):
        """A missing file is reported without a line: find where it is asked for."""
        for e in errors:
            m = re.search(r"File `([^']+)' not found", e["message"])
            if not m or e.get("file"):
                continue
            name = re.escape(re.sub(r"\.(sty|cls)$", "", m.group(1)))
            pat = re.compile(r"\\(?:usepackage|RequirePackage|includegraphics|input|include)"
                             r"\s*(?:\[[^\]]*\])?\s*\{[^}]*\b" + name + r"(?:\.\w+)?\b")
            self._find_line(e, pat)
        return errors

    def _last_engine(self):
        """The engine of the last compile, normal or B/W: they share the
        chapters' .aux files. Read from the first line of the newest log."""
        logs = [self.path(j + ".log") for j in (self.base, self.bw_job)]
        logs = sorted((l for l in logs if os.path.isfile(l)), key=os.path.getmtime)
        if not logs:
            return None
        with open(logs[-1], "rb") as f:
            first = f.readline().decode("utf-8", "replace")
        if first.startswith("This is pdfTeX"):
            return "pdflatex"
        if first.startswith("This is XeTeX"):
            return "xelatex"
        if first.startswith(("This is LuaHBTeX", "This is LuaTeX")):
            return "lualatex"
        return None

    def _bib_newer(self):
        bbl = self.path(self.job + ".bbl")
        try:
            t = os.path.getmtime(bbl)
        except OSError:
            return True
        return any(os.path.getmtime(b) > t for b in glob.glob(self.path("*.bib")))

    def _read_log(self):
        try:
            with open(self.path(self.job + ".log"), "rb") as f:
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def state(self):
        # TeX installed while the page is open: find it without a restart
        if not self.tex["engines"] and time.time() - getattr(self, "_tex_checked", 0) > 5:
            self._tex_checked = time.time()
            self.tex = find_tex()
        r = self.result
        return {
            "project": self.root, "main": os.path.basename(self.main_path),
            "tex": {"engines": sorted(self.tex["engines"]), "bibtex": bool(self.tex["bibtex"]),
                    "distribution": self.tex["distribution"]},
            "running": self.running, "step": self.step,
            "elapsed": round(time.time() - self.started, 1) if self.running else 0,
            "result": r, "pdf_version": self.pdf_version if self.pdf_bytes else 0,
            "bw_version": self.bw_version if os.path.isfile(self.path(self.bw_job + ".pdf")) else 0,
            "gs": bool(find_gs()),
            "stamp": self.source_stamp(),
        }


# --------------------------------------------------------------------------
# Reading the log: errors with file and line, in plain words
# --------------------------------------------------------------------------
FILE_LINE = re.compile(r"^(?:\./)?(.+?\.(?:tex|cls|sty|bib|bst|clo|def|cfg|aux|toc|lof|lot|loi|"
                       r"bbl|ind|out|nav)):(\d+): (.*)$")
AUX_FILE = re.compile(r"\.(aux|toc|lof|lot|loi|bbl|ind|out|nav)$")


_ROOT = [""]


def _rel(f):
    if os.path.isabs(f) and _ROOT[0]:
        try:
            f = os.path.relpath(f, _ROOT[0])
        except ValueError:
            pass
    f = f.replace("\\", "/")
    return f[2:] if f.startswith("./") else f


def _hint(msg):
    m = re.search(r"File `([^']+)' not found", msg)
    if m:
        pkg = re.sub(r"\.(sty|cls)$", "", m.group(1))
        if re.search(r"\.(sty|cls)$", m.group(1)):
            return ("Λείπει το πακέτο «%s». Στο MiKTeX εγκαθίσταται μόνο του (ή από το "
                    "MiKTeX Console)· στο TeX Live: tlmgr install %s" % (pkg, pkg))
        return "Δεν βρέθηκε το αρχείο «%s». Έλεγξε το όνομα και τον φάκελο." % m.group(1)
    if "Undefined control sequence" in msg:
        return ("Άγνωστη εντολή: λάθος στο γράψιμο ή λείπει κάποιο \\usepackage{…} "
                "στο main.tex. Η εντολή είναι στο τέλος της γραμμής που φαίνεται.")
    if "font-not-found" in msg or "cannot be found" in msg and "font" in msg.lower():
        return ("Λείπει γραμματοσειρά. Με πλήρες TeX Live / MiKTeX υπάρχουν όλες του "
                "προτύπου· αλλιώς βάλε άλλη με \\setmainfont{…}.")
    if "Unable to load picture" in msg or re.search(r"File `[^']+\.(png|jpe?g|pdf|eps)' not found", msg):
        return ("Δεν βρέθηκε η εικόνα. Έλεγξε το όνομα (και κεφαλαία/πεζά) και ότι είναι "
                "στον φάκελο figures/, π.χ. \\includegraphics{figures/σχήμα.png}.")
    if "-eps-converted-to.pdf" in msg:
        return ("Μια εικόνα .eps δεν μετατράπηκε σε PDF: χρειάζεται Ghostscript. Μετάτρεψέ την μία "
                "φορά σε .pdf ή .png και άλλαξε την κατάληξη στο \\includegraphics, ή εγκατάστησε "
                "Ghostscript (ghostscript.com).")
    if "I can't write on file" in msg:
        return "Κλείσε το PDF στο πρόγραμμα που το έχεις ανοιχτό και ξαναπάτα Compile."
    if "Missing $ inserted" in msg:
        return "Μαθηματικό σύμβολο (π.χ. _ ή ^) έξω από $…$, ή ένα $ που δεν έκλεισε."
    if "File ended while scanning" in msg or "Paragraph ended before" in msg:
        return ("Ένα άγκιστρο { δεν κλείνει. Αν η γραμμή είναι ένα \\include{…}, το λάθος "
                "είναι μέσα σε εκείνο το αρχείο.")
    if "Missing } inserted" in msg or "Extra }" in msg or "Runaway argument" in msg:
        return "Κάποιο άγκιστρο { } δεν κλείνει σωστά λίγο πριν από αυτή τη γραμμή."
    if re.search(r"\\begin\{[^}]*\} on input line \d+ ended by", msg) or "ended by \\end" in msg:
        return "Ένα \\begin{…} κλείνει με λάθος \\end{…}."
    if "Emergency stop" in msg or "*** (job aborted" in msg:
        return "Το compile σταμάτησε· η αιτία είναι συνήθως το πρώτο σφάλμα πιο πάνω."
    return ""


def parse_log(log):
    lines = log.splitlines()
    errors = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FILE_LINE.match(line)
        if m or line.startswith("! "):
            msg = m.group(3) if m else line[2:]
            # error messages continue until a blank line; the "l.<n>" line shows
            # where TeX stopped
            j, extra, context, skip_next = i + 1, [], "", False
            while j < len(lines) and j < i + 12 and lines[j].strip():
                lj = lines[j]
                if re.match(r"^l\.\d+ ", lj):
                    context = lj.split(" ", 1)[1].strip()
                    nxt = lines[j + 1].strip() if j + 1 < len(lines) else ""
                    if nxt:
                        context += " " + nxt
                    break
                if lj.startswith("<"):  # <to be read again>, <inserted text>: TeX internals
                    skip_next = True
                elif skip_next:
                    skip_next = False
                elif not context and len(extra) < 3 and not lj.startswith(("See the", "Type ", "! ")):
                    extra.append(lj.strip())
                j += 1
            full = msg + (" " + " ".join(extra) if extra and len(msg) < 60 else "")
            err = {"message": full.strip(), "hint": _hint(full)}
            if m:
                err["file"] = _rel(m.group(1))
                if AUX_FILE.search(err["file"]):
                    err["hint"] = ("Το σφάλμα είναι στο %s, ένα βοηθητικό αρχείο που έγραψε "
                                   "προηγούμενο compile (π.χ. με άλλη μηχανή). Πάτα «Καθαρό "
                                   "compile»." % err["file"])
                err["line"] = int(m.group(2))
            if context:
                err["context"] = re.sub(r"\^\^[IM]", " ", context).strip()[:200]
            if not any(e["message"] == err["message"] and e.get("line") == err.get("line")
                       for e in errors):
                errors.append(err)
            i = j
        elif "xdvipdfmx:fatal" in line:
            errors.append({"message": line.strip(), "hint": ""})
        i += 1
    # the first error is the real one; "Emergency stop" etc. only follow from it
    real = [e for e in errors if "Emergency stop" not in e["message"]
            and "job aborted" not in e["message"]]
    return (real or errors)[:8]


def parse_blg(path):
    """BibTeX problems as warnings: the PDF still comes out, like on Overleaf."""
    try:
        with open(path, "rb") as f:
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return ["BibTeX: απέτυχε· δες το αρχείο main.blg."]
    out = []
    for k, l in enumerate(lines):
        m = re.search(r"^(.*?)---line (\d+) of file (\S+)", l)
        if m:
            what = m.group(1).strip() or (lines[k - 1].strip() if k else "")
            out.append("BibTeX, %s γραμμή %s: %s" % (m.group(3), m.group(2), what))
        elif re.match(r"I couldn't open|I found no", l):
            out.append("BibTeX: " + l.strip())
    return out[:10] or ["BibTeX: υπάρχει σφάλμα· δες το αρχείο main.blg."]


def parse_warnings(log):
    found = []
    for m in re.finditer(r"(Citation|Reference) `([^']+)' on page (\d+) undefined", log):
        kind = "Παραπομπή" if m.group(1) == "Citation" else "Αναφορά"
        text = "%s «%s» χωρίς αντιστοιχία (σελ. %s)" % (kind, m.group(2), m.group(3))
        if text not in found:
            found.append(text)
    return found[:30]


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Offline compiler</title>
<style>
:root{--paper:#fff;--ink:#26211c;--muted:#6b6157;--brown:#9f8060;--brown-ink:#6e5235;
 --rule:#e4dbd0;--tint:#f6f1eb;--bad:#a23b2a;--bad-bg:#fbeee9;--good:#2f6b3a;--on-brown:#fff;
 --mono:ui-monospace,"Cascadia Mono",Menlo,Consolas,monospace;
 --text:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#1c1916;--ink:#ede6dd;
 --muted:#b3a89b;--brown:#c4a27f;--brown-ink:#d9bc9c;--rule:#3b342d;--tint:#262220;--bad:#e08a78;
 --bad-bg:#2e201c;--good:#8fcf9b;--on-brown:#1c1916}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{height:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--text);display:flex;flex-direction:column}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid var(--rule)}
header b{font:600 17px/1.2 var(--text)} header b span{color:var(--brown)}
header small{color:var(--muted);font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere}
main{flex:1;display:grid;grid-template-columns:400px minmax(0,1fr);min-height:0}
aside{border-right:1px solid var(--rule);padding:18px;overflow:auto;display:flex;flex-direction:column;gap:16px}
.card{border:1px solid var(--rule);border-radius:8px;padding:12px 14px}
.card h3{margin:0 0 6px;font-size:13px;font-weight:600;color:var(--muted);text-transform:none}
.engines{display:flex;gap:6px;flex-wrap:wrap}
.engines label{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--rule);border-radius:6px;padding:6px 10px;cursor:pointer;font-size:14px}
.engines input{accent-color:var(--brown-ink)}
.engines label.off{opacity:.45;cursor:not-allowed}
.buttons{display:flex;gap:8px;flex-wrap:wrap}
button,.btn{font:500 15px/1 var(--text);padding:12px 16px;border-radius:6px;border:1px solid var(--brown-ink);cursor:pointer;background:transparent;color:var(--brown-ink);text-decoration:none;display:inline-flex;align-items:center;gap:8px}
button.primary{background:var(--brown-ink);color:var(--on-brown);flex:1;justify-content:center;font-size:16px}
button:disabled{opacity:.5;cursor:not-allowed}
button:focus-visible,.btn:focus-visible,input:focus-visible{outline:2px solid var(--brown);outline-offset:2px}
.auto{display:flex;align-items:center;gap:8px;font-size:14px;cursor:pointer}
.auto input{accent-color:var(--brown-ink);width:16px;height:16px}
.status{font-size:14px;display:flex;align-items:center;gap:8px;min-height:22px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--muted);flex:none}
.status.ok .dot{background:var(--good)} .status.fail .dot{background:var(--bad)}
.status.run .dot{background:var(--brown);animation:pulse 1s infinite}
@keyframes pulse{50%{opacity:.3}}
@media (prefers-reduced-motion:reduce){.status.run .dot{animation:none}}
.err{background:var(--bad-bg);border:1px solid color-mix(in srgb,var(--bad) 35%,transparent);border-radius:8px;padding:10px 12px}
.err .where{font:600 12.5px/1.4 var(--mono);color:var(--bad);overflow-wrap:anywhere}
.err .msg{margin:4px 0 0;font-weight:500}
.err code{display:block;margin-top:6px;font:12.5px/1.45 var(--mono);background:var(--paper);border-radius:4px;padding:6px 8px;overflow-wrap:anywhere;white-space:pre-wrap}
.err .hint{margin:6px 0 0;font-size:13.5px;color:var(--muted)}
#export .hint{margin:8px 0 0;font-size:13px;color:var(--muted)}
.slow{margin:-6px 0 0;font-size:13.5px;color:var(--muted)}
.warn{font-size:13.5px;color:var(--muted)} .warn ul{margin:6px 0 0;padding-left:18px}
details summary{cursor:pointer;color:var(--muted);font-size:13.5px}
pre.log{font:11.5px/1.45 var(--mono);background:var(--tint);border-radius:6px;padding:10px;max-height:340px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.notex p{margin:6px 0} .notex ul{margin:6px 0;padding-left:18px} .notex li{margin-bottom:4px}
a{color:var(--brown-ink)}
.preview{position:relative;background:var(--tint);min-height:0}
.preview iframe{position:absolute;inset:0;width:100%;height:100%;border:0;background:var(--tint)}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;color:var(--muted);padding:24px}
.offline{background:var(--bad);color:#fff;padding:8px 18px;font-size:14px;display:none}
@media (max-width:900px){main{grid-template-columns:minmax(0,1fr);grid-template-rows:auto 75vh}
 aside{border-right:0;border-bottom:1px solid var(--rule)} body{height:auto}}
</style></head><body>
<div class="offline" id="offline">Ο compiler σταμάτησε (έκλεισε το παράθυρο της κονσόλας;). Ξανάνοιξέ τον με <code>python compile.py</code>.</div>
<header><b>ntua<span>-</span>thesis · Offline compiler</b><small id="project"></small></header>
<main>
<aside>
  <div class="card" id="texcard"><h3>TeX</h3><div id="tex">Έλεγχος…</div></div>
  <div class="card"><h3>Μηχανή</h3><div class="engines" id="engines"></div></div>
  <div class="buttons">
    <button class="primary" id="go">Compile</button>
    <button id="clean" title="Σβήνει τα βοηθητικά αρχεία (.aux, .toc …) και κάνει compile από την αρχή">Καθαρό compile</button>
    <button id="stop" hidden>Διακοπή</button>
  </div>
  <label class="auto"><input type="checkbox" id="auto"> Αυτόματο compile σε κάθε αποθήκευση</label>
  <div class="status" id="status"><span class="dot"></span><span id="statustext">Πάτα Compile.</span></div>
  <p class="slow" id="slow" hidden></p>
  <div id="errors"></div>
  <div id="warnings"></div>
  <div class="buttons" id="pdfbtns" hidden>
    <a class="btn" id="openpdf" href="/pdf" target="_blank" rel="noopener">Άνοιγμα PDF σε νέα καρτέλα</a>
  </div>
  <div class="card" id="export" hidden><h3>Εξαγωγή</h3>
    <div class="buttons"><button id="bw">Ασπρόμαυρο PDF</button>
      <a class="btn" id="openbw" href="/pdf-bw" target="_blank" rel="noopener" hidden>Άνοιγμα</a></div>
    <p class="hint" id="bwnote">Για τη βιβλιοθήκη και την εκτύπωση: τα χρώματα του προτύπου γίνονται γκρι
      (επιλογή <code>printer</code>), χωρίς αλλαγή στο main.tex. Βγαίνει ως main-bw.pdf στον φάκελο.<span></span></p>
  </div>
  <details id="logbox" hidden><summary>Πλήρες log</summary><pre class="log" id="log"></pre></details>
</aside>
<section class="preview">
  <iframe id="pdf" title="Προεπισκόπηση PDF" hidden></iframe>
  <div class="empty" id="empty">Το PDF θα εμφανιστεί εδώ μετά το πρώτο compile.</div>
</section>
</main>
<script>
"use strict";
const TOKEN = "__TOKEN__";
const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem("ntua-compile-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("ntua-compile-" + k, JSON.stringify(v)); } catch (e) {} }
};
const NAMES = {xelatex: "XeLaTeX", pdflatex: "pdfLaTeX", lualatex: "LuaLaTeX"};
let engine = store.get("engine", "xelatex");
let lastPdf = -1, lastResult = null, seenStamp = null, stableStamp = null, enginesDrawn = "";
$("auto").checked = store.get("auto", false);

function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", cache: "no-store",
    headers: {"X-Token": TOKEN, "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function compile(clean, bw) {
  api("/api/compile", {engine: engine, clean: !!clean, bw: !!bw}).then(draw).catch(() => {});
}
$("bw").onclick = () => compile(false, true);
$("go").onclick = () => compile(false);
$("clean").onclick = () => compile(true);
$("stop").onclick = () => api("/api/stop", {}).then(draw).catch(() => {});
$("auto").onchange = () => store.set("auto", $("auto").checked);

function drawEngines(tex) {
  const key = tex.engines.join(",") + "|" + engine;
  if (key === enginesDrawn) return;
  enginesDrawn = key;
  if (!tex.engines.includes(engine) && tex.engines.length) engine = tex.engines.includes("xelatex") ? "xelatex" : tex.engines[0];
  $("engines").innerHTML = Object.keys(NAMES).map((e) => {
    const has = tex.engines.includes(e);
    return '<label class="' + (has ? "" : "off") + '"><input type="radio" name="engine" value="' + e + '"' +
      (e === engine ? " checked" : "") + (has ? "" : " disabled") + "> " + NAMES[e] +
      (e === "xelatex" ? " <small>(προτείνεται)</small>" : "") + "</label>";
  }).join("");
  document.querySelectorAll('input[name="engine"]').forEach((r) => r.onchange = () => {
    engine = r.value; store.set("engine", engine); enginesDrawn = "";
  });
}

function drawTex(tex) {
  if (tex.engines.length) {
    $("tex").innerHTML = "Βρέθηκε: <b>" + esc(tex.distribution || "TeX") + "</b>" +
      (tex.bibtex ? "" : "<br><small>Δεν βρέθηκε BibTeX: η βιβλιογραφία δεν θα βγει.</small>");
    $("texcard").classList.remove("notex");
    return;
  }
  $("texcard").classList.add("notex");
  $("tex").innerHTML = "<p><b>Δεν βρέθηκε TeX σε αυτόν τον υπολογιστή.</b> Για offline compile χρειάζεται μία εγκατάσταση (μία φορά):</p><ul>" +
    '<li><b>Windows:</b> <a href="https://miktex.org/download" target="_blank" rel="noopener">MiKTeX</a> (στην εγκατάσταση: «Install missing packages on-the-fly: Yes») ή <a href="https://tug.org/texlive/windows.html" target="_blank" rel="noopener">TeX Live</a></li>' +
    '<li><b>macOS:</b> <a href="https://tug.org/mactex/" target="_blank" rel="noopener">MacTeX</a></li>' +
    "<li><b>Linux:</b> <code>sudo apt install texlive-full</code> ή αντίστοιχο</li></ul>" +
    "<p>Μόλις τελειώσει η εγκατάσταση, η σελίδα το βρίσκει μόνη της. Αν δεν το βρει, κλείσε και ξανάνοιξε τον compiler.</p>";
}

function draw(s) {
  $("offline").style.display = "none";
  $("project").textContent = s.project + (s.main !== "main.tex" ? " · " + s.main : "");
  drawTex(s.tex); drawEngines(s.tex);
  const noTex = !s.tex.engines.length;
  $("go").disabled = s.running || noTex;
  $("bw").disabled = s.running || noTex;
  $("export").hidden = noTex;
  $("openbw").hidden = !s.bw_version; $("openbw").href = "/pdf-bw?v=" + s.bw_version;
  $("bwnote").lastChild.textContent = s.gs ? " Οι εικόνες γίνονται κι αυτές γκρι (Ghostscript)." : " Οι εικόνες μένουν όπως είναι: για να γίνουν κι αυτές γκρι χρειάζεται το Ghostscript.";
  $("clean").disabled = s.running || noTex;
  $("go").textContent = s.running ? "Compile…" : "Compile";
  $("stop").hidden = !s.running; $("clean").hidden = s.running;
  if (s.running && s.elapsed > 40) {
    $("slow").hidden = false;
    $("slow").textContent = /MiKTeX/.test(s.tex.distribution)
      ? "Την πρώτη φορά το MiKTeX κατεβάζει πακέτα και γραμματοσειρές· μπορεί να πάρει μερικά λεπτά. Αν ανοίξει παράθυρο του MiKTeX για εγκατάσταση πακέτου, πάτα «Install» (ίσως είναι πίσω από τον browser)."
      : "Αργεί περισσότερο από το συνηθισμένο. Αν δεν προχωρά, πάτα Διακοπή.";
  } else { $("slow").hidden = true; }
  const st = $("status"), r = s.result;
  st.className = "status " + (s.running ? "run" : r ? (r.ok ? "ok" : "fail") : "");
  if (s.running) {
    $("statustext").textContent = (s.step || "Compile") + " · " + Math.round(s.elapsed) + " s";
  } else if (r) {
    const when = new Date(r.finished * 1000).toLocaleTimeString("el-GR");
    const steps = r.steps.length ? " · " + summarize(r.steps) : "";
    $("statustext").textContent = (r.ok ? (r.bw ? "Ασπρόμαυρο PDF έτοιμο σε " : "Έτοιμο σε ") + fmt(r.seconds) + " s" : "Σφάλμα") + steps + " · " + when;
  }
  if (r !== null && JSON.stringify(r) !== lastResult) {
    lastResult = JSON.stringify(r);
    $("errors").innerHTML = r.ok ? "" : r.errors.map((e) =>
      '<div class="err">' + (e.file ? '<div class="where">' + esc(e.file) + (e.line ? ", γραμμή " + e.line : "") + "</div>" : "") +
      '<p class="msg">' + esc(e.message) + "</p>" + (e.context ? "<code>" + esc(e.context) + "</code>" : "") +
      (e.hint ? '<p class="hint">' + esc(e.hint) + "</p>" : "") + "</div>").join("") +
      (!r.ok && s.pdf_version ? '<p class="warn">Η προεπισκόπηση δείχνει το τελευταίο PDF που βγήκε σωστά.</p>' : "");
    $("warnings").innerHTML = r.ok && r.warnings.length ? '<div class="warn"><details' + (r.warnings.some((w) => w.startsWith("BibTeX")) ? " open" : "") + "><summary>" + r.warnings.length +
      " προειδοποιήσεις</summary><ul>" + r.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul></details></div>" : "";
    $("logbox").hidden = !r.log; $("log").textContent = r.log || "";
  }
  if (s.pdf_version && s.pdf_version !== lastPdf) {
    lastPdf = s.pdf_version;
    $("pdf").src = "/pdf?v=" + s.pdf_version + "#view=FitH";
    $("pdf").hidden = false; $("empty").hidden = true; $("pdfbtns").hidden = false;
  }
  // automatic compile: wait until the files stop changing for one poll
  if ($("auto").checked && !s.running && !noTex) {
    const done = r ? r.stamp : seenStamp;
    if (s.stamp === stableStamp && s.stamp !== done && seenStamp !== null) compile(false);
    stableStamp = s.stamp;
  }
  if (seenStamp === null) seenStamp = s.stamp;
}
function fmt(x) { return String(x).replace(".", ","); }
function summarize(steps) {
  const out = []; steps.forEach((x) => { const l = out[out.length - 1]; if (l && l[0] === x) l[1]++; else out.push([x, 1]); });
  return out.map((p) => p[0] + (p[1] > 1 ? " ×" + p[1] : "")).join(", ");
}
async function poll() {
  try { draw(await api("/api/state")); }
  catch (e) { $("offline").style.display = "block"; }
  setTimeout(poll, 1200);
}
poll();
</script></body></html>"""


def make_handler(comp, token, port):
    allowed_hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _host_ok(self):
            return self.headers.get("Host", "") in allowed_hosts

        def _api_ok(self):
            return self._host_ok() and self.headers.get("X-Token") == token

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/":
                page = PAGE.replace("__TOKEN__", token).encode("utf-8")
                return self._send(200, page, "text/html; charset=utf-8",
                                  {"Content-Security-Policy": "default-src 'self'; "
                                   "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                   "frame-src 'self'; frame-ancestors 'none'"})
            if path == "/pdf":
                if not comp.pdf_bytes:
                    return self._send(404, "Δεν υπάρχει ακόμα PDF.".encode("utf-8"),
                                      "text/plain; charset=utf-8")
                return self._send(200, comp.pdf_bytes, "application/pdf",
                                  {"Content-Disposition": 'inline; filename="%s.pdf"' % comp.base})
            if path == "/pdf-bw":
                f = comp.path(comp.bw_job + ".pdf")
                if not os.path.isfile(f):
                    return self._send(404, "Δεν υπάρχει ακόμα ασπρόμαυρο PDF.".encode("utf-8"),
                                      "text/plain; charset=utf-8")
                with open(f, "rb") as fh:
                    return self._send(200, fh.read(), "application/pdf",
                                      {"Content-Disposition": 'inline; filename="%s.pdf"' % comp.bw_job})
            if path == "/api/state":
                if not self._api_ok():
                    return self._json({"error": "forbidden"}, 403)
                return self._json(comp.state())
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._api_ok():
                return self._json({"error": "forbidden"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 10000)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                data = {}
            if urlparse(self.path).path == "/api/stop":
                comp.stop()
                return self._json(comp.state())
            if urlparse(self.path).path == "/api/compile":
                engine = data.get("engine") if data.get("engine") in ENGINE_NAMES else "xelatex"
                comp.compile(engine, bool(data.get("clean")), bool(data.get("bw")))
                return self._json(comp.state())
            return self._json({"error": "not found"}, 404)

    return Handler


def serve(comp, port, open_browser):
    token = secrets.token_urlsafe(24)
    server = None
    for p in range(port, port + 20):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), make_handler(comp, token, p))
            port = p
            break
        except OSError:
            continue
    if server is None:
        sys.exit("Δεν βρέθηκε ελεύθερη θύρα από %d έως %d." % (port, port + 19))
    url = "http://127.0.0.1:%d/" % port
    print("Offline compiler: %s" % url)
    print("Φάκελος: %s" % comp.root)
    tex = comp.tex
    if tex["engines"]:
        print("TeX: %s (%s)" % (tex["distribution"] or "βρέθηκε",
                                ", ".join(ENGINE_NAMES[e] for e in sorted(tex["engines"]))))
    else:
        print("TeX: δεν βρέθηκε. Η σελίδα λέει τι να εγκαταστήσεις.")
    print("Για να σταματήσει: κλείσε αυτό το παράθυρο ή πάτα Ctrl+C.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nΣταμάτησε.")


def main():
    ap = argparse.ArgumentParser(description="Offline compiler για το πρότυπο διπλωματικής ΣΗΜΜΥ ΕΜΠ.")
    ap.add_argument("--main", default=None, help="κύριο αρχείο .tex (προεπιλογή: main.tex)")
    ap.add_argument("--engine", default="xelatex", choices=list(ENGINE_NAMES),
                    help="μηχανή για το --once (προεπιλογή: xelatex)")
    ap.add_argument("--once", action="store_true", help="ένα compile χωρίς σελίδα")
    ap.add_argument("--clean", action="store_true", help="με το --once: σβήνει πρώτα τα βοηθητικά αρχεία")
    ap.add_argument("--bw", action="store_true", help="με το --once: ασπρόμαυρο PDF (main-bw.pdf)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="να μην ανοίξει ο browser")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    main_tex = args.main or os.path.join(here, "main.tex")
    if not os.path.isabs(main_tex) and args.main:
        main_tex = os.path.abspath(main_tex)
    if not os.path.isfile(main_tex):
        sys.exit("Δεν βρέθηκε το %s. Βάλε το compile.py στον φάκελο του προτύπου, δίπλα στο "
                 "main.tex, ή δώσε --main ΑΡΧΕΙΟ.tex." % main_tex)
    comp = Compiler(main_tex)

    if args.once:
        r = comp.compile_sync(args.engine, args.clean, args.bw)
        steps = ", ".join(r["steps"])
        if r["ok"]:
            out = comp.bw_job if args.bw else comp.base
            print("OK σε %s s (%s): %s" % (r["seconds"], steps, comp.path(out + ".pdf")))
            for w in r["warnings"][:10]:
                print("  προειδοποίηση: " + w)
            return 0
        print("ΣΦΑΛΜΑ (%s):" % steps)
        for e in r["errors"]:
            where = ("%s:%s: " % (e["file"], e["line"])) if e.get("file") else ""
            print("  " + where + e["message"])
            if e.get("context"):
                print("      " + e["context"])
            if e.get("hint"):
                print("      → " + e["hint"])
        return 1

    serve(comp, args.port, not args.no_browser)
    return 0


def _pause_on_windows():
    if sys.platform == "win32":
        try:
            input("\nΠάτα Enter για να κλείσει το παράθυρο.")
        except Exception:
            pass


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        code = 0
    except SystemExit as e:
        code = e.code
        if isinstance(code, str):
            print(code, file=sys.stderr)
            _pause_on_windows()
            code = 1
    except Exception:
        import traceback
        traceback.print_exc()
        _pause_on_windows()
        code = 1
    sys.exit(code)
