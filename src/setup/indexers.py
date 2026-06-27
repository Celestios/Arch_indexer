import os
import sys
import shutil
import urllib.request
import zipfile
import subprocess
import tempfile
from pathlib import Path

def download_file_with_resume(url: str, dest_path: Path):
    """Downloads a file supporting HTTP Range requests for resuming incomplete downloads."""
    temp_path = dest_path.with_suffix(".tmp")
    
    # Check current downloaded size
    initial_pos = 0
    if temp_path.exists():
        initial_pos = temp_path.stat().st_size
        print(f"Found existing partial download of size {initial_pos} bytes. Resuming...")
    
    req = urllib.request.Request(url)
    if initial_pos > 0:
        req.add_header("Range", f"bytes={initial_pos}-")
        
    try:
        opener = urllib.request.build_opener()
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")]
        urllib.request.install_opener(opener)
        
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            
            # 206 Partial Content means the server accepted the Range header
            # 200 OK means the server ignored Range and is sending the whole file from start
            mode = "ab" if status == 206 else "wb"
            if status == 200:
                print("Server does not support resume. Downloading from start...")
                initial_pos = 0
                
            content_length = response.getheader("Content-Length")
            total_size = (int(content_length) if content_length else 0) + initial_pos
            print(f"Downloading: {initial_pos}/{total_size} bytes...")
            
            with open(temp_path, mode) as f:
                chunk_size = 1024 * 1024  # 1MB chunks
                downloaded = initial_pos
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    percent = (downloaded / total_size) * 100 if total_size else 0
                    print(f"Downloaded: {downloaded}/{total_size} ({percent:.2f}%)")
                    sys.stdout.flush()
                    
        # Rename temp file to final destination once done
        if dest_path.exists():
            dest_path.unlink()
        temp_path.rename(dest_path)
        print("Download complete.")
    except Exception as e:
        print(f"Download failed: {e}")
        raise e

def bootstrap_codeql(bin_dir: Path) -> Path:
    """Downloads and extracts the CodeQL CLI binary for Windows, caching the download."""
    codeql_dir = bin_dir / "codeql"
    codeql_exe = codeql_dir / "codeql" / "codeql.exe"

    if codeql_exe.exists():
        print("CodeQL CLI is already installed locally.")
        return codeql_exe

    bin_dir.mkdir(parents=True, exist_ok=True)
    zip_path = bin_dir / "codeql.zip"
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
            download_file_with_resume(CODEQL_URL, zip_path)
        except Exception as e:
            raise RuntimeError(f"Failed to download CodeQL CLI: {e}")

    try:
        # Extract Zip file
        if codeql_dir.exists():
            shutil.rmtree(codeql_dir)
        print(f"Extracting CodeQL CLI to {codeql_dir}...")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(codeql_dir)
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



def bootstrap_scip(bin_dir: Path) -> Path:
    """Compiles the SCIP CLI from source using Go and places it in the bin folder."""
    scip_exe = bin_dir / "scip.exe"

    if scip_exe.exists():
        print("SCIP CLI is already compiled locally.")
        return scip_exe

    go_path = shutil.which("go")
    if not go_path:
        print("Go not found. Skipping optional SCIP CLI local compilation.")
        return scip_exe

    print("Bootstrapping SCIP CLI (compiling from source)...")
    bin_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        try:
            # Clone SCIP repository
            print("Cloning scip-code/scip repository...")
            subprocess.run(
                ["git", "clone", "https://github.com/scip-code/scip.git", "--depth", "1", str(temp_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Build binary using Go
            print("Compiling SCIP CLI using Go...")
            subprocess.run(
                ["go", "build", "-o", str(scip_exe), "./cmd/scip"],
                cwd=str(temp_path),
                check=True
            )
            print("SCIP CLI successfully compiled.")
        except Exception as e:
            if scip_exe.exists():
                scip_exe.unlink()
            raise RuntimeError(f"Failed to compile SCIP: {e}")

    return scip_exe


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent.parent
    bin_folder = project_root / "bin"
    
    # Bootstrap CodeQL
    try:
        bootstrap_codeql(bin_folder)
    except Exception as err:
        print(f"Error: {err}", file=sys.stderr)

    # Bootstrap SCIP
    try:
        bootstrap_scip(bin_folder)
    except Exception as err:
        print(f"Error: {err}", file=sys.stderr)
