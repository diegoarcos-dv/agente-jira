"""Read-only benchmark for GATE G2 deterministic-first extraction.

It never calls the application API, ProposalRepository, Jira, MCP, or writes
any file.  Ollama receives only deterministic candidates during enrichment.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.minutes import normalize_text
from app.minutes_deterministic import extract_explicit
from app.minutes_enrichment import build_activities, enrichment_payload
from app.minutes_prompt import ENRICH_PROMPT_VERSION, prompt_for
from benchmark_minutes import datasets


def enrich(client: httpx.Client, model: str, candidates, timeout: float) -> tuple[str | None, int, str | None]:
    _, system_prompt = prompt_for(ENRICH_PROMPT_VERSION)
    payload = {"model": model, "stream": False, "think": False, "format": "json",
               "options": {"temperature": 0, "num_predict": 1536, "num_ctx": 8192},
               "messages": [{"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps({"candidates": enrichment_payload(candidates)}, ensure_ascii=False)}]}
    started = time.perf_counter()
    try:
        response = client.post("/api/chat", json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json().get("message", {}).get("content")
        return content if isinstance(content, str) else None, round((time.perf_counter() - started) * 1000), None
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        return None, round((time.perf_counter() - started) * 1000), exc.__class__.__name__


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vic-path", type=Path, required=True)
    parser.add_argument("--model", default="qwen2.5:1.5b")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--only", action="append", help="Dataset key to run (repeatable)")
    args = parser.parse_args()
    selected = datasets(args.vic_path)
    if args.only:
        selected = {name: selected[name] for name in args.only if name in selected}
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=args.timeout,
                      trust_env=False, follow_redirects=False) as client:
        for name, (text, expected) in selected.items():
            normalized, removed = normalize_text(text)
            started = time.perf_counter()
            extraction = extract_explicit(normalized)
            deterministic_ms = round((time.perf_counter() - started) * 1000)
            terms = " ".join(c.normalized_text for c in extraction.candidates).casefold()
            found = sum(term.casefold() in terms for term in expected)
            row = {"dataset": name, "mode": extraction.extraction_mode,
                   "deterministic_candidates": len(extraction.candidates),
                   "expected": len(expected), "found": found,
                   "evidence_valid": all(c.source_evidence in normalized or c.source_evidence.replace("\n", " ") in normalized.replace("\n", " ") for c in extraction.candidates),
                   "removed_duplicates": removed, "deterministic_ms": deterministic_ms}
            if args.skip_llm or not extraction.candidates:
                row.update({"enrichment": "SKIPPED", "enrichment_ms": 0, "final_candidates": len(extraction.candidates)})
            else:
                raw, elapsed, error = enrich(client, args.model, extraction.candidates, args.timeout)
                activities, warnings, valid = build_activities(extraction.candidates, raw)
                row.update({"enrichment": "HYBRID_ENRICHED" if valid else "DETERMINISTIC_FALLBACK",
                            "enrichment_ms": elapsed, "final_candidates": len(activities),
                            "cardinality_preserved": len(activities) == len(extraction.candidates),
                            "fallback_warning": bool(warnings), "error": error})
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
