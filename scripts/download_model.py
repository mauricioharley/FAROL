import os
from pathlib import Path
from huggingface_hub import hf_hub_download

repo = os.environ.get("MODEL_REPO", "Qwen/Qwen3-4B-GGUF")
filename = os.environ.get("MODEL_FILE", "Qwen3-4B-Q4_K_M.gguf")
target = Path("/models") / filename

if target.exists() and target.stat().st_size > 0:
    print(f"Model already present: {target}")
else:
    print(f"Downloading {repo}/{filename} to /models ...")
    path = hf_hub_download(
        repo_id=repo,
        filename=filename,
        local_dir="/models",
    )
    print(f"Downloaded: {path}")
