# EMSphInx Studio

EMSphInx Studio is a graphical interface for spherical indexing of EDAX (`.edaxh5` + `.up1`) and Oxford Instruments (`.h5oina`) EBSD datasets with [EMSphInx](https://github.com/EMsoft-org/EMSphInx).

The Studio detects the host operating system at startup and selects the appropriate execution method:

| Host | Where `IndexEBSD` runs | Paths written to NML files | Network storage |
| --- | --- | --- | --- |
| Windows | Inside the configured WSL distribution | Windows paths are translated to WSL paths | Configured UNC shares can be mounted automatically with `drvfs` |
| macOS | Directly on macOS as a native executable | Native absolute macOS paths | Shares must already be mounted by macOS, normally under `/Volumes` |

The viewers, NML builders, Oxford-to-UP1 conversion, job queue, progress display, and SHT library management are shared by both platforms.

## Windows / WSL

### Requirements

- Windows with WSL 2.
- A WSL Linux distribution such as Debian.
- EMSphInx installed or compiled inside WSL, including the Linux `IndexEBSD` executable.
- Python 3.8+ on Windows with Tkinter.

The Windows application does not run a Windows build of `IndexEBSD`. It launches the Linux executable inside WSL.

### Install and launch the Studio

From PowerShell in the EMSphInx Studio directory:

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

### Configure WSL execution

Open **Settings > EMSphInx Configuration (Windows / WSL)** and configure:

1. **WSL Distro**: the distribution containing EMSphInx, for example `Debian`.
2. **EMSphInx Executable Dir**: the WSL directory containing `IndexEBSD`, for example `/mnt/c/Software/EMSphInx`.
3. **Drive Mappings**: mappings such as `C:` to `/mnt/c`. These convert paths selected by the Windows GUI into paths accessible inside WSL.
4. **Network Mounts**: optional UNC shares that the Studio should mount inside WSL using `drvfs`.

Configure mappings before generating NML files because Windows-generated NML files contain WSL paths. Existing WSL configuration keys and per-user configuration files remain supported.

## macOS

### Requirements

- macOS with Python 3.8+ and a modern Tkinter installation.
- EMSphInx compiled for macOS, including a native `IndexEBSD` executable.

The macOS application does not use WSL and does not translate paths. It launches the native macOS executable directly.

### Install and launch the Studio

With Homebrew Python 3.12:

```bash
brew install python@3.12 python-tk@3.12
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

Do not launch the Studio with `/usr/bin/python3`. Apple's bundled Python uses an obsolete system Tk and can abort with a misleading `macOS ... or later required` message.

### Configure native execution

1. Build EMSphInx for macOS and locate the directory containing `IndexEBSD`.
2. Start the Studio with `.venv/bin/python main.py`.
3. On first launch, select the directory containing `IndexEBSD`. It can be changed later under **Settings > EMSphInx Configuration (macOS)**.
4. If necessary, make the executable runnable:

   ```bash
   chmod +x /path/to/EMSphInx/IndexEBSD
   ```

Data, SHT, output, and NML paths are passed directly to `IndexEBSD` as native absolute macOS paths. Network shares must already be mounted by macOS before a job starts; Finder-mounted shares are normally available under `/Volumes`.

## Shared workflow

1. Choose EDAX or Oxford mode.
2. Load and inspect the data in the pattern viewer. Shift-drag defines an optional indexing ROI.
3. Select or fetch SHT master patterns and generate the NML in the NML Builder.
4. Start the queue and monitor the live `IndexEBSD` output.

Oxford `.h5oina` patterns are unpacked asynchronously to `.up1` because direct indexing of the packed source has proved unreliable. Optional integer binning uses fast block averaging without interpolation. Non-divisible dimensions are center-cropped first, and the generated NML uses the corresponding output dimensions, effective pixel size, and corrected pattern center. The writer processes large datasets in bounded chunks.

## Moving jobs between platforms

NML files contain platform-specific absolute paths:

- NML files generated on Windows contain WSL paths such as `/mnt/c/...`.
- NML files generated on macOS contain native paths such as `/Users/...` or `/Volumes/...`.

When moving a job between Windows/WSL and macOS, regenerate its NML on the destination system or update every referenced path.
