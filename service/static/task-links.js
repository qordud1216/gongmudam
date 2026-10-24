"use strict";
// Fixed destinations only. Passing a situation never creates or approves work.
window.SeomuTaskLinks = (() => {
  const tasks = {
    education_collection: {kind:"education", href:"adhoc.html?v=45#new", label:"교육 취합 시작하기", note:"입력한 상황을 이어받고 교육명·일정·대상 부서를 확인해요."},
    travel_settlement: {kind:"travel", href:"travel.html?v=45#from-guidance", label:"이 내용으로 출장정산 준비", note:"기관·실제 일정·지급 구분을 확인한 뒤 계산해요. 질문의 안내 문구는 계산 기준으로 적용하지 않아요."},
    folder_organize: {kind:"folder", href:"folders.html?v=45#from-guidance", label:"이 내용으로 업무자료 정리", note:"업무 목적을 이어받아요. 정리할 폴더는 다음 화면에서 직접 골라 주세요."}
  };
  function prepare() { return null; }
  function render(box, answer, today, fail) {
    const kind = answer.task_action?.kind || (answer.plan?.card?.id === "card-travel" ? "travel_settlement" : null);
    const task = tasks[kind];
    if (!task || !answer.query) return;
    const details = document.createElement("details"); details.className = "flow-links task-followup";
    const summary = document.createElement("summary"); summary.textContent = "계산·정산 등 도구가 필요할 때";
    const section = document.createElement("div"); section.className = "task-followup-content";
    const button = document.createElement("button"); button.className = "secondary"; button.textContent = task.label;
    button.addEventListener("click", () => {
      if (!window.SeomuFlow?.write(task.kind, {text:answer.query, today})) {
        fail(Error("브라우저 임시 저장을 사용할 수 없습니다. 다음 업무 화면에서 내용을 직접 입력해 주세요."));
        return;
      }
      location.href = task.href;
    });
    const note = document.createElement("p"); note.className = "muted"; note.textContent = task.note;
    section.append(button, note); details.append(summary, section);
    box.append(details);
  }
  return {render, prepare, clear(){}};
})();
