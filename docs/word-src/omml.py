#!/usr/bin/env python3
"""Take the Word equations (OMML) that pandoc made from equations.md.
usage: omml.py equations.docx omml.json"""
import json, re, sys, zipfile
x = zipfile.ZipFile(sys.argv[1]).read("word/document.xml").decode("utf-8")
paras = re.findall(r"<m:oMathPara>.*?</m:oMathPara>", x, re.S)
json.dump(paras, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
print(len(paras), "equations")
