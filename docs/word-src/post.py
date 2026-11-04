#!/usr/bin/env python3
"""Finish the template that build.js wrote:
- put the Word equations (OMML, from pandoc) in place of the @@EQn@@ markers;
- tie the numbering to the heading styles and to "Βιβλιογραφία IEEE", so a
  heading or reference the student adds later is numbered too;
- keep "Τίτλος χωρίς αρίθμηση" unnumbered although it is based on Heading 1.
usage: post.py raw.docx omml.json out.docx
"""
import json, re, shutil, sys, zipfile
from lxml import etree

raw, omml_json, out = sys.argv[1:4]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}
q = lambda tag: "{%s}%s" % (W, tag)

z = zipfile.ZipFile(raw)
files = {n: z.read(n) for n in z.namelist()}

# ---------------------------------------------------------------- equations
doc = files["word/document.xml"].decode("utf-8")
omml = json.load(open(omml_json, encoding="utf-8"))
def schema_order(para):
    # pandoc writes these children in an order the OOXML schema does not allow
    def dpr(m):
        parts = dict(re.findall(r"<m:(begChr|sepChr|endChr|grow|shp|ctrlPr)\b([^>]*/>)", m.group(1)))
        return "<m:dPr>" + "".join("<m:%s%s" % (k, parts[k]) for k in
                                   ("begChr", "sepChr", "endChr", "grow", "shp", "ctrlPr") if k in parts) + "</m:dPr>"
    para = re.sub(r"<m:dPr>(.*?)</m:dPr>", dpr, para, flags=re.S)
    # an empty separator only matters between several elements; some readers
    # (LibreOffice) draw it in place of the brackets
    para = re.sub(r'<m:sepChr m:val="" ?/>', "", para)
    para = re.sub(r"<m:mcPr>(<m:mcJc[^>]*/>)(<m:count[^>]*/>)</m:mcPr>", r"<m:mcPr>\2\1</m:mcPr>", para)
    return para

for k, para in enumerate(omml):
    para = schema_order(para)
    para = re.sub(r"<m:oMathPara>", '<m:oMathPara xmlns:m="%s">' % M, para, count=1)
    pat = re.compile(r"<w:r>(?:(?!<w:r>).)*?@@EQ%d@@.*?</w:r>" % k, re.S)
    doc, n = pat.subn(lambda _m: para, doc, count=1)
    assert n == 1, "equation %d not placed" % k
assert "@@EQ" not in doc
doc = re.sub(r"<w:highlightCs [^>]*/>", "", doc)      # not in the schema Word validates against
files["word/document.xml"] = doc.encode("utf-8")

# ---------------------------------------------------------------- numbering
num = etree.fromstring(files["word/numbering.xml"])
def abstract_with(text):
    for a in num.findall("w:abstractNum", NS):
        if a.find("w:lvl/w:lvlText", NS).get(q("val")) == text:
            return a
    raise SystemExit("no numbering with " + text)
def num_id_for(abstract):
    aid = abstract.get(q("abstractNumId"))
    for n in num.findall("w:num", NS):
        if n.find("w:abstractNumId", NS).get(q("val")) == aid:
            return n.get(q("numId"))
    raise SystemExit("no num for abstract " + aid)

LVL_ORDER = ["start", "numFmt", "lvlRestart", "pStyle", "isLgl", "suff", "lvlText",
             "lvlPicBulletId", "legacy", "lvlJc", "pPr", "rPr"]
def put_in_order(parent, child, order):
    name = etree.QName(child).localname
    after = order[:order.index(name)]
    pos = 0
    for k, c in enumerate(parent):
        if etree.QName(c).localname in after:
            pos = k + 1
    parent.insert(pos, child)

headings = abstract_with("%1")
for lvl, style in zip(headings.findall("w:lvl", NS), ["Heading1", "Heading2", "Heading3"]):
    ps = etree.Element(q("pStyle")); ps.set(q("val"), style)
    put_in_order(lvl, ps, LVL_ORDER)
ieee = abstract_with("[%1]")
lvl0 = ieee.find("w:lvl", NS)
ps = etree.Element(q("pStyle")); ps.set(q("val"), "BibIEEE")
put_in_order(lvl0, ps, LVL_ORDER)
files["word/numbering.xml"] = etree.tostring(num, xml_declaration=True, encoding="UTF-8", standalone=True)
heading_num, ieee_num = num_id_for(headings), num_id_for(ieee)

# ---------------------------------------------------------------- styles
PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
             "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
             "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
             "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
             "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
             "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"]
STYLE_ORDER = ["name", "aliases", "basedOn", "next", "link", "autoRedefine", "hidden", "uiPriority",
               "semiHidden", "unhideWhenUsed", "qFormat", "locked", "personal", "personalCompose",
               "personalReply", "rsid", "pPr", "rPr", "tblPr", "trPr", "tcPr", "tblStylePr"]
sty = etree.fromstring(files["word/styles.xml"])
def style(sid):
    s = sty.find("w:style[@w:styleId='%s']" % sid, NS)
    assert s is not None, sid
    return s
def ppr(s):
    p = s.find("w:pPr", NS)
    if p is None:
        p = etree.Element(q("pPr")); put_in_order(s, p, STYLE_ORDER)
    return p
def set_numpr(sid, numid, ilvl):
    p = ppr(style(sid))
    old = p.find("w:numPr", NS)
    if old is not None:
        p.remove(old)
    n = etree.Element(q("numPr"))
    if ilvl is not None:
        il = etree.SubElement(n, q("ilvl")); il.set(q("val"), str(ilvl))
    ni = etree.SubElement(n, q("numId")); ni.set(q("val"), str(numid))
    put_in_order(p, n, PPR_ORDER)
for k, sid in enumerate(["Heading1", "Heading2", "Heading3"]):
    set_numpr(sid, heading_num, k)
set_numpr("BibIEEE", ieee_num, 0)
for sid in ["UnnumberedHeading", "AppendixHeading"]:
    set_numpr(sid, 0, 0)                       # numId 0: no numbering
    p = ppr(style(sid))
    ind = p.find("w:ind", NS)
    if ind is not None:
        p.remove(ind)
    ind = etree.Element(q("ind")); ind.set(q("left"), "0"); ind.set(q("firstLine"), "0")
    put_in_order(p, ind, PPR_ORDER)
# Greek names in the styles gallery for the built-in styles stay as Word shows them
files["word/styles.xml"] = etree.tostring(sty, xml_declaration=True, encoding="UTF-8", standalone=True)

# the heading paragraphs no longer need their own numbering
d = etree.fromstring(files["word/document.xml"])
for p in d.iter(q("p")):
    pp = p.find("w:pPr", NS)
    if pp is None:
        continue
    st = pp.find("w:pStyle", NS)
    if st is not None and st.get(q("val")) in ("Heading1", "Heading2", "Heading3", "BibIEEE"):
        n = pp.find("w:numPr", NS)
        if n is not None:
            pp.remove(n)
# bookmark ids must be unique (docx-js gives them all the same id)
open_ids, next_id = [], 100
for el in d.iter(q("bookmarkStart"), q("bookmarkEnd")):
    if el.tag == q("bookmarkStart"):
        el.set(q("id"), str(next_id)); open_ids.append(next_id); next_id += 1
    else:
        el.set(q("id"), str(open_ids.pop()))
assert not open_ids
files["word/document.xml"] = etree.tostring(d, xml_declaration=True, encoding="UTF-8", standalone=True)

# no "Un-named" author in the file's properties
files["docProps/core.xml"] = re.sub(rb"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", b"", files["docProps/core.xml"])

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as o:
    for n in z.namelist():
        o.writestr(n, files[n])
print("wrote", out, "| heading numId", heading_num, "| ieee numId", ieee_num, "|", len(omml), "equations")
