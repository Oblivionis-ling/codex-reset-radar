"""Explicit fixed-revision download. Not called by Backend or worker startup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="convaiinnovations/laya")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--http-download", action="store_true", help="Use official download=true CDN with SHA256 verification")
    args = parser.parse_args()
    if len(args.revision) != 40 or any(c not in "0123456789abcdef" for c in args.revision):
        parser.error("revision must be a full immutable commit SHA")
    root = args.root.resolve()
    os.environ["HF_HOME"] = str(root / "cache" / "huggingface")
    from huggingface_hub import snapshot_download, HfApi
    files = ["rl_agent_config.json", "model.safetensors", "encoder/config.json",
             "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"]
    snapshot = Path(snapshot_download(args.checkpoint, revision=args.revision,
                                     allow_patterns=[f for f in files if not args.http_download or f != 'model.safetensors'] + ["LICENSE", "README.md"],
                                     cache_dir=str(root / "cache" / "huggingface")))
    if args.http_download and not (snapshot / 'model.safetensors').exists():
        import requests
        info = HfApi().model_info(args.checkpoint, revision=args.revision, files_metadata=True)
        weight = next(s for s in info.siblings if s.rfilename == 'model.safetensors')
        expected = weight.lfs.sha256
        partial = root / 'cache' / f'{args.revision}.safetensors.partial'
        started = time.monotonic()
        url = f'https://huggingface.co/{args.checkpoint}/resolve/{args.revision}/model.safetensors?download=true'
        with requests.get(url, stream=True, timeout=(15, 30)) as response:
            response.raise_for_status()
            actual = hashlib.sha256()
            size = 0
            with partial.open('wb') as stream:
                for chunk in response.iter_content(1024 * 1024):
                    if time.monotonic() - started > 1200:
                        raise TimeoutError('MODEL_DOWNLOAD_TIME_BUDGET')
                    stream.write(chunk)
                    actual.update(chunk)
                    size += len(chunk)
                    if size % (32 * 1024 * 1024) == 0:
                        print(f'Downloaded {size} bytes', flush=True)
        if size != weight.size or actual.hexdigest() != expected:
            raise ValueError('OFFICIAL_WEIGHT_HASH_MISMATCH')
        partial.replace(snapshot / 'model.safetensors')
    effective = root / "models" / (args.checkpoint.split("/")[-1] + "-" + args.revision[:12])
    if effective.exists():
        raise SystemExit("Effective model path exists; refusing to overwrite")
    original_hashes = {}
    effective_hashes = {}
    for name in files:
        src = snapshot / name
        dst = effective / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as stream:
            original_hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
        # Keep mutable tokenizer config separate from immutable HF snapshot.
        # Other assets are hardlinked (same volume) to avoid duplicate weight space.
        if name == "tokenizer/tokenizer_config.json":
            config = json.loads(src.read_text(encoding="utf-8"))
            if config.get("tokenizer_class") in (None, "TokenizersBackend"):
                config["tokenizer_class"] = "PreTrainedTokenizerFast"
            config.pop("backend", None)
            config.pop("is_local", None)
            if isinstance(config.get("extra_special_tokens"), list):
                config["extra_special_tokens"] = {f'extra_{i}': token for i, token in enumerate(config['extra_special_tokens'])}
            dst.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            try:
                os.link(src.resolve(), dst)
            except OSError:
                shutil.copyfile(src, dst)
        with dst.open("rb") as stream:
            effective_hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = dict(checkpoint=args.checkpoint, revision=args.revision,
                    source_sha256=original_hashes, effective_sha256=effective_hashes,
                    immutable_snapshot=str(snapshot), tokenizer_compatibility="laya-0.3.5")
    (effective / "crr-model-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(effective)


if __name__ == "__main__":
    main()
