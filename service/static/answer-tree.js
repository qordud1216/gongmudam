"use strict";
function answerTreeHtml(tree, evidenceCount = 0) {
  if (!tree || !Array.isArray(tree.branches)) return "";
  const validCount = Number.isInteger(evidenceCount) && evidenceCount > 0 ? evidenceCount : 0;
  const branches = tree.branches.map((branch) => `<li class="answer-tree-branch"><div class="answer-tree-branch-label">${esc(branch.label)}</div><ul>${(Array.isArray(branch.items) ? branch.items : []).map((item) => {
    const ref = Number.isInteger(item.ref) && item.ref > 0 && item.ref <= validCount ? `<button type="button" class="answer-tree-ref" data-evidence-index="${item.ref}" aria-label="근거 ${item.ref} 확인">근거 ${item.ref}</button>` : "";
    return `<li class="answer-tree-leaf"><span>${esc(item.text)}</span>${ref}</li>`;
  }).join("")}</ul></li>`).join("");
  return `<section class="answer-tree" aria-label="한눈에 보기"><h3>한눈에 보기</h3><div class="answer-tree-root">${esc(tree.title)}</div><ul class="answer-tree-branches">${branches}</ul>${tree.note ? `<p class="answer-tree-note">${esc(tree.note)}</p>` : ""}</section>`;
}
function bindAnswerTree(box) {
  box.addEventListener("click", (event) => {
    const button = event.target.closest(".answer-tree-ref");
    if (!button || !box.contains(button)) return;
    const index = button.dataset.evidenceIndex;
    const original = button.closest(".bubble")?.querySelector("details.answer-original");
    if (!original) return;
    original.open = true;
    const target = [...original.querySelectorAll("details.knowledge-ref[data-evidence-index]")].find((detail) => detail.dataset.evidenceIndex === index);
    if (!target) return;
    for (let parent = target.parentElement; parent && parent !== original; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
    target.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.querySelector("summary")?.focus({ preventScroll: true });
  });
}
