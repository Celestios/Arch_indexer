---
name: build-installer
description: >-
  Build standalone Windows executable (PyInstaller) and Inno Setup installer (ArchSetup.exe)
  for Arch MCP. Use when the user requests building the exe, installer, or distribution package.
---

# Build PyInstaller Exe and Inno Setup Installer

Two-stage build pipeline for Arch MCP distribution binaries.

## Prerequisites
- Virtual environment with PyInstaller: `.venv\Scripts\python.exe`
- Inno Setup 6 compiler: `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
- Spec file: `arch.spec`
- Inno Setup script: `installer.iss`

## Build Steps

### 1. Build PyInstaller Executable
Run PyInstaller using the virtual environment:
```powershell
.venv\Scripts\python.exe -m PyInstaller arch.spec --noconfirm
```
- Output: `dist\arch.exe`

### 2. Compile Inno Setup Installer
Compile `installer.iss` using Inno Setup 6 CLI compiler:
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```
- Output: `dist\ArchSetup.exe`

## Verification
Confirm generated binaries exist in `dist/`:
```powershell
Get-Item dist\arch.exe, dist\ArchSetup.exe | Select-Object Name, Length, LastWriteTime
```
