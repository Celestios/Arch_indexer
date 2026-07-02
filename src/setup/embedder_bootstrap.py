import sys
import argparse
from pathlib import Path
from setup.downloader import download_file
from utils.progress import make_progress_callback

# Defined list of available models, their HuggingFace locations, and dimensions
EMBEDDING_MODELS = {
    "1": {
        "name": "all-MiniLM-L6-v2 (Default - Light & Fast, ~90MB, 384 dims)",
        "model_url": "https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/resolve/main/model.onnx",
        "tokenizer_url": "https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx/resolve/main/tokenizer.json"
    },
    "2": {
        "name": "bge-small-en-v1.5 (High Performance, ~130MB, 384 dims)",
        "model_url": "https://huggingface.co/Xenova/bge-small-en-v1.5/resolve/main/onnx/model.onnx",
        "tokenizer_url": "https://huggingface.co/Xenova/bge-small-en-v1.5/resolve/main/tokenizer.json"
    },
    "3": {
        "name": "all-mpnet-base-v2 (Maximum Accuracy, ~430MB, 768 dims)",
        "model_url": "https://huggingface.co/Xenova/all-mpnet-base-v2/resolve/main/onnx/model.onnx",
        "tokenizer_url": "https://huggingface.co/Xenova/all-mpnet-base-v2/resolve/main/tokenizer.json"
    }
}

def bootstrap_onnx_model(target_dir: Path, model_choice: str = "1") -> tuple[Path, Path]:
    """Downloads the chosen ONNX embedding model assets to the target folder."""
    if model_choice == "4":
        print("Skipping embedding model download by request.")
        return Path(), Path()

    if model_choice not in EMBEDDING_MODELS:
        print(f"Warning: Invalid model choice '{model_choice}'. Defaulting to '1'.", file=sys.stderr)
        model_choice = "1"

    model_info = EMBEDDING_MODELS[model_choice]
    model_path = target_dir / "model.onnx"
    tokenizer_path = target_dir / "tokenizer.json"

    # If assets exist already, check if they are for this model or if we want to overwrite
    # Note: For simplicity, if they exist we assume they are valid unless forced
    if model_path.exists() and tokenizer_path.exists():
        print(f"ONNX Model assets are already present at {target_dir}.")
        return model_path, tokenizer_path

    target_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Selected Model: {model_info['name']}")
    try:
        if not model_path.exists():
            print(f"Resolving model.onnx download...")
            download_file(model_info["model_url"], model_path, progress_callback=make_progress_callback("model.onnx"))
        if not tokenizer_path.exists():
            print(f"Resolving tokenizer.json download...")
            download_file(model_info["tokenizer_url"], tokenizer_path, progress_callback=make_progress_callback("tokenizer.json"))
    except Exception as e:
        raise RuntimeError(f"Failed to download embedding model: {e}")

    return model_path, tokenizer_path

def prompt_user_choice() -> str:
    """Prompts the user interactively on console to choose a model."""
    print("\n--- ONNX Embedding Model Selection ---")
    for key, val in EMBEDDING_MODELS.items():
        print(f" [{key}] {val['name']}")
    print(" [4] Skip downloading / local model already present")
    
    try:
        # Check if stdin is interactive
        if not sys.stdin.isatty():
            print("\nNon-interactive session. Defaulting to choice [1].")
            return "1"
            
        choice = input("\nEnter choice [1-4] (default: 1): ").strip()
        if not choice:
            return "1"
        return choice
    except (KeyboardInterrupt, EOFError):
        print("\nDefaulting to choice [1] due to interruption.")
        return "1"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap ONNX Embedding Model")
    parser.add_argument(
        "--model", 
        type=str, 
        choices=["1", "2", "3", "4"], 
        help="ONNX embedding model to download: 1 (MiniLM), 2 (BGE), 3 (MPNet), 4 (Skip)"
    )
    parser.add_argument(
        "--non-interactive", 
        action="store_true", 
        help="Run without interactive console prompt (uses default if no model specified)"
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    target = project_root / "bin" / "models"
    
    choice = args.model
    if not choice:
        if args.non-interactive:
            choice = "1"
        else:
            choice = prompt_user_choice()
            
    try:
        bootstrap_onnx_model(target, choice)
        if choice != "4":
            print("ONNX Model successfully bootstrapped.")
    except Exception as err:
        print(f"Error bootstrapping ONNX Model: {err}", file=sys.stderr)
        sys.exit(1)
