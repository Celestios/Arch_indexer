import sys
import shutil
import zipfile
from pathlib import Path
from setup.downloader import download_file

def make_progress_callback(filename: str):
    def callback(downloaded: int, total_size: int):
        percent = (downloaded / total_size) * 100 if total_size else 0
        print(f"[{filename}] Downloaded: {downloaded}/{total_size} ({percent:.2f}%)")
        sys.stdout.flush()
    return callback

def bootstrap_codeql(bin_dir: Path, progress_callback = None) -> Path:
    """Downloads and extracts the CodeQL CLI binary for Windows, caching the download in the archive directory."""
    codeql_dir = bin_dir / "codeql"
    codeql_exe = codeql_dir / "codeql.exe"

    if codeql_exe.exists():
        print("CodeQL CLI is already installed locally.")
        return codeql_exe

    bin_dir.mkdir(parents=True, exist_ok=True)
    
    archive_dir = bin_dir.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    zip_path = archive_dir / "codeql.zip"
    old_zip_path = bin_dir / "codeql.zip"

    # Migrate from bin/ to archive/ if it exists from previous setup runs
    if old_zip_path.exists() and not zip_path.exists():
        try:
            print("Migrating codeql.zip from bin/ to archive/...")
            old_zip_path.rename(zip_path)
        except Exception:
            pass

    CODEQL_URL = "https://github.com/github/codeql-cli-binaries/releases/latest/download/codeql-win64.zip"

    # Check if a valid cached zip file exists
    use_cached = False
    if zip_path.exists():
        try:
            print("Checking cached CodeQL CLI zip file...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # Fast check: reading directory headers
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
        # Extract Zip file
        if codeql_dir.exists():
            shutil.rmtree(codeql_dir)
        print(f"Extracting CodeQL CLI to {bin_dir}...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(bin_dir)
        print("CodeQL CLI successfully bootstrapped.")
    except Exception as e:
        # If extraction fails, clean up partially extracted files but keep the zip file
        if codeql_dir.exists():
            try:
                shutil.rmtree(codeql_dir)
            except Exception:
                pass
        raise RuntimeError(f"Failed to extract CodeQL CLI: {e}")

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
