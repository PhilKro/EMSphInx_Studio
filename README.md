# EMSphInx Studio

EMSphInx Studio is a graphical user interface designed for **EMSphInx**, a software package for **spherical indexing of electron diffraction patterns** running under the Windows Subsystem for Linux (WSL).

It provides integration for visualizing, managing, and automatically processing EBSD datasets from **EDAX (.edaxh5 + .up1)** and **Oxford Instruments (.h5oina)** systems.

## Key Features

- **Interactive Map Viewers**: Instantly load and visualize map grids and raw diffraction patterns from binary datasets. Features custom Region of Interest (ROI) drawing and live spatial probing of EBSD patterns.
- **Asynchronous Data Unpacking**: Handles Oxford `.h5oina` files by asynchronously unpacking packed detector arrays into `.up1` files (this is done due to troubles with indexing .h5oina files with EMSphInx, if you find a fix for this please let me know, or make a pull request!).
- **WSL Job Queuing**: A queue that automatically marshals file paths between Windows and WSL environments, automatically mounts missing network drives, securely manages sudo privileges, and pipes EMSphInx'soutput directly to a live console.
- **Master Pattern Management**: Instantly fetch, validate, and manage `SHT` Master Patterns directly from the EMsoft GitHub API or load your own local libraries.

---

## Requirements

To run EMSphInx Studio, ensure you have the following installed:

### Windows Host
- **Python 3.8+**
- Standard Python dependencies (install via pip):
  ```bash
  pip install numpy h5py pillow requests matplotlib
  ```
- **Tkinter** (Usually included with standard Python installations)

### Windows Subsystem for Linux (WSL)
- **WSL 2** configured with a Linux Debian distribution.
- **EMSphInx** installed and compiled within your WSL environment (specifically, the `IndexEBSD` binary). Use the precompiled Debian version from https://github.com/EMsoft-org/EMSphInx/releases.
- If your data resides on network drives, WSL must be able to resolve and mount them via `drvfs`.

---

## Quick Guide

### 1. Configuration
When you first launch the application, you must configure the connection to your WSL environment:
- Open the **Job Queue** tab.
- Set your **WSL Distro** name (e.g., `Debian`).
- Provide the **WSL Path** to the directory containing your compiled `IndexEBSD` executable (e.g., `/mnt/c/Software/EMSphInx`).
- Your settings are saved automatically. If you require WSL network mounting, EMSphInx Studio will securely prompt for your `sudo` password and handle mounting automatically.

### 2. Workflow Overview
1. **System Mode Selection**: Choose either **EDAX** or **Oxford** at the top of the application depending on your data format.
2. **Visualize Data**: Navigate to the Pattern Viewer tab. Load your `.edaxh5` / `.up1` or `.h5oina` files. Click **Initialize Interactive Map** to load the patterns into fast memory. You can Shift+Drag to define an indexing ROI.
3. **Build NML**: Switch to the NML Builder tab. Fetch the necessary SHT Master Patterns, configure your spherical bandwidth and filtering parameters, and click **Generate NML & Add to Queue**.
4. **Execute**: Switch to the Job Queue tab. Your jobs will appear as *Pending*. Click **Start Queue** to automatically execute them sequentially through your WSL environment.

### 3. Help System
A detailed help window is provided at `Help > EMSphInx Studio Help` in the top menu bar. It includes explanations of specific parameters and interactions for each tab.
