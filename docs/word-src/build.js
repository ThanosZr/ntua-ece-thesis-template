// Word thesis template for the School of ECE, NTUA.
// Equations are injected afterwards (post.py) as Word equations (OMML).
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  AlignmentType, WidthType, BorderStyle, LevelFormat, TableOfContents, StyleLevel,
  Footer, PageNumber, SimpleField, Bookmark, HeadingLevel, ShadingType,
  VerticalAlign, TableLayoutType, SectionType, LineRuleType,
} = require("docx");

const A = (f) => path.join(__dirname, "assets", f);
const FONT = "Times New Roman";
const cm = (x) => Math.round(x * 567); // DXA
const TEXT_W = 11906 - cm(3) - cm(2.5);  // A4 width minus left/right margins

// ---------------------------------------------------------------- helpers
const t = (text, o = {}) => new TextRun({ text, ...o });
const b = (text, o = {}) => new TextRun({ text, bold: true, ...o });
const i = (text, o = {}) => new TextRun({ text, italics: true, ...o });
const ph = (text, o = {}) => new TextRun({ text, highlight: "yellow", ...o });   // field to fill in
const sub = (text, o = {}) => new TextRun({ text, subScript: true, ...o });
const sup = (text, o = {}) => new TextRun({ text, superScript: true, ...o });
const kids = (x) => (typeof x === "string" ? [t(x)] : x);

const P = (x, o = {}) => new Paragraph({ children: kids(x), ...o });
const S = (style, x, o = {}) => new Paragraph({ style, children: kids(x), ...o });
// (post.py moves the numbering into the heading styles, so a new heading is numbered too)
const H1 = (x) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: kids(x), numbering: { reference: "headings", level: 0 } });
const H2 = (x) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: kids(x), numbering: { reference: "headings", level: 1 } });
const H3 = (x) => new Paragraph({ heading: HeadingLevel.HEADING_3, children: kids(x), numbering: { reference: "headings", level: 2 } });
const front = (x) => S("FrontTitle", x);
const unnumbered = (x) => S("UnnumberedHeading", x);

// Instructions to the student: one style, so all of them can be removed at once
const note = (...lines) => lines.map((l, k) =>
  S("Odigia", k === 0 && typeof l === "string" ? [b("Οδηγία. "), t(l)] : kids(l)));
const bullet = (x) => new Paragraph({ children: kids(x), numbering: { reference: "bullets", level: 0 } });
const numbered = (x) => new Paragraph({ children: kids(x), numbering: { reference: "numbers", level: 0 } });

const noBorders = {
  top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  insideHorizontal: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};
const noCellBorders = {
  top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};
const cell = (children, width, o = {}) => new TableCell({
  children, width: { size: width, type: WidthType.DXA }, borders: noCellBorders,
  margins: { top: 40, bottom: 40, left: 80, right: 80 }, ...o,
});

// ---- caption numbers: { STYLEREF 1 \s }.{ SEQ <label> \* ARABIC \s 1 }
// Cached results are filled in so the document reads right before F9.
const num = (label, chapter, n) => [
  new SimpleField("STYLEREF 1 \\s", String(chapter)),
  t("."),
  new SimpleField(`SEQ ${label} \\* ARABIC \\s 1`, String(n)),
];
const figure = (img, w, h, chapter, n, caption, bookmark) => [
  S("FigureImage", [new ImageRun({ type: "png", data: fs.readFileSync(img), transformation: { width: w, height: h } })]),
  S("FigureCaption", [
    ...(bookmark ? [new Bookmark({ id: bookmark, children: [t("Σχήμα "), ...num("Σχήμα", chapter, n)] })]
                 : [t("Σχήμα "), ...num("Σχήμα", chapter, n)]),
    t(": "), ...kids(caption)]),
];
const tableCaption = (chapter, n, caption, bookmark) => S("TableCaption", [
  ...(bookmark ? [new Bookmark({ id: bookmark, children: [t("Πίνακας "), ...num("Πίνακας", chapter, n)] })]
               : [t("Πίνακας "), ...num("Πίνακας", chapter, n)]),
  t(": "), ...kids(caption)]);

// ---- equations: a borderless 1×3 table, equation centred, number on the right
let eqCount = 0;
const equation = (chapter, n, bookmark) => {
  const k = eqCount++;
  const number = [t("("), ...num("Εξίσωση", chapter, n), t(")")];
  const w1 = Math.round(TEXT_W * 0.1), w3 = Math.round(TEXT_W * 0.1), w2 = TEXT_W - w1 - w3;
  return new Table({
    width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: [w1, w2, w3],
    borders: noBorders, layout: TableLayoutType.FIXED,
    rows: [new TableRow({ cantSplit: true, children: [
      cell([S("Equation", [])], w1, { verticalAlign: VerticalAlign.CENTER }),
      cell([S("Equation", [t(`@@EQ${k}@@`)])], w2, { verticalAlign: VerticalAlign.CENTER }),
      cell([S("EquationNumber", bookmark ? [new Bookmark({ id: bookmark, children: number })] : number)], w3,
           { verticalAlign: VerticalAlign.CENTER }),
    ] })],
  });
};
const ref = (bookmark, cached) => new SimpleField(`REF ${bookmark} \\h`, cached);

// ---- IEEE-style data table: three rules, header row repeated on new pages
const rule = (sz) => ({ style: BorderStyle.SINGLE, size: sz, color: "000000" });
const dataTable = (widths, header, rows) => {
  const total = widths.reduce((a, c) => a + c, 0);
  const mk = (cells, isHeader, isLast) => new TableRow({
    tableHeader: isHeader, cantSplit: true,
    children: cells.map((c, k) => new TableCell({
      width: { size: widths[k], type: WidthType.DXA },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      borders: {
        top: isHeader ? rule(12) : { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
        bottom: isHeader ? rule(6) : (isLast ? rule(12) : { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }),
        left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
        right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      },
      children: [S(isHeader ? "TableHeading" : "TableText", kids(c))],
    })),
  });
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths, alignment: AlignmentType.CENTER,
    rows: [mk(header, true, false), ...rows.map((r, k) => mk(r, false, k === rows.length - 1))],
  });
};

// ---- the institution block of the cover and title page
const logo = () => new ImageRun({ type: "png", data: fs.readFileSync(A("logo.png")), transformation: { width: 92, height: 92 } });
const institution = () => {
  const w1 = cm(2.9), w2 = TEXT_W - w1;
  return new Table({
    width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: [w1, w2], borders: noBorders,
    rows: [new TableRow({ children: [
      cell([S("Cover", [logo()], { alignment: AlignmentType.LEFT })], w1, { verticalAlign: VerticalAlign.CENTER }),
      cell([
        S("Cover", [b("ΕΘΝΙΚΟ ΜΕΤΣΟΒΙΟ ΠΟΛΥΤΕΧΝΕΙΟ", { size: 26 })], { alignment: AlignmentType.LEFT }),
        S("Cover", "Σχολή Ηλεκτρολόγων Μηχανικών", { alignment: AlignmentType.LEFT }),
        S("Cover", "και Μηχανικών Υπολογιστών", { alignment: AlignmentType.LEFT }),
        S("Cover", [t("Τομέας "), ph("[Όνομα Τομέα]")], { alignment: AlignmentType.LEFT }),
      ], w2, { verticalAlign: VerticalAlign.CENTER }),
    ] })],
  });
};
const titleBlock = () => [
  S("Cover", [b("[Τίτλος της Διπλωματικής Εργασίας]", { size: 32, highlight: "yellow" })], { spacing: { before: cm(3.2) } }),
  S("Cover", [t("ΔΙΠΛΩΜΑΤΙΚΗ ΕΡΓΑΣΙΑ", { size: 28 })], { spacing: { before: cm(1.8) } }),
  S("Cover", [ph("[Ονοματεπώνυμο φοιτητή/φοιτήτριας]", { size: 26 })], { spacing: { before: cm(0.8) } }),
];
const supervisor = (before) => [
  S("Cover", [b("Επιβλέπων/Επιβλέπουσα: "), ph("[Ονοματεπώνυμο]")], { alignment: AlignmentType.LEFT, spacing: { before } }),
  S("Cover", [ph("[Βαθμίδα, π.χ. Καθηγητής Ε.Μ.Π.]")], { alignment: AlignmentType.LEFT, indent: { left: cm(4.1) } }),
];

// ------------------------------------------------------------- the pages
const cover = [
  institution(),
  ...titleBlock(),
  ...supervisor(cm(3.2)),
  S("Cover", [t("Αθήνα, "), ph("[Μήνας Έτος]")], { spacing: { before: cm(4.4) } }),
];

const signatures = () => {
  const w = Math.floor(TEXT_W / 3);
  const one = (who) => cell([
    S("CoverSmall", "......................................"),
    S("CoverSmall", [ph(`[Ονοματεπώνυμο ${who}]`)]),
    S("CoverSmall", [ph("[Βαθμίδα Ε.Μ.Π.]")]),
  ], w);
  return new Table({
    width: { size: w * 3, type: WidthType.DXA }, columnWidths: [w, w, w], borders: noBorders,
    rows: [new TableRow({ children: [one("επιβλέποντα"), one("μέλους"), one("μέλους")] })],
  });
};
const titlePage = [
  S("Cover", [], { pageBreakBefore: true, spacing: { before: 0, after: 0 } }),
  institution(),
  ...titleBlock(),
  ...supervisor(cm(2.2)),
  S("Cover", [t("Εγκρίθηκε από την τριμελή εξεταστική επιτροπή την "), ph("[1η Ιουλίου 2027]"), t(".")],
    { spacing: { before: cm(2.0), after: cm(1.4) } }),
  signatures(),
  S("Cover", [t("Αθήνα, "), ph("[Μήνας Έτος]")], { spacing: { before: cm(2.2) } }),
];

const copyright = [
  S("CopyrightText", "......................................", { pageBreakBefore: true, spacing: { before: cm(1) } }),
  S("CopyrightText", [ph("[Ονοματεπώνυμο]")]),
  S("CopyrightText", "Διπλωματούχος Ηλεκτρολόγος Μηχανικός και Μηχανικός Υπολογιστών Ε.Μ.Π."),
  S("CopyrightText", [t("Copyright © "), ph("[Ονοματεπώνυμο]"), t(", "), ph("[Έτος]"), t(".")], { spacing: { before: cm(4) } }),
  S("CopyrightText", "Με επιφύλαξη παντός δικαιώματος. All rights reserved.", { spacing: { after: 200 } }),
  S("CopyrightText", "Απαγορεύεται η αντιγραφή, αποθήκευση και διανομή της παρούσας εργασίας, εξ ολοκλήρου ή τμήματος αυτής, για εμπορικό σκοπό. Επιτρέπεται η ανατύπωση, αποθήκευση και διανομή για σκοπό μη κερδοσκοπικό, εκπαιδευτικής ή ερευνητικής φύσης, υπό την προϋπόθεση να αναφέρεται η πηγή προέλευσης και να διατηρείται το παρόν μήνυμα. Ερωτήματα που αφορούν τη χρήση της εργασίας για κερδοσκοπικό σκοπό πρέπει να απευθύνονται προς τον συγγραφέα.", { spacing: { after: 200 } }),
  S("CopyrightText", "Οι απόψεις και τα συμπεράσματα που περιέχονται σε αυτό το έγγραφο εκφράζουν τον συγγραφέα και δεν πρέπει να ερμηνευθεί ότι αντιπροσωπεύουν τις επίσημες θέσεις του Εθνικού Μετσόβιου Πολυτεχνείου."),
  ...note("Το κείμενο αυτής της σελίδας είναι το επίσημο κείμενο του προτύπου της βιβλιοθήκης της Σχολής: αλλάζετε μόνο τα κίτρινα πεδία. Στη γραμμή με τις τελείες υπογράφετε στο τυπωμένο αντίτυπο."),
];

const dedication = [
  S("Dedication", [ph("[Αφιέρωση, π.χ. «Στην οικογένειά μου.»]")], { pageBreakBefore: true }),
  ...note("Η αφιέρωση είναι προαιρετική. Αν δεν τη θέλετε, σβήστε αυτή τη σελίδα: τη θέση της παίρνει η Περίληψη (οδηγία του επίσημου προτύπου)."),
];

// --------------------------------------------- front matter (numbered pages)
const abstracts = [
  front("Περίληψη"),
  ...note("Έως μία σελίδα, όχι πάνω από 500 λέξεις (Οδηγός Συγγραφής της βιβλιοθήκης). Ακριβώς από κάτω οι λέξεις κλειδιά."),
  P([ph("[Κείμενο της περίληψης: το πρόβλημα, ο σκοπός, η μέθοδος, τα κύρια αποτελέσματα και τα συμπεράσματα, σε 1–4 παραγράφους.]")]),
  S("Keywords", [b("Λέξεις κλειδιά: "), ph("[λέξη 1, λέξη 2, λέξη 3, λέξη 4, λέξη 5]")]),
  front("Abstract"),
  ...note("Η περίληψη στα αγγλικά, στην αμέσως επόμενη σελίδα, με τις λέξεις κλειδιά στα αγγλικά."),
  P([ph("[Abstract in English.]")], { }),
  S("Keywords", [b("Keywords: "), ph("[keyword 1, keyword 2, keyword 3]")]),
  front("Ευχαριστίες"),
  ...note("Προαιρετικές. Αν τις παραλείψετε, σβήστε τη σελίδα."),
  P([ph("[Κείμενο ευχαριστιών.]")]),
];

const lists = [
  front("Περιεχόμενα"),
  new TableOfContents("Περιεχόμενα", { hyperlink: true, headingStyleRange: "1-3", hideTabAndPageNumbersInWebView: true, useAppliedParagraphOutlineLevel: true }),
  ...note("Οι κατάλογοι (περιεχόμενα, σχήματα, πίνακες) φτιάχνονται μόνοι τους από τα στυλ. Για να ενημερωθούν: Ctrl+A και F9 (ή δεξί κλικ → Ενημέρωση πεδίου → Ενημέρωση ολόκληρου του πίνακα). Αν το Word ρωτήσει στο άνοιγμα αν θα ενημερώσει τα πεδία, πατήστε Ναι."),
  front("Κατάλογος Σχημάτων"),
  new TableOfContents("Κατάλογος Σχημάτων", { hyperlink: true, hideTabAndPageNumbersInWebView: true, stylesWithLevels: [new StyleLevel("Λεζάντα σχήματος", 1)] }),
  ...note("Περιλαμβάνει κάθε παράγραφο με το στυλ «Λεζάντα σχήματος». Αν φτιάχνετε τον κατάλογο από την αρχή: Αναφορές → Εισαγωγή πίνακα εικόνων → Επιλογές → Δημιουργία από: Στυλ «Λεζάντα σχήματος»."),
  front("Κατάλογος Πινάκων"),
  new TableOfContents("Κατάλογος Πινάκων", { hyperlink: true, hideTabAndPageNumbersInWebView: true, stylesWithLevels: [new StyleLevel("Λεζάντα πίνακα", 1)] }),
  ...note("Το ίδιο, από το στυλ «Λεζάντα πίνακα». Ο Οδηγός Συγγραφής ζητά κατάλογο σχημάτων και πινάκων μετά τα περιεχόμενα."),
  front("Κατάλογος Συμβόλων και Συντομογραφιών"),
  ...note("Προαιρετικός, χρήσιμος όταν η εργασία έχει πολλά σύμβολα. Γράφετε τα σύμβολα όπως στις εξισώσεις (πλάγια τα μεγέθη) και τις μονάδες SI όρθιες."),
  dataTable([cm(2.6), cm(8.2), cm(3.4)], ["Σύμβολο", "Μέγεθος", "Μονάδα SI"], [
    [[i("u")], "στιγμιαία τιμή τάσης", "V"],
    [[i("I")], "ενεργός τιμή ρεύματος", "A"],
    [[i("f")], "συχνότητα", "Hz"],
    [[i("ω")], "κυκλική συχνότητα", "rad/s"],
    [[i("S", { underline: {} })], "μιγαδική φαινόμενη ισχύς", "V·A"],
    [[i("P"), t(", "), i("Q")], "ενεργός, άεργος ισχύς", "W, var"],
    [[ph("[…]")], [ph("[…]")], [ph("[…]")]],
  ]),
  S("TableText", ""),
  dataTable([cm(3.6), cm(10.6)], ["Συντομογραφία", "Πλήρης μορφή"], [
    ["Ε.Μ.Π.", "Εθνικό Μετσόβιο Πολυτεχνείο"],
    ["ΣΗΜΜΥ", "Σχολή Ηλεκτρολόγων Μηχανικών και Μηχανικών Υπολογιστών"],
    [[ph("[…]")], [ph("[…]")]],
  ]),
  unnumbered("Εκτενής Περίληψη"),
  ...note("Μόνο για εργασίες γραμμένες στα αγγλικά: το επίσημο αγγλικό πρότυπο της βιβλιοθήκης ζητά το κυρίως κείμενο να ξεκινά με εκτενή περίληψη στα ελληνικά. Σε ελληνική εργασία σβήστε αυτή την ενότητα."),
  P([ph("[Εκτενής περίληψη στα ελληνικά, μερικές σελίδες.]")]),
];

// ------------------------------------------------------------- chapter 1
const ch1 = [
  H1("Εισαγωγή"),
  ...note(
    "Πώς δουλεύει το πρότυπο. Τα κίτρινα [ ] είναι πεδία που συμπληρώνετε. Τα μπλε πλαίσια σαν αυτό είναι οδηγίες: σβήνονται όλα μαζί πριν το PDF (δεξί κλικ στο στυλ «Οδηγία» στη συλλογή στυλ → Επιλογή όλων των περιπτώσεων → Delete).",
    [b("Τα στυλ κάνουν όλη τη δουλειά. "), t("Δεν αλλάζετε γραμματοσειρές και αποστάσεις με το χέρι: διαλέγετε στυλ από Κεντρική → Στυλ (παράθυρο στυλ: Ctrl+Alt+Shift+S). Τα στυλ του προτύπου:")],
    [b("Κανονικό: "), t("το κείμενο (Times New Roman 12 στ., διάστιχο 1,5, πλήρης στοίχιση, λευκή αράδα 12 στ.).")],
    [b("Επικεφαλίδα 1, 2, 3: "), t("κεφάλαια και ενότητες, με αυτόματη αρίθμηση 1, 1.1, 1.1.1· από αυτά φτιάχνονται τα Περιεχόμενα.")],
    [b("Λεζάντα σχήματος / Λεζάντα πίνακα: "), t("όλες οι λεζάντες σχημάτων με το πρώτο, όλες των πινάκων με το δεύτερο· από αυτά φτιάχνονται οι δύο κατάλογοι.")],
    [b("Εικόνα σχήματος: "), t("η παράγραφος που κρατά την εικόνα (στο κέντρο, μένει με τη λεζάντα).")],
    [b("Εξίσωση / Αριθμός εξίσωσης: "), t("μέσα στον πίνακα κάθε εξίσωσης.")],
    [b("Κείμενο πίνακα / Επικεφαλίδα πίνακα: "), t("τα κελιά των πινάκων (11 στ., μονό διάστιχο).")],
    [b("Τίτλος προοιμίου: "), t("Περίληψη, Abstract, Ευχαριστίες, Περιεχόμενα, κατάλογοι· σε νέα σελίδα, εκτός περιεχομένων.")],
    [b("Τίτλος χωρίς αρίθμηση / Τίτλος παραρτήματος: "), t("Βιβλιογραφία και παραρτήματα· σε νέα σελίδα, μέσα στα περιεχόμενα.")],
    [b("Βιβλιογραφία IEEE / Βιβλιογραφία APA: "), t("οι εγγραφές της βιβλιογραφίας.")],
    [b("Οδηγία: "), t("αυτά τα πλαίσια· σβήνονται όλα μαζί.")],
    [b("Word ή LibreOffice. "), t("Το πρότυπο είναι για Microsoft Word 2016 ή νεότερο (Windows ή Mac). Ανοίγει και στο LibreOffice, αλλά εκεί η αρίθμηση ανά κεφάλαιο στις λεζάντες και στις εξισώσεις δεν βγαίνει σωστά.")],
    [b("Ρυθμίσεις σελίδας. "), t("A4· περιθώρια 2,5 cm πάνω και κάτω, 3 cm αριστερά (δέσιμο), 2,5 cm δεξιά. Ο Οδηγός Συγγραφής ζητά περιθώρια τουλάχιστον 2 cm και λίγο μεγαλύτερο από τη μεριά του δεσίματος· έξω από αυτά μπαίνει μόνο ο αριθμός σελίδας. Για εκτύπωση διπλής όψης (προτείνεται από τον οδηγό): Διάταξη → Περιθώρια → Προσαρμοσμένα περιθώρια → Πολλές σελίδες: Κατοπτρικά περιθώρια.")],
    [b("Αρίθμηση σελίδων. "), t("Συνεχής σε όλη την εργασία, με το εξώφυλλο ως σελίδα 1, κάτω στο κέντρο, όπως ζητά ο Οδηγός Συγγραφής. Οι τέσσερις πρώτες σελίδες μετρούν αλλά δεν δείχνουν αριθμό.")],
  ),
  H2("Αντικείμενο και σημασία του θέματος"),
  P([ph("[Κείμενο. Το στυλ «Κανονικό» είναι Times New Roman 12 στ., διάστιχο 1,5 γραμμή, πλήρης στοίχιση και κενό 12 στ. μετά από κάθε παράγραφο.]")]),
  ...note(
    [b("Παράγραφοι και λευκή αράδα. "), t("Η κενή γραμμή ανάμεσα στις παραγράφους (λευκή αράδα) βγαίνει από το στυλ, όχι με δεύτερο Enter: Κεντρική → Παράγραφος → Διάστημα Μετά: 12 στ. Ένα Enter στο τέλος κάθε παραγράφου, ποτέ δύο.")],
    [b("Διάστιχο. "), t("Παράγραφος → Διάστιχο: 1,5 γραμμή. Στους πίνακες, στις λεζάντες και στη βιβλιογραφία μονό διάστιχο (το έχουν ήδη τα στυλ τους).")],
    [b("Εσοχή αντί για λευκή αράδα. "), t("Αν προτιμάτε την εσοχή πρώτης γραμμής: τροποποιήστε το στυλ «Κανονικό» → Μορφή → Παράγραφος → Ειδική: Πρώτη γραμμή 0,5 cm και Διάστημα Μετά: 0 στ. Ένα από τα δύο σε όλη την εργασία, όχι και τα δύο.")],
    [b("Χήρες και ορφανές. "), t("Είναι ενεργό το «Έλεγχος χήρων/ορφανών γραμμών», ώστε να μη μένει μία γραμμή παραγράφου μόνη της στην αρχή ή στο τέλος σελίδας. Οι επικεφαλίδες έχουν «Διατήρηση με την επόμενη».")],
  ),
  H2("Σκοπός και στόχοι της διπλωματικής εργασίας"),
  P([ph("[Κείμενο. Ο σκοπός και οι επιμέρους στόχοι, π.χ.:]")]),
  bullet([ph("[στόχος 1]")]),
  bullet([ph("[στόχος 2]")]),
  bullet([ph("[στόχος 3]")]),
  ...note("Λίστες: Κεντρική → Κουκκίδες ή Αρίθμηση. Οι λίστες του προτύπου έχουν ήδη εσοχή και μονό διάστιχο ανάμεσα στα στοιχεία."),
  H2("Μεθοδολογία και εργαλεία"),
  P([ph("[Κείμενο: η μέθοδος, τα λογισμικά, τα δεδομένα.]")]),
  H2("Δομή της εργασίας"),
  P([ph("[Κείμενο: ένα-δυο προτάσεις για κάθε κεφάλαιο.]")]),
  ...note(
    [b("Κεφάλαια και ενότητες. "), t("Νέο κεφάλαιο: γράψτε τον τίτλο και διαλέξτε «Επικεφαλίδα 1». Ξεκινά μόνο του σε νέα σελίδα και παίρνει τον επόμενο αριθμό, όπως και οι λεζάντες και οι εξισώσεις του. Ενότητες: «Επικεφαλίδα 2» και «Επικεφαλίδα 3». Τρία επίπεδα φτάνουν· για περισσότερα, χωρίστε το κεφάλαιο.")],
  ),
];

// ------------------------------------------------------------- chapter 2
const ch2 = [
  H1([ph("[Θεωρητικό υπόβαθρο]")]),
  P([ph("[Εισαγωγικό κείμενο του κεφαλαίου.]")]),
  H2("Εξισώσεις"),
  ...note(
    [b("Πώς μπαίνει μια εξίσωση. "), t("Κάθε αριθμημένη εξίσωση είναι ένας πίνακας μίας γραμμής και τριών στηλών χωρίς περιγράμματα (10 % – 80 % – 10 % του πλάτους): στη μεσαία στήλη η εξίσωση στο κέντρο, στη δεξιά ο αριθμός. Έτσι η στοίχιση μένει σωστή σε κάθε υπολογιστή και στο PDF. Ο πιο γρήγορος τρόπος: αντιγράψτε έναν από τους πίνακες εξισώσεων αυτού του κεφαλαίου, κάντε κλικ στην εξίσωση και γράψτε τη δική σας. Ο αριθμός ενημερώνεται μόνος του με F9.")],
    [b("Εξίσωση από την αρχή. "), t("Εισαγωγή → Εξίσωση (Alt+=) μέσα στη μεσαία στήλη. Μπορείτε να γράφετε και σε LaTeX: καρτέλα Εξίσωση → LaTeX. Στο Word 365 υπάρχει και το #: γράψτε στο τέλος της εξίσωσης #(2.1) και Enter, και ο αριθμός μπαίνει δεξιά· όμως ο πίνακας κρατά τη στοίχιση και σε παλαιότερες εκδόσεις και στο LibreOffice.")],
    [b("Αρίθμηση κατά IEEE. "), t("Αριθμός ανά κεφάλαιο σε παρενθέσεις, στοιχισμένος δεξιά: (2.1), (2.2)… Στο κείμενο: «από την (2.1)» ή «η εξίσωση (2.1)», με Αναφορές → Παραπομπή → Σελιδοδείκτης, ώστε να ενημερώνεται. Η εξίσωση είναι μέρος της πρότασης: μετά από αυτήν μπαίνει κόμμα ή τελεία, και το «όπου» που εξηγεί τα σύμβολα ξεκινά χωρίς εσοχή.")],
    [b("ISO 80000-2: πλάγια ή όρθια. "), t("Πλάγια: τα μεγέθη και οι μεταβλητές (u, I, t, ω, R) και οι δείκτες που είναι μεταβλητές (Iₖ με k = 1, 2, …). Όρθια: οι αριθμοί· οι μονάδες (V, Hz)· οι σταθερές e, π και η φανταστική μονάδα j· το διαφορικό d· οι συναρτήσεις sin, cos, ln, exp· οι περιγραφικοί δείκτες (u_L για «πηνίο», P_loss για «απώλειες»). Έντονα πλάγια τα διανύσματα και οι πίνακες. Οι μιγαδικές ποσότητες (φάσορες) υπογραμμίζονται, π.χ. S = U I*.")],
    [b("Όρθιο στο Word. "), t("Επιλέξτε το σύμβολο μέσα στην εξίσωση και πατήστε «Κανονικό κείμενο» στην καρτέλα Εξίσωση. Τα sin, cos, ln γίνονται όρθια μόνα τους όταν τα γράφετε με ανάποδη κάθετο: \\sin, \\ln.")],
  ),
  P([t("Η στιγμιαία τιμή μιας ημιτονικής τάσης γράφεται")]),
  equation(2, 1, "eq_u"),
  P([t("όπου "), i("Û"), t(" το πλάτος, "), i("ω"), t(" η κυκλική συχνότητα, "), i("f"), t(" η συχνότητα και "), i("φ"), sub("u"), t(" η αρχική φάση. Με φάσορες, η μιγαδική ισχύς είναι")]),
  equation(2, 2),
  P([t("όπου το j είναι όρθιο, ως φανταστική μονάδα. Παραδείγματα για παράγωγο, ολοκλήρωμα και άθροισμα, με όρθιο d και περιγραφικούς δείκτες όρθιους:")]),
  equation(2, 3),
  equation(2, 4),
  equation(2, 5),
  P([t("Πίνακες με έντονα πλάγια σύμβολα, και εξίσωση σε δύο γραμμές στοιχισμένες στο «=»:")]),
  equation(2, 6),
  equation(2, 7),
  ...note("Εξίσωση σε πολλές γραμμές: μέσα στην εξίσωση Shift+Enter για νέα γραμμή, και δεξί κλικ → Στοίχιση σε = ώστε να στοιχίζονται στο ίσον. Πολλές μικρές εξισώσεις στην ίδια γραμμή χωρίζονται με κόμμα και κενό (δείτε την (2.9))."),
  P([t("Εκθετική συνάρτηση με όρθιο e, ρίζες και κλάσματα, και συνάρτηση με κλάδους:")]),
  equation(2, 8),
  equation(2, 9),
  equation(2, 10),
  H2("Μεγέθη, αριθμοί και μονάδες"),
  P([t("Ο "), ref("tab_iso", "Πίνακας 2.1"), t(" συνοψίζει τους κανόνες του ISO 80000-1 για τη γραφή μεγεθών, αριθμών και μονάδων στο κείμενο, στους πίνακες και στα σχήματα.")]),
  tableCaption(2, 1, "Γραφή μεγεθών, αριθμών και μονάδων κατά ISO 80000-1", "tab_iso"),
  dataTable([cm(3.4), cm(3.6), cm(7.2)], ["Σωστά", "Λάθος", "Κανόνας"], [
    [[i("f"), t(" = 50 Hz")], [i("f"), t(" = 50Hz, "), i("f"), t(" = 50 [Hz]")], "Κενό ανάμεσα σε αριθμό και μονάδα (μη διακοπτόμενο: Ctrl+Shift+Space)· η μονάδα χωρίς αγκύλες."],
    [[i("U"), t(" = 20 kV")], [i("U"), t(" = 20 KV")], "Πρόθεμα και μονάδα όπως ορίζονται: k πεζό, V κεφαλαίο."],
    [[i("R"), t(" = 4,7 kΩ")], [i("R"), t(" = 4.7 kOhm")], "Στα ελληνικά υποδιαστολή το κόμμα· σύμβολο Ω, όχι λέξη."],
    ["20 000 V", "20.000 V", "Ψηφία σε ομάδες των τριών με κενό, όχι με τελεία."],
    [[i("E"), t(" σε V/m")], [i("E"), t(" [V/m]")], "Η μονάδα ενός μεγέθους δεν γράφεται σε αγκύλες."],
    [[i("t"), t(" / ms")], [i("t"), t(" [ms]")], "Άξονες σχημάτων και επικεφαλίδες στηλών: μέγεθος / μονάδα."],
    ["5 %", "5%", "Το % γράφεται σαν μονάδα, με κενό."],
    [[i("u"), sub("max")], [i("u"), sub("max", { italics: true })], "Περιγραφικός δείκτης όρθιος· δείκτης που είναι μεταβλητή, πλάγιος (Iₖ)."],
    [[t("sin "), i("x"), t(", ln "), i("x")], [i("sin x, ln x")], "Οι συναρτήσεις όρθιες, η μεταβλητή πλάγια."],
  ]),
  P([ph("[Κείμενο.]")], { spacing: { before: 240 } }),
];

// ------------------------------------------------------------- chapter 3
const ch3 = [
  H1([ph("[Περιγραφή και μοντελοποίηση του υπό μελέτη συστήματος]")]),
  P([ph("[Εισαγωγικό κείμενο του κεφαλαίου.]")]),
  H2("Σχήματα"),
  ...note(
    [b("Σχήμα. "), t("Εισαγωγή → Εικόνες (ή επικόλληση), σε δική του παράγραφο με το στυλ «Εικόνα σχήματος» (κεντραρισμένη, μένει με τη λεζάντα), και διάταξη «Στη γραμμή με το κείμενο». Ανάλυση τουλάχιστον 300 dpi, ή διανυσματικό σχήμα (EMF, SVG). Χρώματα που ξεχωρίζουν και σε ασπρόμαυρη εκτύπωση (ο Οδηγός Συγγραφής ζητά διαφορετικά σύμβολα ή διαγραμμίσεις, γιατί οι φωτοτυπίες είναι ασπρόμαυρες). Στους άξονες: μέγεθος / μονάδα, π.χ. t / ms.")],
    [b("Λεζάντα σχήματος, κάτω από το σχήμα. "), t("Ο πιο γρήγορος τρόπος: αντιγράψτε τη λεζάντα του Σχήματος 3.1 κάτω από το νέο σχήμα και αλλάξτε μόνο το κείμενο· ο αριθμός διορθώνεται με F9. Από την αρχή: Αναφορές → Εισαγωγή λεζάντας → Ετικέτα: «Σχήμα» (αν λείπει: Νέα ετικέτα) → Αρίθμηση → Συμπερίληψη αριθμού κεφαλαίου (Επικεφαλίδα 1, διαχωριστικό τελεία) → OK, και μετά στυλ «Λεζάντα σχήματος». Όλες οι λεζάντες σχημάτων με αυτό το ένα στυλ: από αυτό φτιάχνεται ο Κατάλογος Σχημάτων.")],
    [b("Πηγή. "), t("Αν το σχήμα είναι από άλλη εργασία, η παραπομπή μπαίνει στο τέλος της λεζάντας, π.χ. [3], και χρειάζεται άδεια όταν ο κάτοχος το ζητά.")],
  ),
  ...figure(A("placeholder.png"), 450, 225, 3, 1, [ph("[Περιγραφή του σχήματος, μία πρόταση.]"), t(" "), ph("[n]")], "fig_1"),
  P([ph("[Κείμενο που σχολιάζει το σχήμα.]")]),
  ...figure(A("placeholder.png"), 450, 225, 3, 2, [ph("[Δεύτερο σχήμα: ο αριθμός 3.2 μπήκε μόνος του.]")]),
  H2("Πίνακες"),
  ...note(
    [b("Λεζάντα πίνακα, πάνω από τον πίνακα (IEEE). "), t("Όπως στα σχήματα, με ετικέτα «Πίνακας» και στυλ «Λεζάντα πίνακα», που μένει στην ίδια σελίδα με τον πίνακα. Από αυτό το στυλ φτιάχνεται ο Κατάλογος Πινάκων.")],
    [b("Μορφή πίνακα. "), t("Τρεις οριζόντιες γραμμές (πάνω, κάτω από τις επικεφαλίδες, κάτω), χωρίς κάθετες. Στυλ «Επικεφαλίδα πίνακα» και «Κείμενο πίνακα» (11 στ., μονό διάστιχο). Επικεφαλίδες με μέγεθος και μονάδα, π.χ. U / kV, ώστε στα κελιά να μένουν μόνο αριθμοί. Η γραμμή επικεφαλίδων επαναλαμβάνεται σε κάθε σελίδα (Διάταξη πίνακα → Επανάληψη γραμμών κεφαλίδας). Ο πιο γρήγορος τρόπος: αντιγράψτε τον Πίνακα 3.1 με τη λεζάντα του.")],
  ),
  tableCaption(3, 1, [ph("[Τίτλος του πίνακα]")], "tab_data"),
  dataTable([cm(5.2), cm(2.4), cm(3.0), cm(3.0)], ["Μέγεθος", "Σύμβολο", "Τιμή", "Μονάδα"], [
    [[ph("[Ονομαστική τάση]")], [i("U"), sub("n")], [ph("[20]")], "kV"],
    [[ph("[Συχνότητα]")], [i("f")], [ph("[50]")], "Hz"],
    [[ph("[Αντίσταση ανά μονάδα μήκους]")], [i("R"), t("′")], [ph("[0,05]")], "Ω/km"],
  ]),
  P([ph("[Κείμενο.]")], { spacing: { before: 240 } }),
];

// ------------------------------------------------------------- chapter 4
const ch4 = [
  H1([ph("[Αποτελέσματα]")]),
  P([ph("[Εισαγωγικό κείμενο του κεφαλαίου.]")]),
  H2("Παραπομπές μέσα στο κείμενο"),
  P([t("Όπως φαίνεται στο "), ref("fig_1", "Σχήμα 3.1"), t(" και στον "), ref("tab_data", "Πίνακας 3.1"), t(", "), ph("[…]"), t(". Από την "), ref("eq_u", "(2.1)"), t(" προκύπτει ότι "), ph("[…]"), t(".")]),
  ...note(
    [b("Παραπομπή σε σχήμα, πίνακα ή εξίσωση. "), t("Αναφορές → Παραπομπή → Τύπος αναφοράς: Σχήμα ή Πίνακας → Εισαγωγή αναφοράς σε: Μόνο ετικέτα και αριθμός. Για τις εξισώσεις, ο αριθμός κάθε εξίσωσης είναι σελιδοδείκτης (Εισαγωγή → Σελιδοδείκτης, π.χ. eq_u)· Τύπος αναφοράς: Σελιδοδείκτης. Οι παραπομπές ενημερώνονται με F9, αν αλλάξει η σειρά.")],
  ),
  H2("Βιβλιογραφικές παραπομπές"),
  P([t("Κατά IEEE, οι πηγές αριθμούνται με τη σειρά που εμφανίζονται: όπως δείχνει το [1], "), ph("[…]"), t(", ενώ τα [2]–[4] "), ph("[…]"), t(".")]),
  ...note(
    [b("IEEE ή APA. "), t("Ο Οδηγός Συγγραφής και το επίσημο πρότυπο δέχονται IEEE ή APA· ένα από τα δύο σε όλη την εργασία. IEEE: αριθμοί σε αγκύλες [1], [2]–[4], και βιβλιογραφία με αριθμητική σειρά. APA (7η έκδοση): (Επώνυμο, Έτος) ή Επώνυμο (Έτος) στο κείμενο, και βιβλιογραφία αλφαβητικά.")],
    [b("Εργαλεία. "), t("Αναφορές → Διαχείριση πηγών και Στυλ: IEEE ή APA → Εισαγωγή παραπομπής → Βιβλιογραφία· ή Zotero / Mendeley με το πρόσθετο του Word· ή γεννήτριες όπως το MyBib (IEEE, APA), που προτείνει η βιβλιοθήκη. Ό,τι κι αν χρησιμοποιήσετε, δώστε στη λίστα το στυλ «Βιβλιογραφία IEEE» ή «Βιβλιογραφία APA».")],
  ),
  H2([ph("[Ενότητα]")]),
  P([ph("[Κείμενο.]")]),
];

// ------------------------------------------------------------- chapter 5
const ch5 = [
  H1("Συμπεράσματα και μελλοντική έρευνα"),
  H2("Συμπεράσματα"),
  P([ph("[Κείμενο.]")]),
  H2("Μελλοντική έρευνα"),
  P([ph("[Κείμενο.]")]),
  ...note(
    [b("Πριν βγάλετε το PDF. ")],
    "1. Σβήστε όλες τις οδηγίες (στυλ «Οδηγία») και ελέγξτε ότι δεν έμεινε κίτρινο πεδίο (Κεντρική → Εύρεση → Σύνθετη εύρεση → Μορφή → Επισήμανση).",
    "2. Ctrl+A και F9, δύο φορές: ενημερώνονται αριθμοί, παραπομπές, περιεχόμενα και κατάλογοι.",
    "3. Ελέγξτε ότι κανένα σχήμα ή πίνακας δεν βγαίνει έξω από τα περιθώρια.",
    "4. Αρχείο → Αποθήκευση ως → PDF → Επιλογές: «Συμβατό με ISO 19005-1 (PDF/A)» και «Δημιουργία σελιδοδεικτών με χρήση: Επικεφαλίδων». Οι γραμματοσειρές ενσωματώνονται έτσι στο PDF.",
    "5. Ανοίξτε το PDF και κοιτάξτε κάθε σελίδα, ειδικά τις εξισώσεις και τους καταλόγους.",
  ),
];

// ------------------------------------------------------------- back matter
const ieee = (runs) => new Paragraph({ style: "BibIEEE", children: runs, numbering: { reference: "ieee", level: 0 } });
const back = [
  unnumbered("Βιβλιογραφία"),
  ...note("Παραδείγματα μορφής IEEE (IEEE Reference Guide), για να αντικατασταθούν. Τίτλοι περιοδικών, βιβλίων και συνεδρίων πλάγια· τα ηλεκτρονικά με ημερομηνία πρόσβασης. Η αρίθμηση [1], [2], … μπαίνει μόνη της από το στυλ «Βιβλιογραφία IEEE»."),
  ieee([t("A. Author, B. Author, and C. Author, “Title of article,” "), i("Abbrev. Title of Journal"), t(", vol. x, no. x, pp. xxx–xxx, Abbrev. Month Year, doi: xx.xxxx/xxxxx.")]),
  ieee([t("A. Author, “Title of paper,” in "), i("Abbrev. Name of Conf."), t(", City, Country, Year, pp. xxx–xxx.")]),
  ieee([t("A. Author, "), i("Title of Book"), t(", xth ed. City, Country: Publisher, Year.")]),
  ieee([i("Title of Standard"), t(", Standard number, Year.")]),
  ieee([t("Α. Επώνυμο, «Τίτλος διπλωματικής εργασίας», Διπλωματική εργασία, Σχολή Ηλεκτρολόγων Μηχανικών και Μηχανικών Υπολογιστών, Ε.Μ.Π., Αθήνα, Έτος.")]),
  ieee([t("Organization, “Title of page.” [Online]. Available: https://… [Accessed: Month Day, Year].")]),
  ...note(
    [b("Αν διαλέξετε APA. "), t("Στυλ «Βιβλιογραφία APA» (κρεμαστή εσοχή 1,27 cm, χωρίς αριθμούς), αλφαβητικά, π.χ.:")],
    "Author, A. A., & Author, B. B. (Year). Title of article. Title of Journal, volume(issue), pages. https://doi.org/xx.xxxx/xxxxx",
    "Author, A. A. (Year). Title of book (xth ed.). Publisher.",
  ),
  S("AppendixHeading", [t("Παράρτημα Α: "), ph("[Τίτλος]")]),
  ...note("Κάθε παράρτημα με το στυλ «Τίτλος χωρίς αρίθμηση» και γράμμα στον τίτλο: Παράρτημα Α, Β, Γ. Οι λεζάντες εδώ γράφονται με το χέρι (Σχήμα Α.1, Πίνακας Α.1) με τα ίδια στυλ λεζάντας, ώστε να μπαίνουν στους καταλόγους."),
  P([ph("[Κείμενο του παραρτήματος.]")]),
];

// ------------------------------------------------------------------ styles
const para = (o) => ({ ...o });
const styles = {
  default: {
    document: { run: { font: FONT, size: 24, language: { value: "el-GR" } } },
    heading1: { run: { font: FONT, size: 36, bold: true, color: "000000" },
                paragraph: { spacing: { before: 0, after: 480, line: 276, lineRule: LineRuleType.AUTO }, keepNext: true, keepLines: true, pageBreakBefore: true, alignment: AlignmentType.LEFT } },
    heading2: { run: { font: FONT, size: 28, bold: true, color: "000000" },
                paragraph: { spacing: { before: 360, after: 120, line: 276, lineRule: LineRuleType.AUTO }, keepNext: true, keepLines: true, alignment: AlignmentType.LEFT } },
    heading3: { run: { font: FONT, size: 24, bold: true, color: "000000" },
                paragraph: { spacing: { before: 240, after: 120, line: 276, lineRule: LineRuleType.AUTO }, keepNext: true, keepLines: true, alignment: AlignmentType.LEFT } },
  },
  paragraphStyles: [
    { id: "Normal", name: "Normal", run: { font: FONT, size: 24 },
      paragraph: { spacing: { before: 0, after: 240, line: 360, lineRule: LineRuleType.AUTO }, alignment: AlignmentType.JUSTIFIED, widowControl: true } },
    { id: "FrontTitle", name: "Τίτλος προοιμίου", basedOn: "Normal", next: "Normal", quickFormat: true,
      run: { font: FONT, size: 32, bold: true },
      paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 0, after: 480, line: 276, lineRule: LineRuleType.AUTO }, pageBreakBefore: true, keepNext: true } },
    { id: "UnnumberedHeading", name: "Τίτλος χωρίς αρίθμηση", basedOn: "Heading1", next: "Normal", quickFormat: true,
      run: { font: FONT, size: 36, bold: true }, paragraph: { outlineLevel: 0 } },
    { id: "AppendixHeading", name: "Τίτλος παραρτήματος", basedOn: "UnnumberedHeading", next: "Normal", quickFormat: true,
      run: { font: FONT, size: 36, bold: true }, paragraph: { outlineLevel: 0 } },
    { id: "FigureImage", name: "Εικόνα σχήματος", basedOn: "Normal", next: "FigureCaption", quickFormat: true,
      paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 120, line: 240, lineRule: LineRuleType.AUTO }, keepNext: true } },
    { id: "Caption", name: "caption", basedOn: "Normal", next: "Normal",
      run: { font: FONT, size: 22, bold: false, italics: false, color: "000000" },
      paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 120, after: 240, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "FigureCaption", name: "Λεζάντα σχήματος", basedOn: "Caption", next: "Normal", quickFormat: true,
      run: { font: FONT, size: 22 }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 0, after: 360, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "TableCaption", name: "Λεζάντα πίνακα", basedOn: "Caption", next: "Normal", quickFormat: true,
      run: { font: FONT, size: 22 }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 240, after: 120, line: 240, lineRule: LineRuleType.AUTO }, keepNext: true } },
    { id: "Equation", name: "Εξίσωση", basedOn: "Normal", next: "Normal", quickFormat: true,
      paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 60, after: 60, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "EquationNumber", name: "Αριθμός εξίσωσης", basedOn: "Normal", next: "Normal", quickFormat: true,
      paragraph: { alignment: AlignmentType.RIGHT, spacing: { before: 60, after: 60, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "TableText", name: "Κείμενο πίνακα", basedOn: "Normal", next: "TableText", quickFormat: true,
      run: { font: FONT, size: 22 }, paragraph: { alignment: AlignmentType.LEFT, spacing: { before: 0, after: 0, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "TableHeading", name: "Επικεφαλίδα πίνακα", basedOn: "TableText", next: "TableText", quickFormat: true,
      run: { font: FONT, size: 22, bold: true }, paragraph: { alignment: AlignmentType.LEFT, spacing: { before: 0, after: 0, line: 240, lineRule: LineRuleType.AUTO }, keepNext: true } },
    { id: "Keywords", name: "Λέξεις κλειδιά", basedOn: "Normal", next: "Normal", quickFormat: true,
      paragraph: { spacing: { before: 240, after: 240, line: 360, lineRule: LineRuleType.AUTO } } },
    { id: "BibIEEE", name: "Βιβλιογραφία IEEE", basedOn: "Normal", next: "BibIEEE", quickFormat: true,
      run: { font: FONT, size: 22 }, paragraph: { alignment: AlignmentType.LEFT, spacing: { before: 0, after: 120, line: 264, lineRule: LineRuleType.AUTO } } },
    { id: "BibAPA", name: "Βιβλιογραφία APA", basedOn: "Normal", next: "BibAPA", quickFormat: true,
      run: { font: FONT, size: 22 }, paragraph: { alignment: AlignmentType.LEFT, indent: { left: 720, hanging: 720 }, spacing: { before: 0, after: 120, line: 264, lineRule: LineRuleType.AUTO } } },
    { id: "Cover", name: "Εξώφυλλο", basedOn: "Normal", next: "Cover",
      run: { font: FONT, size: 24 }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0, line: 276, lineRule: LineRuleType.AUTO } } },
    { id: "CoverSmall", name: "Εξώφυλλο μικρό", basedOn: "Cover", next: "CoverSmall",
      run: { font: FONT, size: 20 }, paragraph: { alignment: AlignmentType.CENTER, spacing: { before: 0, after: 0, line: 240, lineRule: LineRuleType.AUTO } } },
    { id: "CopyrightText", name: "Κείμενο copyright", basedOn: "Normal", next: "CopyrightText",
      run: { font: FONT, size: 20 }, paragraph: { alignment: AlignmentType.JUSTIFIED, spacing: { before: 0, after: 0, line: 252, lineRule: LineRuleType.AUTO } } },
    { id: "Dedication", name: "Αφιέρωση", basedOn: "Normal", next: "Normal",
      run: { font: FONT, size: 24, italics: true }, paragraph: { alignment: AlignmentType.RIGHT, spacing: { before: cm(6), after: 480 }, pageBreakBefore: true } },
    { id: "Odigia", name: "Οδηγία", basedOn: "Normal", next: "Normal", quickFormat: true,
      run: { font: "Calibri", size: 20, color: "1F3864" },
      paragraph: { alignment: AlignmentType.LEFT, spacing: { before: 60, after: 60, line: 252, lineRule: LineRuleType.AUTO },
                   shading: { type: ShadingType.CLEAR, color: "auto", fill: "E8F0FA" },
                   border: { left: { style: BorderStyle.SINGLE, size: 18, color: "2F5597", space: 6 } },
                   indent: { left: 170, right: 170 } } },
  ],
};

const numbering = {
  config: [
    { reference: "headings", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 680, hanging: 680 } } } },
      { level: 1, format: LevelFormat.DECIMAL, text: "%1.%2", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 851, hanging: 851 } } } },
      { level: 2, format: LevelFormat.DECIMAL, text: "%1.%2.%3", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1021, hanging: 1021 } } } },
    ] },
    { reference: "bullets", levels: [
      { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 284 }, spacing: { after: 60 } } } },
    ] },
    { reference: "numbers", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 567, hanging: 340 }, spacing: { after: 60 } } } },
    ] },
    { reference: "ieee", levels: [
      { level: 0, format: LevelFormat.DECIMAL, text: "[%1]", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 680, hanging: 680 } } } },
    ] },
  ],
};

const page = { size: { width: 11906, height: 16838 },
  margin: { top: cm(2.5), bottom: cm(2.5), left: cm(3), right: cm(2.5), header: cm(1.25), footer: cm(1.25) } };
const pageNumberFooter = new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], size: 22 })] })] });
const emptyFooter = new Footer({ children: [new Paragraph({ children: [] })] });

const doc = new Document({
  creator: "", title: "Πρότυπο Διπλωματικής Εργασίας ΣΗΜΜΥ ΕΜΠ",
  description: "Word template for diploma theses, School of ECE, NTUA",
  features: { updateFields: true },
  styles, numbering,
  sections: [
    { properties: { page: { ...page, pageNumbers: { start: 1 } } }, footers: { default: emptyFooter },
      children: [...cover, ...titlePage, ...copyright, ...dedication] },
    { properties: { page, type: SectionType.NEXT_PAGE }, footers: { default: pageNumberFooter },
      children: [...abstracts, ...lists, ...ch1, ...ch2, ...ch3, ...ch4, ...ch5, ...back] },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(path.join(__dirname, "raw.docx"), buf);
  console.log("wrote raw.docx;", eqCount, "equations");
});
