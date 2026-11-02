const { makeJob, applyDiffToUnderlines } = require("./static/logic.js");

// Test case: internal deletion
let raw = {
  text: "the cat sitted on the mat while the dog barked at the mailman",
  underlines: [
    { limit: { left_pos: 22, right_pos: 25 }, type: "weird spelling", candidates: ["matte", "doormat"] }, // "mat" at [22,25)
  ]
};

let job = makeJob(raw);
console.log("Original job:", JSON.stringify(job.underlines[0]));

// Delete last letter 't' from "mat" -> "ma" 
let newText = "the cat sitted on the ma while the dog barked at the mailman";
console.log("\nNew text:", newText);
let kept = applyDiffToUnderlines(job.text, newText, job.underlines);
console.log("After deletion:", JSON.stringify(kept));

// Check if tag preserved and boundaries correct
if (kept.length === 1) {
  console.log("✓ Tag preserved");
  if (kept[0].left_pos === 22 && kept[0].right_pos === 24) {
    console.log("✓ Boundaries correct: [22,24)");
  } else {
    console.log("✗ Boundaries incorrect:", kept[0].left_pos, kept[0].right_pos);
  }
} else {
  console.log("✗ Tag not preserved, length:", kept.length);
}

// Test restoration
let restoredText = "the cat sitted on the mat while the dog barked at the mailman";
console.log("\nRestoring to:", restoredText);
let restored = applyDiffToUnderlines(newText, restoredText, kept);
console.log("After restoration:", JSON.stringify(restored));

if (restored.length === 1) {
  console.log("✓ Tag preserved after restore");
  if (restored[0].left_pos === 22 && restored[0].right_pos === 25) {
    console.log("✓ Boundaries correct after restore: [22,25)");
  } else {
    console.log("✗ Boundaries incorrect after restore:", restored[0].left_pos, restored[0].right_pos);
  }
} else {
  console.log("✗ Tag not preserved after restore, length:", restored.length);
}