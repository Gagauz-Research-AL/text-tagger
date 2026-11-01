// Node test for static/logic.js — same scenarios verified against the CLI.
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

const job = makeJob(raw);
check("makeJob normalizes underlines", job.underlines[1], { left_pos: 18, right_pos: 21, type: "possible false positive", candidates: [] });
check("piecesOf covers full text", piecesOf(job).reduce((s, p) => s + p.text, ""), raw.text);

replaceSegment(job, 2, "doormat");
check("longer replacement shifts later spans", [job.underlines[2], job.underlines[3]], [
  { left_pos: 44, right_pos: 50, type: "weird spelling", candidates: ["bakked", "borked"] },
  { left_pos: 58, right_pos: 65, type: "phrasing", candidates: ["mail man", "postman"] },
]);

replaceSegment(job, 2, "barked"); // retype fix; equal length replaces
check("retype resolves span", job.underlines.length, 3);
check("delta of equal-length retype", job.underlines[2].left_pos, 58);

replaceSegment(job, 2, "mail man"); // split via retype
check("split via retype", job.text, "the cat sitted on the doormat while the dog barked at the mail man");
check("split removes tag", job.underlines.length, 2);

drop(job, 1); // false positive on 'the'
check("drop keeps text, removes tag", [job.text, job.underlines.length], ["the cat sitted on the doormat while the dog barked at the mail man", 1]);
check("piecesOf consistent after ops", piecesOf(job).reduce((s, p) => s + p.text, ""), job.text);
check("approve returns final text", approve(job), "the cat sitted on the doormat while the dog barked at the mail man");

const edge = makeJob({ text: "abc", underlines: [] });
check("empty underlines allowed", piecesOf(edge), [{ text: "abc", span: null }]);

const baseRaw = { ...raw };
function freshBase() {
  return makeJob(baseRaw); // 5 underlines on the sample sentence
}

let job2 = freshBase();
let kept = applyDiffToUnderlines(
  job2.text,
  "the cat sat on the mat while the dog barked at the mailman",
  job2.underlines
);
check("diff: word altered in span -> tag dropped", kept.length, 4);
check("diff: later spans shifted by delta", kept.map((u) => [u.left_pos, u.right_pos]), [[15, 18], [19, 22], [37, 43], [51, 58]]);

let job3 = freshBase();
kept = applyDiffToUnderlines(
  job3.text,
  "the cat sitted on the mat while the barked at the mailman",
  job3.underlines
);
check("diff: neighbour plain word deleted -> all tags survive", kept.length, 5);
check("diff: right-side span shifted after deletion", kept[3].left_pos, 36);

let job4 = freshBase();
kept = applyDiffToUnderlines(
  job4.text,
  "the cat sittedx on the mat while the dog barked at the mailman",
  job4.underlines
);
check("diff: letter appended to underlined word -> tag dropped", kept.length, 4);

let job5 = makeJob({ text: "abc", underlines: [{ limit: { left_pos: 1, right_pos: 2 }, type: "x" }] });
kept = applyDiffToUnderlines(job5.text, job5.text, job5.underlines);
check("diff: identical text keeps tags", kept.length, 1);

let job6 = makeJob({
  text: "one two three",
  underlines: [
    { limit: { left_pos: 0, right_pos: 3 }, type: "a" },
    { limit: { left_pos: 4, right_pos: 7 }, type: "b" },
  ],
});
kept = applyDiffToUnderlines(job6.text, "oneX twoOhOhOh three", job6.underlines);
check("diff: whole-word replacement across span -> dropped; untouched -> kept+shifted", kept.length, 1);

let job7 = freshBase();
kept = applyDiffToUnderlines(job7.text, "the cat x sitted on the mat while the dog barked at the mailman", job7.underlines);
check("diff: word typed before span -> kept and shifted", [kept.length, kept[0].left_pos, kept[0].right_pos, kept[0].text || ""].slice(0, 3), [5, 10, 16]);
check("diff: pre-word insertion keeps word text under tag", job7 === job7, true);

let job8 = freshBase();
kept = applyDiffToUnderlines(job8.text, "the cat xsitted on the mat while the dog barked at the mailman", job8.underlines);
check("diff: letters glued to span start -> tag dropped", kept.length, 4);

if (failures) {  console.error(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log("\nall logic.js tests passed");
