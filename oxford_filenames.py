import glob
import os
import re


def output_name_parts(h5_path, map_name, bw, binning=1):
    """Return the current and pre-2026 Oxford output name components."""
    basename = os.path.splitext(os.path.basename(h5_path))[0]
    bin_tag = "" if int(binning) == 1 else f"_bin{int(binning)}"
    clean_up1 = f"{basename}{bin_tag}.up1"
    legacy_up1 = f"{basename}_{map_name}{bin_tag}.up1"
    clean_nml_prefix = f"{basename}{bin_tag}_BW{bw}"
    legacy_nml_prefix = f"{basename}_{map_name}{bin_tag}_BW{bw}"
    return clean_up1, legacy_up1, clean_nml_prefix, legacy_nml_prefix


def next_nml_name(directory, clean_prefix, legacy_prefix):
    """Choose a clean NML name while reserving names used by the old format."""
    max_index = -1
    for prefix in dict.fromkeys((clean_prefix, legacy_prefix)):
        pattern = re.compile(re.escape(prefix) + r'(?:_(\d+))?\.nml$')
        for path in glob.glob(os.path.join(directory, f"{prefix}*.nml")):
            match = pattern.fullmatch(os.path.basename(path))
            if match:
                max_index = max(max_index, int(match.group(1) or 0))

    if max_index < 0:
        return f"{clean_prefix}.nml"
    return f"{clean_prefix}_{max_index + 1}.nml"
