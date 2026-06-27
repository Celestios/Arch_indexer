import sys
import urllib.request
from pathlib import Path

def bootstrap_onnx_model(target_dir: Path) -> tuple[Path, Path]:
    """Downloads the ONNX embedding model assets (model.onnx, tokenizer.json) to the target folder."""
    model_path = target_dir / "model.onnx"
    tokenizer_path = target_dir / "tokenizer.json"

    if model_path.exists() and tokenizer_path.exists():
        return model_path, tokenizer_path

    target_dir.mkdir(parents=True, exist_ok=True)
    MODEL_URL = "https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/resolve/main/model.onnx"
    TOKENIZER_URL = "https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/resolve/main/tokenizer.json"

    try:
        # Use an opener with a browser-like User-Agent to avoid blocks or throttling
        opener = urllib.request.build_opener()
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")]
        urllib.request.install_opener(opener)

        if not model_path.exists():
            print(f"Downloading ONNX model to {model_path} (one-time operation)...")
            urllib.request.urlretrieve(MODEL_URL, model_path)
        if not tokenizer_path.exists():
            print(f"Downloading tokenizer to {tokenizer_path}...")
            urllib.request.urlretrieve(TOKENIZER_URL, tokenizer_path)
    except Exception as e:
        raise RuntimeError(f"Failed to download embedding model: {e}")

    return model_path, tokenizer_path

if __name__ == "__main__":
    # If run directly, bootstrap into the local bin/models folder
    project_root = Path(__file__).parent.parent.parent
    target = project_root / "bin" / "models"
    try:
        bootstrap_onnx_model(target)
        print("ONNX Model successfully bootstrapped.")
    except Exception as err:
        print(f"Error bootstrapping ONNX Model: {err}", file=sys.stderr)
        sys.exit(1)
