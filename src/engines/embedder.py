import sys
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

class LocalEmbedder:
    """
    Wraps the local ONNX embedding model (all-MiniLM-L6-v2) for generating
    normalized vector embeddings of code symbols.
    """

    def __init__(self, bin_dir: Path):
        """Loads the ONNX model session and Tokenizer from the local bin folder."""
        self.bin_dir = bin_dir
        model_path = bin_dir / "models" / "model.onnx"
        tokenizer_path = bin_dir / "models" / "tokenizer.json"

        if not model_path.exists() or not tokenizer_path.exists():
            raise FileNotFoundError(
                f"Embedding model files not found at {model_path.parent}. "
                "Ensure setup has been run successfully."
            )

        try:
            self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        except Exception as e:
            raise RuntimeError(f"Failed to load tokenizer: {e}")

        # Set graph optimization level
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        try:
            self.session = ort.InferenceSession(str(model_path), sess_options=opts)
        except Exception as e:
            raise RuntimeError(f"ONNX Session compilation failed: {e}")

    def embed(self, text: str) -> list[float]:
        """
        Encodes source text, executes inference, and applies vectorized mean pooling
        with L2 normalization.
        """
        self.tokenizer.enable_truncation(max_length=512)

        try:
            encoding = self.tokenizer.encode(text)
        except Exception as e:
            raise RuntimeError(f"Tokenizer encoding failed: {e}")

        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
        token_type_ids = np.array([encoding.type_ids], dtype=np.int64)

        try:
            outputs = self.session.run(None, {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids
            })
        except Exception as e:
            raise RuntimeError(f"ONNX inference execution failed: {e}")

        embeddings_data = outputs[0]

        if embeddings_data.ndim != 3 or embeddings_data.shape[2] not in (384, 768):
            raise ValueError(
                "Output tensor shape deviates from the expected 384 or 768-dimensional space."
            )

        # Mean pooling along the sequence dimension axis (axis 1)
        pooled = np.mean(embeddings_data, axis=1)[0]

        # L2 Normalization
        norm = np.linalg.norm(pooled)
        if norm > 0.0:
            pooled = pooled / norm

        return pooled.tolist()
