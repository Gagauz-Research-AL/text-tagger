// Pure edit logic for the text-tagger UI — a JS mirror of tagger.py.
// No DOM access: unit-testable with node.

function makeJob(raw) {
  const text = raw.text;
  const underlines = (raw.underlines || []).map((u) => {
    const left = u.limit ? u.limit.left_pos : u.left_pos;
    const right = u.limit ? u.limit.right_pos : u.right_pos;
    return {
      left_pos: left,
      right_pos: right,
      type: u.type || "",
      candidates: u.candidates ? u.candidates.slice() : [],
      original: text.slice(left, right),
    };
  });
  underlines.sort((a, b) => a.left_pos - b.left_pos);
  return { text, underlines };
}

function piecesOf(job) {
  const pieces = [];
  let pos = 0;
  job.underlines.forEach((u, i) => {
    if (u.left_pos > pos) pieces.push({ text: job.text.slice(pos, u.left_pos), span: null });
    pieces.push({ text: job.text.slice(u.left_pos, u.right_pos), span: i });
    pos = u.right_pos;
  });
  if (pos < job.text.length) pieces.push({ text: job.text.slice(pos), span: null });
  return pieces;
}

function replaceSegment(job, idx, newText) {
  const u = job.underlines[idx];
  const delta = newText.length - (u.right_pos - u.left_pos);
  job.text = job.text.slice(0, u.left_pos) + newText + job.text.slice(u.right_pos);
  u.right_pos = u.left_pos + newText.length;
  job.underlines.forEach((other, j) => {
    if (j !== idx && other.left_pos >= u.right_pos - delta) {
      other.left_pos += delta;
      other.right_pos += delta;
    }
  });
}

function drop(job, idx) {
  job.underlines.splice(idx, 1);
}

function isSeparator(ch) {
  return /\s/.test(ch) || ".,;:!?()\"'-—–".includes(ch);
}

function applyDiffToUnderlines(oldText, newText, underlines) {
  // Underlines fully left of the change keep their offsets; fully right of
  // it shift by the length delta; anything overlapping the change region is
  // dropped (its word was altered by the edit).
  // Boundary rule: a pure insertion sitting exactly on a span edge survives
  // only if the inserted text is separated from the word (= typed a
  // neighbouring word); letters glued onto the word (concat) drop the tag.
  if (oldText === newText) return underlines.slice();
  const min = Math.min(oldText.length, newText.length);
  let a = 0;
  while (a < min && oldText[a] === newText[a]) a++;
  let b = 0;
  while (b < min - a && oldText[oldText.length - 1 - b] === newText[newText.length - 1 - b]) b++;
  const changeEnd = oldText.length - b;
  const delta = newText.length - oldText.length;
  const inserted = a === changeEnd ? newText.slice(a, a + delta) : null;
  return underlines.filter((u) => {
    if (inserted !== null) {
      if (a === u.right_pos) return isSeparator(inserted[0]);
      if (a === u.left_pos && !isSeparator(inserted[inserted.length - 1])) return false;
    }
    if (u.right_pos <= a) return true;
    if (u.left_pos >= changeEnd) {
      u.left_pos += delta;
      u.right_pos += delta;
      return true;
    }
    return false;
  });
}

function approve(job) {
  return job.text;
}

if (typeof module !== "undefined") {
  module.exports = { makeJob, piecesOf, replaceSegment, drop, approve, applyDiffToUnderlines };
}
