#!/bin/sh
# Rebuilds docs/thesis-template.docx (the Word template).
# Needs: Node.js with the "docx" package (npm install docx), pandoc,
# Python 3 with Pillow and lxml, and pdftoppm (poppler-utils).
set -e
cd "$(dirname "$0")"
mkdir -p assets
pdftoppm -r 300 -png -singlefile ../../logo/pyrforos.pdf assets/logo
python3 placeholder.py assets/placeholder.png
pandoc equations.md -o equations.docx
python3 omml.py equations.docx omml.json
node build.js
python3 post.py raw.docx omml.json ../thesis-template.docx
rm -rf raw.docx equations.docx omml.json assets
