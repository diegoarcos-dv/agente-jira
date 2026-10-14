"""Read-only Ollama benchmark for GATE G2.

The script sends the versioned minutes prompt directly to Ollama. It never
calls the application API, creates proposals, or writes to Jira.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from app.minutes import MinutesDocument, normalize_text, validate_extraction
from app.minutes_prompt import prompt_for


def load_vic(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    start = raw.find("Fecha:")
    end_marker = "Ejecuta ahora únicamente la aceptación real de GATE G1."
    end = raw.find(end_marker, start)
    return raw[start:end if end >= 0 else None].strip()


def datasets(vic_path: Path) -> dict[str, tuple[str, list[str]]]:
    vic = load_vic(vic_path)
    return {
        "A-VIC-GIS-real-duplicada": (vic + "\n\n" + vic, [
            "ajustes pendientes", "sesión conjunta", "pruebas integrales",
            "resultados finales", "liberación a Producción",
        ]),
        "B-pendientes-explicitos": (
            "Reunión 20/06/2026. Pendientes: preparar el diseño; revisar permisos; enviar el informe antes del viernes.",
            ["preparar el diseño", "revisar permisos", "enviar el informe"],
        ),
        "C-sin-responsable": (
            "Minuta de seguimiento. Participantes: Ana y Luis. Acuerdos: actualizar el tablero y validar la documentación. No se asignó responsable.",
            ["actualizar el tablero", "validar la documentación"],
        ),
        "D-contexto-largo": (
            ("Contexto general del proyecto y antecedentes. " * 35)
            + "Pendientes: confirmar la fecha de pruebas y publicar el aviso de liberación.",
            ["confirmar la fecha de pruebas", "publicar el aviso de liberación"],
        ),
        "E-sin-pendientes": (
            "Minuta informativa. Se revisó el avance general, se compartieron métricas y se cerró la sesión sin acuerdos ni pendientes nuevos.",
            [],
        ),
    }


def call(client: httpx.Client, model: str, text: str, expected_terms: list[str], system_prompt: str,
         *, num_ctx: int, num_predict: int, keep_alive: str | int | None = None) -> dict:
    normalized, removed = normalize_text(text)
    payload = {
        "model": model, "stream": False, "think": False,
        "format": "json",
        "options": {"temperature": 0, "num_predict": num_predict, "num_ctx": num_ctx},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"document": normalized}, ensure_ascii=False)},
        ],
    }
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    started = time.perf_counter()
    try:
        response = client.post("/api/chat", json=payload)
        elapsed = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        body = response.json()
        content = body.get("message", {}).get("content")
        valid_json = isinstance(content, str)
        pydantic_valid = False
        activities = expected = omitted = invented = evidence_invalid = duplicates = 0
        raw_activity_count = raw_found = raw_evidence_invalid = raw_responsibles = raw_dates = raw_account_ids = raw_duplicates = 0
        raw_type = None
        raw_keys = []
        if valid_json:
            try:
                raw = json.loads(content)
                raw_type = type(raw).__name__
                raw_keys = list(raw.keys())[:20] if isinstance(raw, dict) else []
                raw_activities = raw.get("activities", []) if isinstance(raw, dict) else []
                if isinstance(raw_activities, list):
                    raw_activity_count = len(raw_activities)
                    searchable = " ".join(
                        f"{item.get('title', '')} {item.get('description', '')} {item.get('source_evidence', '')}"
                        for item in raw_activities if isinstance(item, dict)
                    ).casefold()
                    raw_found = sum(term.casefold() in searchable for term in expected_terms)
                    raw_evidence_invalid = sum(
                        1 for item in raw_activities if isinstance(item, dict)
                        and (not item.get("source_evidence") or item.get("source_evidence") not in normalized)
                    )
                    raw_responsibles = sum(1 for item in raw_activities if isinstance(item, dict) and item.get("responsible_candidate"))
                    raw_dates = sum(1 for item in raw_activities if isinstance(item, dict) and item.get("due_date_candidate"))
                    raw_account_ids = sum(1 for item in raw_activities if isinstance(item, dict) and item.get("accountId"))
                    signatures = [str(item.get("source_evidence", "")).casefold() for item in raw_activities if isinstance(item, dict)]
                    raw_duplicates = len(signatures) - len(set(signatures))
            except (ValueError, TypeError, AttributeError):
                pass
            try:
                doc = MinutesDocument.model_validate_json(content)
                pydantic_valid = True
                checked, _, notes = validate_extraction(doc, normalized)
                activities = len(checked.activities)
                evidence_invalid = 0
                duplicates = sum("duplicado" in warning.casefold() for warning_list in notes for warning in warning_list)
                # Counts are filled by the caller from the keyword ground truth.
                invented = sum(1 for item in checked.activities if item.responsible_candidate or item.due_date_candidate)
                searchable = " ".join(
                    f"{item.title} {item.description} {item.source_evidence}"
                    for item in checked.activities
                ).casefold()
                expected = len(expected_terms)
                found = sum(term.casefold() in searchable for term in expected_terms)
            except Exception as exc:  # validation result only; never print model output
                evidence_invalid = int(exc.__class__.__name__ == "MinutesError")
        return {
            "ok": True, "http": response.status_code, "ms": round(elapsed),
            "chars_original": len(text), "chars_normalized": len(normalized),
            "load_ms": round(body.get("load_duration", 0) / 1e6),
            "eval_tokens": body.get("eval_count"), "prompt_tokens": body.get("prompt_eval_count"),
            "json": valid_json, "pydantic": pydantic_valid, "activities": activities,
            "removed": removed, "invented": invented, "evidence_invalid": evidence_invalid,
            "duplicates": duplicates, "expected": len(expected_terms), "found": found if pydantic_valid else raw_found,
            "activities_raw": raw_activity_count, "evidence_invalid_raw": raw_evidence_invalid,
            "responsibles_raw": raw_responsibles, "dates_raw": raw_dates,
            "account_ids_raw": raw_account_ids, "duplicates_raw": raw_duplicates,
            "raw_type": raw_type, "raw_keys": raw_keys,
        }
    except (httpx.TimeoutException, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        response = getattr(exc, "response", None)
        return {"ok": False, "http": getattr(response, "status_code", None),
                "ms": round((time.perf_counter() - started) * 1000),
                "error": exc.__class__.__name__, "chars_original": len(text),
                "chars_normalized": len(normalized), "removed": removed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vic-path", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--quick", action="store_true", help="Cold/warm only for A; one warm pass for B-E")
    parser.add_argument("--only", action="append", help="Dataset key to run (repeatable)")
    parser.add_argument("--model", action="append", help="Model name to run (repeatable)")
    parser.add_argument("--warm-only", action="store_true", help="Run a single warm pass per selected dataset")
    parser.add_argument("--prompt-version", default="minutes-v1")
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--num-predict", type=int, default=4096)
    args = parser.parse_args()
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=args.timeout,
                      trust_env=False, follow_redirects=False) as client:
        prompt_version, system_prompt = prompt_for(args.prompt_version)
        tags = client.get("/api/tags").json().get("models", [])
        models = [item.get("name") or item.get("model") for item in tags]
        if args.model:
            models = [model for model in models if model in args.model]
        print(json.dumps({"models": models}, ensure_ascii=False), flush=True)
        for model in models:
            print(json.dumps({"model": model}, ensure_ascii=False), flush=True)
            selected = datasets(args.vic_path)
            if args.only:
                selected = {name: selected[name] for name in args.only if name in selected}
            for name, (text, expected_terms) in selected.items():
                # keep_alive=0 makes the first call a genuine cold-load measurement.
                if args.warm_only:
                    passes = [("warm", call(client, model, text, expected_terms, system_prompt,
                                             num_ctx=args.num_ctx, num_predict=args.num_predict))]
                else:
                    cold = call(client, model, text, expected_terms, system_prompt,
                                num_ctx=args.num_ctx, num_predict=args.num_predict, keep_alive=0)
                    passes = [("cold", cold)]
                    if not args.quick or name == "A-VIC-GIS-real-duplicada":
                        passes.append(("warm", call(client, model, text, expected_terms, system_prompt,
                                                     num_ctx=args.num_ctx, num_predict=args.num_predict)))
                for label, result in passes:
                    result["model"] = model
                    result["dataset"] = name
                    result["phase"] = label
                    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
