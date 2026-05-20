# EMSphInx Studio

EMSphInx Studio is a powerful, cross-platform graphical user interface designed to bridge local Windows desktop environments with high-performance spherical indexing tools running under the Windows Subsystem for Linux (WSL).

It provides seamless integration for visualizing, managing, and automatically processing massive EBSD datasets from both **EDAX (.edaxh5 + .up1)** and **Oxford Instruments (.h5oina)** systems.

## Key Features

- **Interactive Map Viewers**: Instantly load and visualize massive map grids and raw diffraction patterns from binary datasets. Features custom Region of Interest (ROI) drawing and live spatial probing.
- **Asynchronous Data Unpacking**: Handles giant Oxford `.h5oina` files by asynchronously unpacking packed detector arrays into highly optimized `.up1` binary blocks without freezing the UI.
- **Intelligent WSL Job Queuing**: A robust execution queue that automatically marshals file paths between Windows and WSL environments, automatically mounts missing network drives, securely manages sudo privileges, and pipes high-performance C++ solver output directly to a live console.
- **EMsoft Integration**: Instantly fetch, validate, and manage `SHT` Master Patterns directly from the EMsoft GitHub API or load your own local libraries.

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
- **WSL 2** configured with a Linux distribution (e.g., Debian, Ubuntu).
- **EMSphInx** installed and compiled within your WSL environment (specifically, the `IndexEBSD` binary).
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
A comprehensive, detailed help system is built directly into the application. Click `Help > EMSphInx Studio Help` in the top menu bar to learn more about specific parameters and interactions for each tab.
