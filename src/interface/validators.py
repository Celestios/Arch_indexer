from typing import Optional, List, Union


def validate_filepaths(filepaths: Union[List[str], str]) -> List[str]:
    """Normalize and parse filepaths from various input formats."""
    if isinstance(filepaths, str):
        if "," in filepaths:
            return [p.strip() for p in filepaths.split(",") if p.strip()]
        else:
            return [filepaths.strip()]
    return list(filepaths)


def resolve_filepath(repository, raw_path: str) -> Optional[str]:
    """Resolve a raw filepath against the database using exact match then suffix matching."""
    file_info = repository.files.get_file(raw_path)
    if file_info:
        return raw_path
    all_files = repository.files.get_all_files_metadata()
    for real_fp in all_files.keys():
        if real_fp.replace("\\", "/").endswith(raw_path.replace("\\", "/")):
            return real_fp
    return None
