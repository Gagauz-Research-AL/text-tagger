// Node test for static/logic.js — expectations recorded from observed
// behaviour of the pure logic (probe run), snapshotted into assertions.
const { makeJob, piecesOf, replaceSegment, drop, approve, applyDiffToUnderlines } = require("./logic.js");

let failures = 0;
function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    failures++;
    console.error(`FAIL ${name}\n  got:      ${a}\n  expected: ${e}`);
  } else {
    console.log(`ok   ${name}`);
  }
}

const raw = {
  text: "the cat sitted on the mat while the dog barked at the mailman",
  underlines: [
    { limit: { left_pos: 8, right_pos: 14 }, type: "grammatical error", candidates: ["sat", "was sitting"] },
    { limit: { left_pos: 18, right_pos: 21 }, type: "possible false positive" },
    { limit: { left_pos: 22, right_pos: 25 }, type: "weird spelling", candidates: ["matte", "doormat"] },
    { limit: { left_pos: 40, right_pos: 46 }, type: "weird spelling", candidates: ["bakked", "borked"] },
    { limit: { left_pos: 54, right_pos: 61 }, type: "phrasing", candidates: ["mail man", "postman"] },
  ],
};

function freshBase() {
  return makeJob(raw);
}

// --- makeJob -------------------------------------------------------------
const job = makeJob(raw);
check("makeJob normalizes underlines", job.underlines[1], {
  left_pos: 18, right_pos: 21, type: "possible false positive", candidates: [], original: "the",
});
check("makeJob captures original span text", job.underlines[0].original, "sitted");
check("piecesOf covers full text", piecesOf(job).reduce((s, p) => s + p.text, ""), raw.text);

// --- replaceSegment keeps the corrected word tagged -----------------------
const rj = freshBase();
replaceSegment(rj, 2, "doormat");
check("grow: corrected word stays tagged", [rj.underlines[2].left_pos, rj.underlines[2].right_pos], [22, 29]);
check("grow: later tags shift", [rj.underlines[3].left_pos, rj.underlines[4].right_pos], [44, 65]);
check("grow: text updated", rj.text, "the cat sitted on the doormat while the dog barked at the mailman");

replaceSegment(rj, 2, "barked");
check("equal retype: span follows the new word", [rj.underlines[2].left_pos, rj.underlines[2].right_pos], [22, 28]);
check("equal retype: later tags shift", rj.underlines[3].left_pos, 43);

replaceSegment(rj, 2, "mail man");
check("split: retyped span keeps its tag", rj.underlines.length, 5);
check("split: span covers replacement", [rj.underlines[2].left_pos, rj.underlines[2].right_pos], [22, 30]);
check("split: text updated", rj.text, "the cat sitted on the mail man while the dog barked at the mailman");

drop(rj, 1);
check("drop keeps text, removes tag", [rj.text, rj.underlines.length],
  ["the cat sitted on the mail man while the dog barked at the mailman", 4]);
check("piecesOf consistent after ops", piecesOf(rj).reduce((s, p) => s + p.text, ""), rj.text);
check("approve returns final text", approve(rj), "the cat sitted on the mail man while the dog barked at the mailman");

const edge = makeJob({ text: "abc", underlines: [] });
check("empty underlines allowed", piecesOf(edge), [{ text: "abc", span: null }]);

// --- applyDiffToUnderlines (live-typing semantics) -------------------------
let kept = applyDiffToUnderlines(raw.text,
  "the cat sat on the mat while the dog barked at the mailman", freshBase().underlines);
check("word altered in span -> tag dropped", kept.map((u) => [u.left_pos, u.right_pos]),
  [[15, 18], [19, 22], [37, 43], [51, 58]]);

kept = applyDiffToUnderlines(raw.text,
  "the cat sitted on the mat while the barked at the mailman", freshBase().underlines);
check("neighbour plain word deleted -> all tags survive", kept.map((u) => [u.left_pos, u.right_pos]),
  [[8, 14], [18, 21], [22, 25], [36, 42], [50, 57]]);
check("right-side span shifted after deletion", kept[3].left_pos, 36);

kept = applyDiffToUnderlines(raw.text,
  "the cat sittedx on the mat while the dog barked at the mailman", freshBase().underlines);
check("letter appended to underlined word -> tag dropped", kept.length, 4);

kept = applyDiffToUnderlines(raw.text,
  "the cat xsitted on the mat while the dog barked at the mailman", freshBase().underlines);
check("letters glued to span start -> tag dropped", kept.length, 4);

kept = applyDiffToUnderlines(raw.text,
  "the cat sitte on the mat while the dog barked at the mailman", freshBase().underlines);
check("letter deleted from underlined word -> tag dropped", kept.length, 4);

kept = applyDiffToUnderlines(raw.text,
  "the cat x sitted on the mat while the dog barked at the mailman", freshBase().underlines);
check("word typed before span -> kept and shifted", [kept.length, kept[0].left_pos, kept[0].right_pos], [5, 10, 16]);

kept = applyDiffToUnderlines(raw.text,
  "the cat sitted  on the mat while the dog barked at the mailman", freshBase().underlines);
check("separator typed at span edge -> tag survives", kept.length, 5);

const job5 = makeJob({ text: "abc", underlines: [{ limit: { left_pos: 1, right_pos: 2 }, type: "x" }] });
kept = applyDiffToUnderlines(job5.text, job5.text, job5.underlines);
check("identical text keeps tags", kept.length, 1);

const job6 = makeJob({
  text: "one two three",
  underlines: [
    { limit: { left_pos: 0, right_pos: 3 }, type: "a" },
    { limit: { left_pos: 4, right_pos: 7 }, type: "b" },
  ],
});
kept = applyDiffToUnderlines(job6.text, "oneX twoOhOhOh three", job6.underlines);
check("untouched span kept+shifted, altered one dropped", kept.length, 1);

// --- undo mechanism: snapshot before edit, pop on Ctrl+Z ------------------
// This is exactly what index.html does on every edit and every Ctrl+Z.
// Restoring the snapshot reinstates the deleted letter AND the tag — that
// is the fix for "Ctrl+Z does not bring the panel back".
const ui = freshBase();
const snap = { text: ui.text, underlines: ui.underlines.map((u) => ({ ...u })) };
ui.text = "the cat sitte on the mat while the dog barked at the mailman";
ui.underlines = applyDiffToUnderlines(snap.text, ui.text, snap.underlines);
check("live: deletion from underlined word drops its tag", ui.underlines.length, 4);
check("live: letter is gone", ui.text.slice(8, 13), "sitte");

ui.text = snap.text;
ui.underlines = snap.underlines;
check("undo: letter reinstated", ui.text.slice(8, 14), "sitted");
check("undo: tag count restored", ui.underlines.length, 5);
check("undo: span bounds restored", [ui.underlines[0].left_pos, ui.underlines[0].right_pos], [8, 14]);
check("undo: tag covers reinstated letter", ui.text.slice(ui.underlines[0].left_pos, ui.underlines[0].right_pos), "sitted");

// Same mechanism after applying a candidate:
const ok = freshBase();
const snap2 = { text: ok.text, underlines: ok.underlines.map((u) => ({ ...u })) };
replaceSegment(ok, 2, "doormat");
check("live: candidate applied", ok.text.slice(22, 29), "doormat");
check("live: candidate keeps tag", [ok.underlines[2].left_pos, ok.underlines[2].right_pos], [22, 29]);

ok.text = snap2.text;
ok.underlines = snap2.underlines;
check("undo after candidate reinstates original word", ok.text.slice(22, 25), "mat");
check("undo after candidate restores span", [ok.underlines[2].left_pos, ok.underlines[2].right_pos], [22, 25]);

if (failures) {
  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall logic.js tests passed");
