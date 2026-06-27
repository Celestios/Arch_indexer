import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

def download_file(
    url: str,
    dest_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    chunk_size: int = 1024 * 1024  # Default chunk size: 1MB
) -> Path:
    """
    Downloads a file supporting HTTP Range requests for resuming incomplete downloads.
    
    Args:
        url: Direct HTTP/HTTPS download link.
        dest_path: Target path where the final file should be stored.
        progress_callback: Optional callback receiving (bytes_downloaded, total_bytes).
        chunk_size: Read buffer chunk size.
        
    Returns:
        Path to the successfully downloaded file.
    """
    temp_path = dest_path.with_suffix(".tmp")
    
    # Check current downloaded size to prepare for resume
    initial_pos = 0
    if temp_path.exists():
        initial_pos = temp_path.stat().st_size
    
    req = urllib.request.Request(url)
    if initial_pos > 0:
        req.add_header("Range", f"bytes={initial_pos}-")
        
    try:
        # Establish connection using a browser-like User-Agent
        opener = urllib.request.build_opener()
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")]
        urllib.request.install_opener(opener)
        
        with urllib.request.urlopen(req) as response:
            status = response.getcode()
            
            # 206 Partial Content: Server accepted the Range header and resumes
            # 200 OK: Server rejected/ignored the Range header, starting from scratch
            mode = "ab" if status == 206 else "wb"
            if status == 200:
                initial_pos = 0
                
            content_length = response.getheader("Content-Length")
            total_size = (int(content_length) if content_length else 0) + initial_pos
            
            # Trigger initial callback
            if progress_callback:
                progress_callback(initial_pos, total_size)
            
            with open(temp_path, mode) as f:
                downloaded = initial_pos
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback:
                        progress_callback(downloaded, total_size)
                    sys.stdout.flush()
                    
        # Atomic rename once download completes successfully
        if dest_path.exists():
            dest_path.unlink()
        temp_path.rename(dest_path)
        
    except Exception as e:
        # We preserve the temp_path so it can be resumed next time
        raise RuntimeError(f"Download failed for {url}: {e}")
        
    return dest_path
