# EMSphInx Studio

EMSphInx Studio is a graphical interface for spherical indexing of EDAX (`.edaxh5` + `.up1`) and Oxford Instruments (`.h5oina`) EBSD datasets with [EMSphInx](https://github.com/EMsoft-org/EMSphInx).

The Studio runs on Windows and macOS. On Windows, it uses Debian through Windows Subsystem for Linux (WSL) to run the EMSphInx indexing program, `IndexEBSD`. On macOS, it runs a native macOS build. The viewers, job queue, and other tools work the same way on both platforms.

## Windows / WSL

### 1. Install Debian / WSL

On Windows 11 or Windows 10 version 2004 (build 19041) or later, open **PowerShell as administrator** (right-click PowerShell and choose **Run as administrator**) and run:

```powershell
wsl --install -d Debian
```

This installs WSL and Debian. Restart the PC if prompted, then open **Debian** from the Start menu and complete the first-time setup by choosing a Linux username and password. You can then close the Debian window; the Studio starts WSL when needed. If Debian is already installed and set up, skip this step.

For installation help, see [Microsoft's WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).

### 2. Put the EMSphInx binaries in a folder

Extract the **precompiled Debian EMSphInx binaries** into a folder on your PC, for example:

```text
C:\Software\EMSphInx
```

Keep the supplied files together and locate the folder containing `IndexEBSD`. You do not need to compile EMSphInx or copy it into Debian's own filesystem. WSL can access the files directly from your Windows drive.

For example, if the executable is `C:\Software\EMSphInx\IndexEBSD`, its folder is `/mnt/c/Software/EMSphInx` inside WSL. A folder on `D:` uses `/mnt/d/` instead. If the archive has an extra subfolder containing `IndexEBSD`, use that subfolder.

### 3. Install and launch the Studio

Install standard **64-bit Python 3.13 for Windows**, including Tkinter (included with the standard Python installer), from the [Python Windows downloads](https://www.python.org/downloads/windows/) page. Download or clone this repository into a folder such as `C:\Software\EMSphInx_Studio`. Use a path without spaces, as EMSphInx has trouble reading multiple master patterns from paths containing spaces.

Select Python 3.13 explicitly: newer Python versions can arrive before compatible prebuilt packages are available. In particular, Python 3.15 can cause `h5py` to compile from source and fail with a missing `hdf5.dll` error. The commands below require prebuilt packages so installation does not attempt to compile HDF5 dependencies.

Open a regular **PowerShell** window in the EMSphInx Studio folder and run:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

For later launches, run only `.\.venv\Scripts\python.exe main.py` from the same folder.

If installation has already failed with `Failed building wheel for h5py` or a missing `hdf5.dll`, install Python 3.13 as above and create a fresh environment from the Studio folder:

```powershell
py -3.13 -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install --upgrade pip
.\.venv313\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv313\Scripts\python.exe main.py
```

This leaves the old environment intact. Use `.\.venv313\Scripts\python.exe main.py` for subsequent launches after this recovery. Installing another Python version does not change the Python version of an existing virtual environment; use the fresh environment rather than reusing one created with Python 3.15. Prebuilt `h5py` packages include HDF5, so this installation does not require a separate HDF5 installation or a compiler.

### 4. Point the Studio to EMSphInx

Open **Settings > EMSphInx Configuration (Windows / WSL)** and configure:

1. **WSL Distro**: enter `Debian`.
2. Next to **EMSphInx folder (WSL path)**, click **Browse…** and select `IndexEBSD` in the folder you extracted in step 2. The Studio fills in the WSL path automatically. You can also enter the folder path manually.
3. **Drive Mappings**: check that the drives you use match their WSL paths, for example `C:` → `/mnt/c` and `D:` → `/mnt/d`.
4. **Network Mounts**: remove any example entries you do not use. For files stored on your PC, this list can be empty.

Save the settings before creating jobs. Select your data files using their normal Windows paths; the Studio converts these to WSL paths automatically.

If your data is on a network share, add it under **Network Mounts** and give it a WSL mount point, for example `\\server\share` → `/mnt/n`. If you also access that share as `N:` in Windows, set its **Drive Mapping** to the same `/mnt/n` path. The Studio mounts configured shares when starting the queue.

## macOS

### Requirements

- macOS with Python 3.12+ and a modern Tkinter installation. The pyMTEX dependency requires Python 3.12 or newer.
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

1. Locate the folder containing the native macOS `IndexEBSD` executable.
2. Start the Studio with `.venv/bin/python main.py`.
3. On first launch, click **Browse…** and select the macOS `IndexEBSD` executable. The Studio fills in its folder automatically. You can change it later under **Settings > EMSphInx Configuration (macOS)**.
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

In Tab 1, **Map Field** also offers **IPF X**, **IPF Y**, and **IPF Z** when the loaded scan contains indexed orientations and phase information. These maps use pyMTEX's phase-aware HSV IPF colours for the corresponding specimen directions; unindexed points are black. IPF maps are generated in the background and cached while the file is open. They use the orientations already stored in the selected scan, rather than loading separate SphInx result files. Install the updated requirements to enable this feature.

IPF display requires usable crystal symmetry and lattice metadata. Oxford scans with a nonzero specimen orientation are not yet supported for IPF display; their other map fields remain available.

For Oxford data, the Studio automatically converts the patterns to a `.up1` file in the background before indexing. Optional binning reduces the pattern size by averaging blocks of pixels. The Studio updates the indexing parameters automatically and processes large files in chunks to limit memory use.

Detector tilt is read from the selected scan and written to the SphInx NML as `thetac` in degrees. EDAX camera elevation is used directly; Oxford `Detector Orientation Euler` is read in radians and converted as `Phi × 180/π − 90`. SphInx applies this scalar elevation only. If the Oxford orientation also has azimuth or twist, the Studio preserves the original Euler angles in the NML comments and reports the unapplied rotations in the job console. Invalid angles and unsupported EDAX azimuth are reported as errors. When EDAX H5 calibration lacks the angle, the Studio checks the `.ang` file with the same stem as the selected `.up1` for `CameraElevationAngle`. If neither source provides an angle, detector tilt defaults to 0°. Sample tilt continues to come from the SHT master pattern. Existing NML files are used as supplied.

Both NML parameter tabs show the imported angle in the editable **Detector tilt (°)** field. Edits apply to the generated job and are not saved as application defaults. Selecting another scan or EDAX UP1 restores that source's imported angle; **Reset to Defaults** also restores the imported angle. Binning and pattern-display changes preserve your edit. Values must be finite and between −60° and +60°.

## Moving jobs between platforms

NML files contain platform-specific absolute paths:

- NML files generated on Windows contain WSL paths such as `/mnt/c/...`.
- NML files generated on macOS contain native paths such as `/Users/...` or `/Volumes/...`.

When moving a job between Windows/WSL and macOS, regenerate its NML on the destination system or update every referenced path.
