import os
import sys
import shutil
import zipfile
import tempfile
from pathlib import Path
from setup.downloader import download_file
from utils.progress import make_progress_callback


def _get_archive_dir() -> Path:
    """Get a user-writable archive directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path.home() / ".cache"
    return base / "arch-mcp" / "archive"


def _ensure_codeql_cli_binary(bin_dir: Path, progress_callback=None) -> Path:
    """Download and extract the CodeQL CLI binary if not already present."""
    codeql_dir = bin_dir / "codeql"
    codeql_exe = codeql_dir / "codeql.exe"

    if codeql_exe.exists():
        print("CodeQL CLI is already installed locally.")
        return codeql_exe

    CODEQL_URL = "https://github.com/github/codeql-cli-binaries/releases/latest/download/codeql-win64.zip"

    archive_dir = _get_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    zip_path = archive_dir / "codeql.zip"
    old_zip_path = bin_dir / "codeql.zip"

    if old_zip_path.exists() and not zip_path.exists():
        try:
            print("Migrating codeql.zip from bin/ to archive/...")
            old_zip_path.rename(zip_path)
        except Exception:
            pass

    use_cached = False
    if zip_path.exists():
        try:
            print("Checking cached CodeQL CLI zip file...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                _ = zip_ref.namelist()
                use_cached = True
                print("Cached CodeQL CLI zip file is valid.")
        except Exception:
            print("Cached zip file is corrupted/incomplete. Renaming to tmp to resume...")
            temp_path = zip_path.with_suffix(".tmp")
            if not temp_path.exists():
                try:
                    zip_path.rename(temp_path)
                except Exception:
                    pass

    if not use_cached:
        try:
            cb = progress_callback if progress_callback else make_progress_callback("codeql.zip")
            download_file(CODEQL_URL, zip_path, progress_callback=cb)
        except Exception as e:
            raise RuntimeError(f"Failed to download CodeQL CLI: {e}")

    try:
        if codeql_dir.exists():
            shutil.rmtree(codeql_dir)
        print(f"Extracting CodeQL CLI to {bin_dir}...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(bin_dir)
        print("CodeQL CLI successfully bootstrapped.")
    except Exception as e:
        if codeql_dir.exists():
            try:
                shutil.rmtree(codeql_dir)
            except Exception:
                pass
        raise RuntimeError(f"Failed to extract CodeQL CLI: {e}")

    return codeql_exe


def bootstrap_codeql(bin_dir: Path, progress_callback=None) -> Path:
    """Downloads and extracts the CodeQL CLI binary for Windows, caching the download in the archive directory."""
    return _ensure_codeql_cli_binary(bin_dir, progress_callback)


CODEQL_PACK_MAP = {
    "python": "codeql/python-all",
    "rust": "codeql/rust-all",
    "go": "codeql/go-all",
    "java": "codeql/java-all",
    "javascript": "codeql/javascript-all",
    "csharp": "codeql/csharp-all",
    "cpp": "codeql/cpp-all",
}


def download_codeql_packs(bin_dir: Path, languages: list) -> None:
    """Download CodeQL language packs for the specified languages."""
    codeql_exe = bin_dir / "codeql" / "codeql.exe"
    if not codeql_exe.exists():
        system_path = shutil.which("codeql")
        if system_path:
            codeql_exe = Path(system_path)
        else:
            print("[CodeQL] CLI not found, skipping pack download.")
            return

    packs_to_install = [CODEQL_PACK_MAP[l] for l in languages if l in CODEQL_PACK_MAP]
    if not packs_to_install:
        return

    print(f"[CodeQL] Downloading packs: {', '.join(packs_to_install)}...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        qlpack_path = Path(tmp_dir) / "qlpack.yml"
        deps = "\n".join(f"  {p}: \"*\"" for p in packs_to_install)
        qlpack_path.write_text(
            f"name: arch-pack-setup\nversion: 1.0.0\ndependencies:\n{deps}\n",
            encoding="utf-8"
        )

        res = __import__("subprocess").run(
            [str(codeql_exe), "pack", "install"],
            cwd=tmp_dir,
            shell=(sys.platform == "win32"),
            capture_output=True,
            text=True
        )
        if res.returncode == 0:
            print(f"[CodeQL] Packs downloaded successfully.")
        else:
            print(f"[CodeQL] Warning: pack download failed: {res.stderr}", file=sys.stderr)

    return codeql_exe
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bootstrap CodeQL indexer")
    parser.add_argument("--skip-codeql", action="store_true", help="Skip CodeQL CLI setup")
    parser.add_argument("--non-interactive", action="store_true", help="Run without interactive prompts")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    bin_folder = project_root / "bin"

    setup_codeql = not args.skip_codeql

    # If interactive, prompt the user to confirm choices
    if not args.non-interactive and sys.stdin.isatty():
        print("\n--- CodeQL CLI Setup Configuration ---")
        try:
            cql_ans = input("Setup CodeQL CLI? [Y/n]: ").strip().lower()
            setup_codeql = cql_ans not in ("n", "no")
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled or interrupted. Defaulting to setup CodeQL CLI.")
            setup_codeql = True

    # Bootstrap CodeQL
    if setup_codeql:
        try:
            bootstrap_codeql(bin_folder)
        except Exception as err:
            print(f"Error bootstrapping CodeQL: {err}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Skipping CodeQL CLI setup.")
