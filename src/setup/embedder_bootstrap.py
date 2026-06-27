import sys
from pathlib import Path
from setup.downloader import download_file


def make_progress_callback(filename: str):
    def callback(downloaded: int, total_size: int):
        percent = (downloaded / total_size) * 100 if total_size else 0
        print(f"[{filename}] Downloaded: {downloaded}/{total_size} ({percent:.2f}%)")
        sys.stdout.flush()
    return callback

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
        if not model_path.exists():
            print(f"Resolving ONNX model download...")
            download_file(MODEL_URL, model_path, progress_callback=make_progress_callback("model.onnx"))
        if not tokenizer_path.exists():
            print(f"Resolving tokenizer download...")
            download_file(TOKENIZER_URL, tokenizer_path, progress_callback=make_progress_callback("tokenizer.json"))
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
