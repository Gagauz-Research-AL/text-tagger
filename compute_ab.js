const { makeJob } = require("./static/logic.js");

let oldText = "the cat sitted on the ma while the dog barked at the mailman";
let newText = "the cat sitted on the mat while the dog barked at the mailman";

console.log("Old text:", oldText);
console.log("New text:", newText);

// Compute a and b like in the function
const min = Math.min(oldText.length, newText.length);
let a = 0;
while (a < min && oldText[a] === newText[a]) a++;
let b = 0;
while (b < min - a && oldText[oldText.length - 1 - b] === newText[newText.length - 1 - b]) b++;
const changeEnd = oldText.length - b;
const delta = newText.length - oldText.length;

console.log("a =", a);
console.log("b =", b);
console.log("changeEnd =", changeEnd);
console.log("delta =", delta);
console.log("oldText.length =", oldText.length);
console.log("newText.length =", newText.length);

// Show the characters around position a
console.log("\nAround position a:");
for (let i = Math.max(0, a-3); i < Math.min(oldText.length, a+3); i++) {
  const oldChar = oldText[i] || '(end)';
  const newChar = newText[i] || '(end)';
  const mark = (i === a) ? '<<<' : ' ';
  console.log(`${i}: old='${oldChar}' new='${newChar}' ${mark}`);
}

// Show the characters around the end
console.log("\nAround the end:");
for (let i = Math.max(0, oldText.length-5-b); i < Math.min(oldText.length, oldText.length+5); i++) {
  const oldChar = oldText[i] || '(end)';
  const newChar = newText[i] || '(end)';
  const markOld = (i === oldText.length - 1 - b) ? '<-b' : ' ';
  const markNew = (i === newText.length - 1 - b) ? '<-b' : ' ';
  console.log(`${i}: old='${oldChar}' new='${newChar}' ${markOld}${markNew}`);
}