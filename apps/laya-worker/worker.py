"""Private newline-JSON worker. No HTTP listener, downloads, or notifications."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time


def preflight(agent, state, questions):
    """Match SDK 0.3.5 tokenization; reject *any* SDK truncation."""
    from laya.common import render_options, serialize_state
    tok = agent.tok
    count = lambda s: len(tok(s.replace(tok.mask_token, " "), add_special_tokens=False)["input_ids"])
    state_tokens = count(serialize_state(state))
    output = {}
    for key, definition in questions.items():
        q = agent._to_internal(definition)
        head = count(f"{q['t']} question: {q['ins']}")
        options = [count(" " + option) for option in render_options(q)]
        option_total = sum(n + 1 for n in options)
        budget = agent.cfg.get("head_max_len", 192) - option_total
        total = 4 + head + option_total + state_tokens
        truncated = (any(n > 48 for n in options) or budget < 16
                     or head > max(8, budget) or total > agent.cfg.get("max_len", 512))
        output[key] = dict(question_tokens=head, option_tokens=option_total,
                           state_tokens=state_tokens, total_tokens=total, truncated=truncated)
    return output


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def main():
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      TOKENIZERS_PARALLELISM="false")
    path = Path(sys.argv[1]).resolve(strict=True)
    manifest = json.loads((path / "crr-model-manifest.json").read_text(encoding="utf-8"))
    started = time.monotonic()
    if importlib.metadata.version('laya') != '0.3.5':
        raise ValueError('SDK_VERSION_MISMATCH')
    # Verify every effective asset before SDK code can load it or mutate configs.
    for relative, expected in manifest["effective_sha256"].items():
        candidate = (path / relative).resolve(strict=True)
        if not candidate.is_relative_to(path):
            raise ValueError("MODEL_PATH_ESCAPE")
        with candidate.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("MODEL_HASH_MISMATCH")
    for required in ("model.safetensors", "rl_agent_config.json", "encoder/config.json",
                     "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"):
        if required not in manifest["effective_sha256"]:
            raise ValueError("MODEL_ASSET_MISSING")
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import laya
        import psutil
        torch.set_num_threads(max(1, min(4, int(sys.argv[3]))))
        torch.set_num_interop_threads(1)
        agent = laya.load(str(path), device=sys.argv[2])
    identity = dict(checkpoint=manifest["checkpoint"], revision=manifest["revision"],
                    sdk="0.3.5", device=str(agent.device), dtype=str(agent.dtype),
                    torch=torch.__version__, transformers=importlib.metadata.version('transformers'),
                    model_sha256=manifest['effective_sha256']['model.safetensors'],
                    threads=torch.get_num_threads(),
                    cold_seconds=time.monotonic() - started)
    emit(dict(status="READY", identity=identity))
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            questions = request["questions"]
            if not isinstance(questions, dict) or not 1 <= len(questions) <= 5:
                raise ValueError("INVALID_QUESTIONS")
            budget = preflight(agent, request["state"], questions)
            if any(item["truncated"] for item in budget.values()):
                emit(dict(id=request_id, error="INPUT_TOO_LONG", tokens=budget))
                continue
            started = time.monotonic()
            with contextlib.redirect_stdout(sys.stderr):
                result = agent.predict(request["state"], questions)
            emit(dict(id=request_id, result=result, tokens=budget, identity=identity,
                      elapsed_seconds=time.monotonic() - started,
                      rss_bytes=psutil.Process().memory_info().rss))
        except Exception as error:
            # Never send exception strings containing input bodies or local credentials.
            emit(dict(id=request_id, error=type(error).__name__))


if __name__ == "__main__":
    main()
