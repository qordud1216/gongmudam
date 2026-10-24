"""Run offline question/retrieval QA cases against the in-process API."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "reference_data" / "question_checks_v39.json"
TODAY = "2026-10-20"

# Import the established hash-backed citation validator, also when invoked as a script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.check_question_answers import DEFAULT_MANIFEST, citation_checks, load_sources


def _evidence(result: dict[str, Any]) -> list[Any] | None:
    knowledge = result.get("knowledge")
    return knowledge.get("evidence") if isinstance(knowledge, dict) and isinstance(knowledge.get("evidence"), list) else None


def evaluate_case(case: Any, result: Any, verified_sources: dict[str, str]) -> dict[str, Any]:
    """Return actionable failures and diagnostics for one case and API response."""
    failures: list[str] = []
    checks: dict[str, Any] = {}
    if not isinstance(case, dict):
        return {"passed": False, "failures": ["case entry is not an object"], "checks": {}}
    if not isinstance(result, dict):
        return {"passed": False, "failures": ["API result is not an object"], "checks": {}}
    evidence = _evidence(result)
    if evidence is None:
        evidence = []
        failures.append("knowledge.evidence missing or not a list")
    mode = result.get("mode")
    outcome = case.get("outcome")
    if outcome not in {"answer", "unavailable", "clarify"}:
        failures.append(f"unknown outcome {outcome!r}")

    actual_articles: list[str] = []
    actual_rules: list[str] = []
    for entry in evidence:
        if isinstance(entry, dict) and isinstance(entry.get("official"), dict):
            article = entry["official"].get("article")
            if isinstance(article, str):
                actual_articles.append(article)
    tree = result.get("knowledge", {}).get("tree") if isinstance(result.get("knowledge"), dict) else None
    rule_id = tree.get("rule_id") if isinstance(tree, dict) else None
    if isinstance(rule_id, str):
        actual_rules.append(rule_id)
    checks["actual"] = {"mode": mode, "articles": actual_articles, "rules": actual_rules}

    if outcome == "answer":
        if not evidence:
            failures.append("answer outcome requires nonempty evidence")
        if mode not in {"source_search", "source_llm"}:
            failures.append(f"answer outcome requires source_search or source_llm mode; got {mode!r}")
        allow_articles = case.get("allow_articles")
        if allow_articles is not None:
            bad = []
            for entry in evidence:
                official = entry.get("official") if isinstance(entry, dict) else None
                article = official.get("article") if isinstance(official, dict) else None
                if not isinstance(article, str) or not any(isinstance(a, str) and a in article for a in allow_articles):
                    bad.append(article if isinstance(article, str) else "<nonofficial or missing article>")
            if bad:
                failures.append(f"official articles outside allow_articles: {bad!r}")
        required_articles = case.get("require_articles", [])
        for required in required_articles:
            if not isinstance(required, str) or not any(required in article for article in actual_articles):
                failures.append(f"required article not represented: {required!r}")
        combined = "\n".join(entry.get("text", "") for entry in evidence if isinstance(entry, dict) and isinstance(entry.get("text"), str))
        missing_facts = [fact for fact in case.get("facts", []) if not isinstance(fact, str) or fact not in combined]
        if missing_facts:
            failures.append(f"required source facts missing from combined evidence: {missing_facts!r}")

        tree_text = "\n".join(
            item.get("text", "")
            for branch in (tree.get("branches", []) if isinstance(tree, dict) and isinstance(tree.get("branches"), list) else [])
            if isinstance(branch, dict)
            for item in (branch.get("items", []) if isinstance(branch.get("items"), list) else [])
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
        missing_summary_facts = [fact for fact in case.get("summary_facts", [])
                                 if not isinstance(fact, str) or fact not in tree_text]
        if missing_summary_facts:
            failures.append(f"required summary facts missing from tree text: {missing_summary_facts!r}")

        answer = result.get("answer")
        answer_facts = case.get("answer_facts", [])
        missing_answer_facts = [fact for fact in answer_facts
                                if not isinstance(fact, str) or not isinstance(answer, str) or fact not in answer]
        if missing_answer_facts:
            failures.append(f"required answer facts missing from displayed answer: {missing_answer_facts!r}")
        paragraph_checks = []
        if not isinstance(answer, str) or not answer.strip():
            failures.append("answer outcome requires nonblank displayed answer")
        else:
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", answer.replace("\r\n", "\n").replace("\r", "\n")) if p.strip()]
            for index, paragraph in enumerate(paragraphs):
                match = re.fullmatch(r"\[(\d+)\]\s*(.+)", paragraph, flags=re.DOTALL)
                if not match:
                    paragraph_checks.append({"paragraph": index, "passed": False, "error": "missing [n] prefix"})
                    failures.append(f"answer paragraph {index + 1} lacks a [n] evidence prefix")
                    continue
                number, displayed_text = int(match.group(1)), match.group(2)
                entry = evidence[number - 1] if 1 <= number <= len(evidence) else None
                source_text = entry.get("text") if isinstance(entry, dict) else None
                valid = isinstance(source_text, str) and displayed_text in source_text
                paragraph_checks.append({"paragraph": index, "ref": number, "passed": valid,
                                         "error": None if valid else "prefix is out of range or paragraph is not exact evidence text"})
                if not valid:
                    failures.append(f"answer paragraph {index + 1} does not exactly match evidence [{number}]")
        checks["answer_paragraphs"] = paragraph_checks

        if isinstance(tree, dict):
            tree_checks = []
            for branch_index, branch in enumerate(tree.get("branches", []) if isinstance(tree.get("branches"), list) else []):
                for item_index, item in enumerate(branch.get("items", []) if isinstance(branch, dict) and isinstance(branch.get("items"), list) else []):
                    if not isinstance(item, dict) or "support_quotes" not in item:
                        continue
                    ref = item.get("ref")
                    entry = evidence[ref - 1] if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(evidence) else None
                    source_text = entry.get("text") if isinstance(entry, dict) else None
                    quotes = item.get("support_quotes")
                    valid_quotes = isinstance(quotes, list) and all(isinstance(q, str) and isinstance(source_text, str) and q in source_text for q in quotes)
                    ok = entry is not None and valid_quotes
                    tree_checks.append({"branch": branch_index, "item": item_index, "ref": ref, "passed": ok})
                    if not ok:
                        failures.append(f"tree support_quotes item {branch_index}.{item_index} has invalid ref or unsupported quote")
            checks["tree_support"] = tree_checks
        else:
            checks["tree_support"] = []

        allow_rules = case.get("allow_rules")
        if isinstance(tree, dict) and tree.get("kind") == "summary" and allow_rules is not None and rule_id not in allow_rules:
            failures.append(f"summary rule {rule_id!r} is outside allow_rules")
        require_rules = case.get("require_rules", [])
        for required in require_rules:
            if not isinstance(required, str) or rule_id != required:
                failures.append(f"required summary rule not represented: {required!r}")
    elif outcome == "unavailable":
        if evidence:
            failures.append("unavailable outcome requires no evidence")
        if mode != "source_unavailable":
            failures.append(f"unavailable outcome requires source_unavailable mode; got {mode!r}")
    elif outcome == "clarify":
        if evidence:
            failures.append("clarify outcome requires no evidence")
        if mode != "source_clarification":
            failures.append(f"clarify outcome requires source_clarification mode; got {mode!r}")
        if not isinstance(tree, dict) or tree.get("kind") != "clarification":
            failures.append("clarify outcome requires tree.kind clarification")

    forbid_rules = case.get("forbid_rules", [])
    if isinstance(tree, dict) and rule_id in forbid_rules:
        failures.append(f"forbidden summary rule used: {rule_id!r}")

    citations = citation_checks({"knowledge": {"evidence": evidence}}, verified_sources)
    checks["citations"] = citations
    if not citations["passed"]:
        failures.append("one or more citations failed exact verified-excerpt validation")
    return {"passed": not failures, "failures": failures, "checks": checks}


def _run_cases(cases: list[Any], verified_sources: dict[str, str], include_extended: bool = False) -> list[dict[str, Any]]:
    from app import assistant, folders, knowledge, main

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="question-audit-") as temp_dir:
        db_patch = patch.object(folders, "DB_PATH", Path(temp_dir) / "folders.db")
        with db_patch:
            folders.initialize()
            knowledge.initialize()
            manifest_rows = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
            selected_rows = manifest_rows if include_extended else [row for row in manifest_rows if row.get("collection") != "v40"]
            expected_digests = {row["sha256"] for row in selected_rows}
            excerpt_dir = DEFAULT_MANIFEST.parent / "excerpts"
            library = folders.connect(folders.Connect(name="오프라인 질문 검증", roots=[str(excerpt_dir)]))
            selected_files = [item for item in library["files"] if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() in expected_digests]
            registration = knowledge.register(library["id"], knowledge.Register(
                version=library["version"], file_ids=[item["id"] for item in selected_files], kind="참고자료"))
            key = library["id"]
            if registration.get("registered") != len(expected_digests):
                raise RuntimeError(f"expected to register {len(expected_digests)} official excerpts, got {registration.get('registered')!r}")
            with patch.object(knowledge.config, "active_profile", return_value={"provider": "offline"}), \
                 patch.object(main.assistant, "ask", side_effect=AssertionError("offline QA must not fall back to assistant.ask")):
                for case in cases:
                    item: dict[str, Any] = {"id": case.get("id") if isinstance(case, dict) else None,
                                            "category": case.get("category") if isinstance(case, dict) else None,
                                            "question": case.get("question") if isinstance(case, dict) else None}
                    started = time.monotonic()
                    try:
                        if not isinstance(case, dict) or not isinstance(case.get("question"), str) or not case["question"].strip():
                            raise ValueError("case must have a nonempty question")
                        reply = main.api_ask({"query": case["question"], "knowledge_library_id": key, "today": TODAY})
                        check = evaluate_case(case, reply, verified_sources)
                        item.update({"mode": reply.get("mode"), "articles": check["checks"].get("actual", {}).get("articles", []),
                                     "rules": check["checks"].get("actual", {}).get("rules", []), "failures": check["failures"],
                                     "checks": check["checks"], "passed": check["passed"], "result": reply})
                    except Exception as exc:
                        item.update({"mode": None, "articles": [], "rules": [], "failures": [f"{type(exc).__name__}: {exc}"],
                                     "checks": {}, "passed": False, "result": None})
                    item["duration_seconds"] = round(time.monotonic() - started, 3)
                    results.append(item)
    return results


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-extended", action="store_true", help="include v40 manifest sources")
    args = parser.parse_args(argv)
    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("cases JSON root must be a list")
    except Exception as exc:
        parser.error(f"cannot read cases: {type(exc).__name__}: {exc}")
    verified_sources, manifest_problems = load_sources(DEFAULT_MANIFEST)
    case_results = _run_cases(cases, verified_sources, include_extended=args.include_extended)
    category_counts: dict[str, dict[str, int]] = {}
    for item in case_results:
        category = str(item.get("category") or "<uncategorized>")
        counts = category_counts.setdefault(category, {"total": 0, "passed": 0, "failed": 0})
        counts["total"] += 1
        counts["passed" if item["passed"] else "failed"] += 1
    passed = sum(bool(item["passed"]) for item in case_results)
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "cases_path": str(args.cases),
              "manifest_problems": manifest_problems, "cases": case_results,
              "summary": {"total": len(case_results), "passed": passed, "failed": len(case_results) - passed,
                          "categories": category_counts}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if passed == len(case_results) and not manifest_problems else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
