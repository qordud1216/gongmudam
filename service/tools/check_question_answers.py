"""Run reviewed manual QA cases against the local question-answering API."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "reference_data" / "official-20261020" / "manifest.json"
TODAY = "2026-10-20"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(value: str) -> str:
    return " ".join(value.split())


def load_sources(manifest_path: Path) -> tuple[dict[str, str], list[str]]:
    """Return verified excerpt text indexed by sha, and manifest problems."""
    texts: dict[str, str] = {}
    problems: list[str] = []
    try:
        rows = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("manifest root is not a list")
    except Exception as exc:
        return texts, [f"manifest unavailable: {type(exc).__name__}: {exc}"]

    excerpt_dir = manifest_path.parent / "excerpts"
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("sha256"), str) or not isinstance(row.get("filename"), str):
            problems.append(f"manifest entry {index} missing sha256 or filename")
            continue
        path = excerpt_dir / row["filename"]
        try:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if digest != row["sha256"]:
                problems.append(f"excerpt hash mismatch for manifest entry {index}")
                continue
            texts[row["sha256"]] = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except Exception as exc:
            problems.append(f"excerpt unavailable for manifest entry {index}: {type(exc).__name__}: {exc}")
    return texts, problems


def as_evidence(answer: dict[str, Any]) -> list[Any] | None:
    knowledge = answer.get("knowledge")
    if not isinstance(knowledge, dict) or not isinstance(knowledge.get("evidence"), list):
        return None
    return knowledge["evidence"]


def citation_checks(answer: dict[str, Any], verified_sources: dict[str, str]) -> dict[str, Any]:
    evidence = as_evidence(answer)
    if evidence is None:
        return {"passed": False, "checked": 0, "items": [], "error": "knowledge.evidence missing or not a list"}
    items: list[dict[str, Any]] = []
    for index, entry in enumerate(evidence):
        if not isinstance(entry, dict):
            items.append({"index": index, "passed": False, "error": "evidence entry is not an object"})
            continue
        sha = entry.get("sha256")
        source = verified_sources.get(sha) if isinstance(sha, str) else None
        fields = ["quote"] + (["model_selected_quote"] if "model_selected_quote" in entry else [])
        item: dict[str, Any] = {"index": index, "sha256": sha, "fields": {}}
        for field in fields:
            quote = entry.get(field)
            valid = isinstance(quote, str) and source is not None and quote.replace("\r\n", "\n").replace("\r", "\n") in source
            item["fields"][field] = {"passed": valid, "error": None if valid else (
                "quote is missing or not text" if not isinstance(quote, str) else
                "sha256 does not identify a verified registered excerpt" if source is None else
                "quote is not exact contiguous excerpt text"
            )}
        item["passed"] = all(value["passed"] for value in item["fields"].values())
        items.append(item)
    return {"passed": all(item.get("passed", False) for item in items), "checked": len(items), "items": items}


def evaluate(case: Any, answer: dict[str, Any], verified_sources: dict[str, str]) -> dict[str, Any]:
    failures: list[str] = []
    checks: dict[str, Any] = {}
    if not isinstance(case, dict):
        return {"passed": False, "failures": ["case entry is not an object"], "checks": {}}

    evidence = as_evidence(answer)
    mode = answer.get("mode")
    if evidence is None:
        failures.append("missing knowledge.evidence list")
        evidence = []
    if not isinstance(mode, str):
        failures.append("missing mode")
        mode = None

    expected = case.get("expected")
    expect_no_answer = case.get("expect_no_answer", False)
    if not isinstance(expect_no_answer, bool):
        failures.append("expect_no_answer must be a boolean")
        expect_no_answer = False

    expected_results: list[dict[str, Any]] = []
    if not isinstance(expected, list):
        failures.append("expected must be a list")
    elif expect_no_answer and expected:
        failures.append("expected must be empty when expect_no_answer is true")
    else:
        for idx, item in enumerate(expected):
            if not isinstance(item, dict):
                failures.append(f"expected[{idx}] is not an object")
                continue
            title, article, facts = item.get("title"), item.get("article"), item.get("facts")
            malformed = []
            if not isinstance(title, str) or not title:
                malformed.append("title")
            if not isinstance(article, str) or not article:
                malformed.append("article")
            if not isinstance(facts, list) or not all(isinstance(fact, str) for fact in facts):
                malformed.append("facts")
            if malformed:
                failures.append(f"expected[{idx}] missing or invalid fields: {', '.join(malformed)}")
                expected_results.append({"index": idx, "passed": False, "error": "invalid expected fields"})
                continue
            matches = []
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                official = entry.get("official")
                if not isinstance(official, dict):
                    continue
                if official.get("title") == title and isinstance(official.get("article"), str) and official["article"].startswith(article):
                    matches.append(entry)
            quotes = [normalized(entry["quote"]) for entry in matches if isinstance(entry.get("quote"), str)]
            missing_facts = [fact for fact in facts if not any(normalized(fact) in quote for quote in quotes)]
            result = {"index": idx, "matched_evidence": len(matches), "missing_facts": missing_facts,
                      "passed": bool(matches) and not missing_facts}
            expected_results.append(result)
            if not result["passed"]:
                failures.append(f"expected[{idx}] did not match title/article and all facts")

    if expect_no_answer:
        summary = answer.get("summary")
        if not isinstance(summary, str):
            failures.append("expect_no_answer requires summary text")
            summary = ""
        phrase = bool(re.search(r"확인하지 못|확인할 수 없", summary))
        no_evidence = len(evidence) == 0
        supported_mode = mode == "source_unavailable"
        checks["no_answer"] = {"passed": no_evidence and (supported_mode or phrase), "no_evidence": no_evidence,
                               "mode": mode, "supported_mode": supported_mode, "summary_phrase": phrase}
        if not checks["no_answer"]["passed"]:
            failures.append("no-answer conditions were not met")
    elif mode not in {"source_search", "source_llm"}:
        failures.append(f"mode {mode!r} is not a recognized official-answer mode")

    checks["expected"] = expected_results
    if not expect_no_answer:
        displayed = answer.get("answer")
        all_facts = [fact for entry in expected if isinstance(expected, list) for fact in (entry.get("facts", []) if isinstance(entry, dict) and isinstance(entry.get("facts"), list) else []) if isinstance(fact, str)] if isinstance(expected, list) else []
        missing_facts = [fact for fact in all_facts if not isinstance(displayed, str) or normalized(fact) not in normalized(displayed)]
        paragraph_checks: list[dict[str, Any]] = []
        paragraph_errors: list[str] = []
        if not isinstance(displayed, str) or not displayed.strip():
            paragraph_errors.append("displayed answer is missing or empty")
        else:
            canonical = displayed.replace("\r\n", "\n").replace("\r", "\n")
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", canonical) if part.strip()]
            for paragraph_index, paragraph in enumerate(paragraphs):
                match = re.fullmatch(r"\[(\d+)\]\s*(.+)", paragraph, flags=re.DOTALL)
                if not match:
                    paragraph_checks.append({"paragraph": paragraph_index, "passed": False, "error": "missing [n] citation prefix"})
                    paragraph_errors.append(f"paragraph {paragraph_index + 1} has no citation prefix")
                    continue
                number = int(match.group(1))
                cited_text = match.group(2)
                cited_evidence = evidence[number - 1] if 1 <= number <= len(evidence) and isinstance(evidence[number - 1], dict) else None
                source_text = cited_evidence.get("text") if isinstance(cited_evidence, dict) else None
                if isinstance(source_text, str):
                    source_text = source_text.replace("\r\n", "\n").replace("\r", "\n")
                exact = isinstance(source_text, str) and cited_text in source_text
                paragraph_checks.append({"paragraph": paragraph_index, "citation": number, "passed": exact,
                                         "error": None if exact else "citation does not identify evidence with an exact contiguous text match"})
                if not exact:
                    paragraph_errors.append(f"paragraph {paragraph_index + 1} is not an exact excerpt from citation [{number}]")
        displayed_check = {"passed": not missing_facts and not paragraph_errors, "missing_facts": missing_facts,
                           "citation_paragraphs": paragraph_checks, "errors": paragraph_errors}
        checks["displayed_answer"] = displayed_check
        if not displayed_check["passed"]:
            failures.append("displayed answer is missing expected facts or contains uncited/non-exact text")
    checks["citations"] = citation_checks(answer, verified_sources)
    if not checks["citations"]["passed"]:
        failures.append("one or more citations failed exact excerpt validation")
    return {"passed": not failures, "failures": failures, "checks": checks}


def write_output(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path, help="JSON file containing a list of reviewed QA cases")
    parser.add_argument("--output", required=True, type=Path, help="JSON file to write results to")
    parser.add_argument("--base-url", default="http://127.0.0.1:8766", help="question-answering API base URL")
    parser.add_argument("--library-id", help="optional knowledge library ID sent with each question")
    parser.add_argument("--case", help="run only the case with this id")
    args = parser.parse_args()

    try:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(cases, list):
            raise ValueError("cases JSON root must be a list")
    except Exception as exc:
        parser.error(f"cannot read cases: {type(exc).__name__}: {exc}")
    selected = [case for case in cases if args.case is None or (isinstance(case, dict) and case.get("id") == args.case)]
    if args.case is not None and not selected:
        parser.error(f"no case found with id {args.case!r}")

    verified_sources, manifest_problems = load_sources(DEFAULT_MANIFEST)
    report: dict[str, Any] = {"started_at": utc_now(), "base_url": args.base_url, "library_id": args.library_id,
                              "citation_text_normalization": "line_endings_only", "cases": [], "manifest_problems": manifest_problems}
    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        for case in selected:
            started = time.monotonic()
            item: dict[str, Any] = {"id": case.get("id") if isinstance(case, dict) else None,
                                    "category": case.get("category") if isinstance(case, dict) else None,
                                    "question": case.get("question") if isinstance(case, dict) else None,
                                    "checked_at": utc_now()}
            try:
                if not isinstance(case, dict) or not isinstance(case.get("question"), str) or not case["question"].strip():
                    raise ValueError("case must have a non-empty question")
                payload: dict[str, Any] = {"query": case["question"], "today": TODAY}
                if args.library_id:
                    payload["knowledge_library_id"] = args.library_id
                response = client.post("/api/ask", json=payload)
                response.raise_for_status()
                answer = response.json()
                if not isinstance(answer, dict):
                    raise ValueError("API response root is not an object")
                item.update({"mode": answer.get("mode"), "model": answer.get("model"), "answer": answer,
                             "checks": evaluate(case, answer, verified_sources)})
            except Exception as exc:
                item["checks"] = {"passed": False, "failures": [f"{type(exc).__name__}: {exc}"], "checks": {}}
                item["mode"] = None
                item["model"] = None
            item["duration_seconds"] = round(time.monotonic() - started, 3)
            report["cases"].append(item)
            report["updated_at"] = utc_now()
            write_output(args.output, report)
            outcome = "PASS" if item["checks"].get("passed") else "FAIL"
            print(f"{item['id'] or '<missing-id>'} {item.get('mode') or '<no-mode>'} {item['duration_seconds']:.3f}s {outcome}", flush=True)

    passed = sum(bool(item["checks"].get("passed")) for item in report["cases"])
    report["summary"] = {"passed": passed, "failed": len(report["cases"]) - passed, "total": len(report["cases"]),
                          "manifest_problem_count": len(manifest_problems)}
    report["completed_at"] = utc_now()
    write_output(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if passed == len(report["cases"]) and not manifest_problems else 1


if __name__ == "__main__":
    sys.exit(main())
