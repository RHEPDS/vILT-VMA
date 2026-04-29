# Analysis pipeline executed by vm_analysis.runner (edit in this file or replace module).
import io
import base64
import math
import os
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

# ROOT, SAVED_DIR, HELPER_DIR, INDEX_NROWS must be set by vm_analysis.runner.run_analysis()
# before exec() — do not assign them here (would overwrite injected values).
INDEX_FILENAME = "index.xlsx"

__figures__: list[str] = []
__figure_titles__: list[str] = []
__tables__: list[tuple[str, str]] = []
__risk_summary__: dict | None = None
__discovered_os__: dict | None = None
__duration_recalc__: dict | None = None
__log__ = io.StringIO()

def _orig_print(*args, **kwargs):
    kwargs.setdefault("file", __log__)
    print(*args, **kwargs)

def display(obj):
    if hasattr(obj, "to_html"):
        __tables__.append(("dataframe", obj.to_html(classes="table table-sm", border=0)))
    else:
        __tables__.append(("text", str(obj)))

def _extract_figure_title() -> str:
    """Read suptitle / axes titles from the current matplotlib figure."""
    fig = plt.gcf()
    parts: list[str] = []
    try:
        st = fig._suptitle
        if st is not None and hasattr(st, "get_text"):
            t = st.get_text().strip()
            if t:
                parts.append(t)
    except Exception:
        pass
    seen: set[str] = set()
    for ax in fig.get_axes():
        try:
            t = ax.get_title()
            if not t or not str(t).strip():
                continue
            n = " ".join(str(t).split()).strip()
            if n and n not in seen:
                seen.add(n)
                parts.append(n)
        except Exception:
            pass
    return " — ".join(parts) if parts else ""

def _capture_fig():
    idx = len(__figures__) + 1
    title = _extract_figure_title() or f"Chart {idx}"
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close()
    buf.seek(0)
    __figures__.append(base64.b64encode(buf.read()).decode("ascii"))
    __figure_titles__.append(title)

def _compute_overall_risk_summary() -> dict:
    """Overall score 0–100: inventory scale (VMs, hosts, cores, log-scaled) + unsupported guest OS %."""
    g = globals()
    vm = int(g.get("inscope_vm_count") or 0)
    hosts = int(g.get("inscope_host_count") or 0)
    cores = 0
    ivh = g.get("inscope_vhost_df")
    if ivh is not None and not getattr(ivh, "empty", True) and "# Cores" in ivh.columns:
        cores = int(pd.to_numeric(ivh["# Cores"], errors="coerce").fillna(0).sum())

    unsupported_pct = 0.0
    tot_os = g.get("total_os_instances")
    if tot_os:
        unsupported_pct = float(g.get("unsupported_count") or 0) / float(tot_os) * 100.0
    else:
        _os_map = {
            "Red Hat": "Easy",
            "CentOS": "Medium",
            "Windows": "Medium",
            "Ubuntu": "Hard",
            "SUSE Linux Enterprise": "Hard",
            "Oracle": "White Glove",
            "Microsoft SQL": "White Glove",
        }
        try:
            csv_path = Path(SAVED_DIR) / "In_Scope_VMs.csv"
            if csv_path.is_file():
                df = pd.read_csv(csv_path, low_memory=False)
                if not df.empty and "Cleaned OS" in df.columns:
                    vc = df["Cleaned OS"].value_counts()
                    tot = int(vc.sum())
                    if tot:
                        uns = 0
                        for os_name, cnt in vc.items():
                            d = next(
                                (diff for k, diff in _os_map.items() if k in str(os_name)),
                                "Unsupported",
                            )
                            if d == "Unsupported":
                                uns += int(cnt)
                        unsupported_pct = uns / tot * 100.0
        except Exception:
            pass

    def _cl(x: float) -> float:
        return max(0.0, min(1.0, x))

    vm_s = _cl(math.log10(1 + vm) / math.log10(1 + 500)) * 100
    host_s = _cl(math.log10(1 + hosts) / math.log10(1 + 80)) * 100
    core_s = _cl(math.log10(1 + max(cores, 0)) / math.log10(1 + 4000)) * 100
    os_s = min(100.0, unsupported_pct)
    overall = 0.22 * vm_s + 0.22 * host_s + 0.22 * core_s + 0.34 * os_s
    if overall >= 70.0:
        lbl = "High"
    elif overall >= 40.0:
        lbl = "Medium"
    else:
        lbl = "Low"
    return {
        "score": round(overall, 1),
        "vm_count": vm,
        "host_count": hosts,
        "cpu_cores": cores,
        "unsupported_guest_os_pct": round(unsupported_pct, 2),
        "label": lbl,
    }

def _discovered_os_lists() -> dict:
    """Distinct Cleaned OS with VM counts: in-scope (no exclusion) vs out-of-scope (any exclusion)."""
    g = globals()

    _OS_FAMILY_KEYS = (
        "Red Hat",
        "CentOS",
        "Windows",
        "Ubuntu",
        "SUSE Linux Enterprise",
        "Oracle",
        "Microsoft SQL",
    )

    def _is_unsupported_os_name(os_name: object) -> bool:
        """True if OS string matches none of the migration-complexity supported families."""
        s = str(os_name)
        return not any(k in s for k in _OS_FAMILY_KEYS)

    def _agg_series(s) -> list[dict]:
        s = s.fillna("").astype(str).str.strip()
        s = s.mask(s == "", "(unknown)")
        vc = s.value_counts()
        out: list[dict] = []
        for k, v in vc.sort_values(ascending=False).items():
            out.append(
                {
                    "os": str(k),
                    "vm_count": int(v),
                    "is_unsupported_os": _is_unsupported_os_name(k),
                }
            )
        return out

    cv = g.get("consolidated_vinfo_df")
    if cv is not None and not getattr(cv, "empty", True) and "Cleaned OS" in cv.columns:
        if "Exclusion Reason" in cv.columns:
            er = cv["Exclusion Reason"].fillna("").astype(str).str.strip()
            in_df = cv[er == ""]
            out_df = cv[er != ""]
        else:
            in_df = cv
            out_df = cv.iloc[0:0]
        return {
            "in_scope": _agg_series(in_df["Cleaned OS"]),
            "out_of_scope": _agg_series(out_df["Cleaned OS"]),
        }
    try:
        ins: list[dict] = []
        outs: list[dict] = []
        in_path = Path(SAVED_DIR) / "In_Scope_VMs.csv"
        out_path = Path(SAVED_DIR) / "Out_of_Scope_VMs.csv"
        if in_path.is_file():
            df = pd.read_csv(in_path, low_memory=False)
            if not df.empty and "Cleaned OS" in df.columns:
                ins = _agg_series(df["Cleaned OS"])
        if out_path.is_file():
            df = pd.read_csv(out_path, low_memory=False)
            if not df.empty and "Cleaned OS" in df.columns:
                outs = _agg_series(df["Cleaned OS"])
        return {"in_scope": ins, "out_of_scope": outs}
    except Exception:
        return {"in_scope": [], "out_of_scope": []}

def _duration_recalc_payload() -> dict | None:
    """Grain-level minutes (Environment × vCenter × Complexity × OS) for FTE + env include/exclude UI."""
    g = globals()
    pd = g.get("pd")
    if pd is None:
        return None
    te = float(g.get("TE_HOURS_PER_DAY") or g.get("te_hours_per_day") or 8)
    fte = float(g.get("FTE_COUNT") or g.get("fte_count") or 10)
    fv = g.get("filtered_vinfo_df")
    if fv is None or getattr(fv, "empty", True):
        return None
    need = {"Cleaned OS", "Disk Size TB", "VM", "Cluster", "vCenter"}
    if not need.issubset(set(fv.columns)):
        return None
    try:
        df = fv.copy()
        if "Environment" not in df.columns:
            df["Environment"] = "Unknown"
        df["Environment"] = df["Environment"].fillna("Unknown").astype(str).str.strip()
        df["Cleaned OS"] = df["Cleaned OS"].fillna("Unknown OS").astype(str).str.strip()
        df["Disk Size TB"] = pd.to_numeric(df["Disk Size TB"], errors="coerce").fillna(0)
        df["Cluster"] = df["Cluster"].fillna("").astype(str).str.lower()
        df["vCenter"] = df["vCenter"].fillna("unknown").astype(str)

        supported_os_counts = fv["Cleaned OS"].value_counts().index.tolist()
        df["OS Support"] = df["Cleaned OS"].apply(
            lambda os: (
                "Supported"
                if any(supported_os in str(os) for supported_os in supported_os_counts)
                else "Not Supported"
            )
        )

        size_bins = [0, 10, 20, 50, float("inf")]
        size_labels = [
            "Easy (0-10TB)",
            "Medium (10-20TB)",
            "Hard (20-50TB)",
            "White Glove (>50TB)",
        ]
        df["Disk Size Category"] = pd.cut(df["Disk Size TB"], bins=size_bins, labels=size_labels)

        def classify_complexity(row):
            cluster = str(row.get("Cluster", "")).lower()
            disk_size_category = row.get("Disk Size Category", "")
            if cluster.startswith("sql-") or "oracle" in cluster:
                return "White Glove"
            complexity_map = {
                "Easy (0-10TB)": "Easy",
                "Medium (10-20TB)": "Medium",
                "Hard (20-50TB)": "Hard",
                "White Glove (>50TB)": "White Glove",
            }
            return complexity_map.get(disk_size_category, "Unknown")

        df["Complexity"] = df.apply(classify_complexity, axis=1)

        migration_time_per_500gb = 110
        pmt_minutes = 60
        df["Migration Time (minutes)"] = df["Disk Size TB"].apply(
            lambda size: ((float(size) * 1024) / 500) * migration_time_per_500gb
        )
        df["Total Time (minutes)"] = df["Migration Time (minutes)"] + pmt_minutes

        gr = (
            df.groupby(["Environment", "vCenter", "Complexity", "OS Support"], observed=True)
            .agg(
                VM_Count=("VM", "count"),
                Total_Disk_TB=("Disk Size TB", "sum"),
                Total_Time_Minutes=("Total Time (minutes)", "sum"),
            )
            .reset_index()
        )

        grain_rows: list[dict] = []
        for _, row in gr.iterrows():
            grain_rows.append(
                {
                    "environment": str(row["Environment"]),
                    "vcenter": str(row["vCenter"]),
                    "complexity": str(row["Complexity"]),
                    "os_support": str(row["OS Support"]),
                    "vm_count": int(row["VM_Count"]),
                    "total_disk_tb": float(row["Total_Disk_TB"]),
                    "total_time_minutes": float(row["Total_Time_Minutes"]),
                }
            )

        env_names = sorted({str(x) for x in df["Environment"].unique()})
        gt_ref = None
        try:
            ggt = g.get("global_total_mig_time")
            if ggt is not None and pd.notna(ggt):
                gt_ref = float(ggt)
        except (TypeError, ValueError):
            pass

        if not grain_rows:
            return None
        return {
            "te_hours_per_day": te,
            "fte_count_default": fte,
            "grain_rows": grain_rows,
            "environment_names": env_names,
            "global_total_mig_minutes_reference": gt_ref,
        }
    except Exception:
        return None

DATA_DIR = str(ROOT / 'data')
INDEX_FILEPATH = os.path.join(DATA_DIR, INDEX_FILENAME)

# --- notebook cell 3 ---
# Analyze the VM inventory generated by rvtools
import pandas as pd
import os
from pathlib import Path
import matplotlib.pyplot as plt
# --- notebook cell 5 ---
# Set the display option to prevent line wrapping
pd.set_option('display.max_colwidth', None)
pd.set_option('display.expand_frame_repr', False)
# --- notebook cell 7 ---
INDEX_SHEETNAME = "index"
# --- notebook cell 10 ---
def read_rvtools_excel_files(directory, filenames_to_process):
    rvtools_data = {}

    for filename in os.listdir(directory):
        # Only process files listed in the index file.
        filename_base, _ = os.path.splitext(filename)
        if filename_base not in filenames_to_process: continue
        if filename in ['index.xlsx', 'index_template.xlsx']: continue

        if filename.endswith('.xlsx') or filename.endswith('.xls'):
            filepath = os.path.join(directory, filename)
            excel_data = pd.read_excel(filepath, sheet_name=None)
            rvtools_data[filename] = excel_data

    return rvtools_data
# --- notebook cell 15 ---
import pandas as pd
import os

# Read the index Excel file
index_df = pd.read_excel(
    INDEX_FILEPATH, sheet_name=INDEX_SHEETNAME, 
    nrows=INDEX_NROWS, index_col='vCenter', 
    true_values=['Yes', 'Y'], false_values=['No', 'N'], 
    na_filter=False, dtype={'In Scope': bool}
)

# Clean up column names and handle missing values
index_df.columns = index_df.columns.str.replace(' ', '_')
index_df.fillna('', inplace=True)

# Ensure 'In_Scope' column is boolean
index_df['In_Scope'] = index_df['In_Scope'].astype(bool)

# Filter for in-scope vCenters
inscope_df = index_df[index_df['In_Scope']].reset_index()

# Extract list of in-scope vCenter instances
inscope_vcenter_instances = set(inscope_df['vCenter'].tolist())  # Use a set for faster lookups

# Function to read RVTools Excel files while excluding 'index_template.xlsx' and 'index.xlsx'
def read_rvtools_excel_files(directory, vcenters):
    rvtools_data = {}
    exclude_files = {"index_template.xlsx", "index.xlsx"}  # Set of filenames to exclude

    for file in os.listdir(directory):
        if file.endswith(".xlsx") and file.lower() not in exclude_files:
            vcenter_match = next((vc for vc in vcenters if vc in file), None)  # Check if file contains an in-scope vCenter
            if vcenter_match:
                file_path = os.path.join(directory, file)
                try:
                    xls = pd.ExcelFile(file_path)
                    sheets = {sheet: xls.parse(sheet) for sheet in xls.sheet_names}
                    rvtools_data[file] = sheets
                except Exception as e:
                    print(f"Error reading {file}: {e}")
    
    return rvtools_data

# Read the RVTools Excel files
rvtools_data = read_rvtools_excel_files(str(ROOT / 'data'), inscope_vcenter_instances)

# Display the loaded data (for demonstration purposes)
for filename, sheets in rvtools_data.items():
    print(f'Processed RVTools File: {filename}')
    for sheet_name, df in sheets.items():
        print(f"  Sheet: {sheet_name} Shape: {df.shape}")

print("\n✅️ "f'Total files processed: {len(rvtools_data)}')
# --- notebook cell 17 ---
import pandas as pd

# Initialize the lists
vinfo_sheets = []
vhost_sheets = []
vdisk_sheets = []

# Load vInfo, vHost and vDisk sheets into the lists
for filename, sheets in rvtools_data.items():
    vCenter = filename.split('.')[0].lower()  # Extract vCenter instance name from the filename

    # Ensure required sheets exist before processing
    if 'vInfo' in sheets and 'vHost' in sheets and 'vDisk' in sheets:
        # Add the vCenter instance name to each sheet
        sheets['vInfo']['vCenter'] = vCenter
        sheets['vHost']['vCenter'] = vCenter
        sheets['vDisk']['vCenter'] = vCenter

        # Append to the respective lists
        vinfo_sheets.append(sheets['vInfo'])
        vhost_sheets.append(sheets['vHost'])
        vdisk_sheets.append(sheets['vDisk'])

# Filter out empty or all-NA DataFrames
vinfo_sheets = [df for df in vinfo_sheets if not df.dropna(how='all').empty]
vhost_sheets = [df for df in vhost_sheets if not df.dropna(how='all').empty]
vdisk_sheets = [df for df in vdisk_sheets if not df.dropna(how='all').empty]

# Concatenate the filtered DataFrames only if there are valid sheets
consolidated_vinfo_df = pd.concat(vinfo_sheets, ignore_index=True) if vinfo_sheets else pd.DataFrame()
consolidated_vhost_df = pd.concat(vhost_sheets, ignore_index=True) if vhost_sheets else pd.DataFrame()
consolidated_vdisk_df = pd.concat(vdisk_sheets, ignore_index=True) if vdisk_sheets else pd.DataFrame()

# Verify data ingestion success with improved readability
print("🔍 Data Ingestion Verification")
print("\n✅️ "f"Total vInfo (Total VM's) records: {len(consolidated_vinfo_df)}")
print("✅️ "f"Total vHost (Total HW) records: {len(consolidated_vhost_df)}")
print("✅️ "f"Total vDisk (Total VM Disks) records: {len(consolidated_vdisk_df)}\n")

# --- notebook cell 19 ---
import matplotlib.pyplot as plt
import pandas as pd

# Ensure that consolidated_vinfo_df exists before proceeding
try:
    # Group by vCenter and count VMs
    grouped_summary = consolidated_vinfo_df.groupby("vCenter").size().reset_index(name="Count")

    # Create a pivot table for better visualization
    grouped_summary_pivot = grouped_summary.pivot_table(values="Count", index="vCenter", aggfunc="sum")

    # Print summary
    total_vms = grouped_summary["Count"].sum()
    total_vcenters = grouped_summary.shape[0]

    print(f"🔍 Overall Distribution of {total_vms:,} VMs in the {total_vcenters:,} vCenter instances:")
    print(grouped_summary_pivot)
    print("\n📝 This is the TOTAL VM count, and WILL include VM templates, SRM Placeholders, Powered Off & Orphaned Objects...")

    # Calculate original percentage distribution
    percentages = grouped_summary["Count"] / total_vms * 100

    # Identify slices below .5% and adjust to at least 1%
    min_threshold = 0.5
    new_min_threshold = 1
    adjusted_percentages = percentages.copy()

    # Find slices below threshold
    below_threshold_mask = adjusted_percentages < min_threshold
    num_below_threshold = below_threshold_mask.sum()
    
    if num_below_threshold > 0:
        # Calculate deficit caused by increasing small slices to 10%
        deficit = new_min_threshold * num_below_threshold - adjusted_percentages[below_threshold_mask].sum()

        # Increase small slices to 10%
        adjusted_percentages[below_threshold_mask] = new_min_threshold

        # Reduce larger slices proportionally to compensate for the increase
        large_slices_mask = ~below_threshold_mask  # Slices that are >= min_threshold
        if large_slices_mask.sum() > 0:
            scale_factor = (100 - new_min_threshold * num_below_threshold) / adjusted_percentages[large_slices_mask].sum()
            adjusted_percentages[large_slices_mask] *= scale_factor

    # Ensure sum is exactly 100% (fix potential floating-point issues)
    adjusted_percentages = adjusted_percentages.round(1)
    adjusted_percentages.iloc[-1] += 100 - adjusted_percentages.sum()  # Correct final rounding error safely

    # Generate explode values to emphasize each slice
    explode_values = [0.05] * len(grouped_summary)  # Adjust explosion for all slices

    # Get colors from the tab20 colormap
    cmap = plt.get_cmap("tab20")
    colors = [cmap(i % 10) for i in range(len(grouped_summary))]  # Cycle through the colormap

    # Plot an exploded pie chart with adjusted percentages
    plt.figure(figsize=(8, 8))
    plt.pie(
        adjusted_percentages,
        labels=grouped_summary["vCenter"],
        autopct=lambda p: f"{p:.1f}%",  # Ensures every slice displays a percentage
        startangle=140,
        explode=explode_values,  # Add explode effect
        shadow=True,  # Add shadow for better visualization
        colors=colors  # Use tab20 colors
    )
    plt.title("\nDistribution of VMs by vCenter Instances")
    _capture_fig()

except NameError:
    print("Error: The dataset 'consolidated_vinfo_df' is not defined.")
except Exception as e:
    print(f"An error occurred: {e}")
# --- notebook cell 21 ---
import re
import pandas as pd
import matplotlib.pyplot as plt

# Function to load patterns from an external file
def load_patterns(file_path):
    """Reads patterns from an external file."""
    with open(file_path, "r", encoding="utf-8") as file:
        patterns = [line.strip() for line in file if line.strip()]
    return patterns

# Load OS filter patterns and ignore patterns
os_filter_patterns = load_patterns(str(HELPER_DIR / "os_filter_patterns.txt"))
ignore_patterns = load_patterns(str(HELPER_DIR / "ignored_patterns.txt"))

def clean_os_name(os_name):
    """Normalize OS names by removing extra spaces and redundant information."""
    if pd.isna(os_name) or os_name.strip() == '':
        return ''
    os_name = os_name.strip()
    os_name = re.sub(r"\s*\(.*\)$", "", os_name)  # Remove (32-bit) / (64-bit)
    os_name = re.sub(r"\s+", " ", os_name)  # Remove extra spaces
    return os_name

def os_filter(os_name):
    """Check if the OS should be filtered based on the defined patterns."""
    if pd.isna(os_name) or os_name.strip() == '':
        return False
    os_name_clean = clean_os_name(os_name)
    return any(re.fullmatch(pattern, os_name_clean, re.IGNORECASE) for pattern in os_filter_patterns)

# Ensure the DataFrame exists before processing
if 'consolidated_vinfo_df' not in globals():
    raise ValueError("consolidated_vinfo_df is not defined.")
if 'consolidated_vdisk_df' not in globals():
    raise ValueError("consolidated_vdisk_df is not defined.")

# Ensure OS column is populated, tagging Unknown if both sources are empty
consolidated_vinfo_df['OS Effective'] = consolidated_vinfo_df['OS according to the VMware Tools'].fillna(
    consolidated_vinfo_df['OS according to the configuration file']
)
consolidated_vinfo_df.loc[
    consolidated_vinfo_df['OS Effective'].isna() |
    (consolidated_vinfo_df['OS Effective'].str.strip() == ''),
    'OS Effective'
] = 'Unknown'

# Normalize OS names before filtering
consolidated_vinfo_df['Cleaned OS'] = consolidated_vinfo_df['OS Effective'].apply(clean_os_name)

# Initialize exclusion reason column
consolidated_vinfo_df['Exclusion Reason'] = ''

# Apply exclusion rules using escaped ignore patterns
if ignore_patterns:
    consolidated_vinfo_df.loc[
        consolidated_vinfo_df['VM'].str.contains('|'.join(map(re.escape, ignore_patterns)), case=False, na=False),
        'Exclusion Reason'
    ] = 'Ignored VM Pattern'

consolidated_vinfo_df.loc[
    consolidated_vinfo_df['Cleaned OS'].apply(os_filter),
    'Exclusion Reason'
] = 'Excluded OS'

# Exclude 'Unknown' OS VMs
consolidated_vinfo_df.loc[
    consolidated_vinfo_df['OS Effective'] == 'Unknown',
    'Exclusion Reason'
] = 'Unknown OS'

# Ensure 'Template' column is properly processed
consolidated_vinfo_df['Template'] = consolidated_vinfo_df['Template'].fillna(False).astype(bool)
consolidated_vinfo_df.loc[
    consolidated_vinfo_df['Template'],
    'Exclusion Reason'
] = 'Template'

consolidated_vinfo_df.loc[
    consolidated_vinfo_df['SRM Placeholder'].fillna(False) == True,
    'Exclusion Reason'
] = 'SRM Placeholder'

consolidated_vinfo_df.loc[
    consolidated_vinfo_df['Connection state'].fillna('').str.lower() == 'orphaned',
    'Exclusion Reason'
] = 'Orphaned VM'

# Powered off VMs with excluded OS
consolidated_vinfo_df.loc[
    (consolidated_vinfo_df['Powerstate'].fillna('').str.lower() == 'poweredoff') &
    (consolidated_vinfo_df['Cleaned OS'].apply(os_filter)),
    'Exclusion Reason'
] = 'Powered Off'

# ✅ Controller-based filtering using vDisk sheet
if 'Controller' in consolidated_vdisk_df.columns:
    controller_pattern = r'i440fx|ide\s*\d+'
    matching_vms = consolidated_vdisk_df[
        consolidated_vdisk_df['Controller'].str.contains(controller_pattern, case=False, na=False, regex=True)
    ]['VM'].unique()

    consolidated_vinfo_df.loc[
        (consolidated_vinfo_df['VM'].isin(matching_vms)) &
        (consolidated_vinfo_df['Exclusion Reason'] == ''),
        'Exclusion Reason'
    ] = 'i440fx or IDE Controller'
else:
    print("⚠️ The 'Controller' column does not exist in the consolidated_vdisk_df.")

# Filter in-scope VMs
filtered_vinfo_df = consolidated_vinfo_df[consolidated_vinfo_df['Exclusion Reason'] == '']

# Debugging: Ensure no Templates exist in filtered VMs
assert not filtered_vinfo_df['Template'].any(), "Templates are still present in In-Scope VMs!"

# Categorize ignored VMs
ignored_vm_artifacts = consolidated_vinfo_df[consolidated_vinfo_df['Exclusion Reason'] == 'Excluded OS']
ignored_artifacts = consolidated_vinfo_df[
    consolidated_vinfo_df['Exclusion Reason'].isin(['Template', 'SRM Placeholder', 'Orphaned VM', 'Unknown OS'])
]
ignored_controllers = consolidated_vinfo_df[
    consolidated_vinfo_df['Exclusion Reason'] == 'i440fx or IDE Controller'
]

# Save data to CSV files
filtered_vinfo_df.to_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), index=False)
ignored_vm_artifacts.to_csv(str(SAVED_DIR / "Out_of_Scope_VMs.csv"), index=False)
ignored_controllers.to_csv(str(SAVED_DIR / "Unsupported_disk_Controllers.csv"), index=False)

# Display summary
print("\n🔍 Filtering Summary")
print(f"🔶 Out-of-Scope VM count (OS): {len(ignored_vm_artifacts):,}")
print(f"🔶 Ignored Artifacts (Template, SRM, Orphaned, Unknown OS): {len(ignored_artifacts):,}")
print(f"🔶 Ignored Controllers: {len(ignored_controllers):,}")
print(f"🔷 In-Scope VM count: {len(filtered_vinfo_df):,}\n")

# Pie Chart
plt.figure(figsize=(8, 8))
plt.pie(
    [len(ignored_vm_artifacts), len(ignored_artifacts), len(ignored_controllers), len(filtered_vinfo_df)],
    labels=['Out-of-Scope VMs', 'Ignored Artifacts', 'Unsupported Controllers', 'In-Scope VMs'],
    autopct='%1.1f%%', shadow=True, startangle=140,
    explode=(0.05, 0.05, 0.05, 0),
    colors=['lightcoral', 'lightskyblue', 'red', 'lightgreen']
)
plt.title("\nBreakdown of VM Filtering")
_capture_fig()

# Confirm file creation
print(f"\n✅ CSV files saved successfully to: {SAVED_DIR}")
print("📁 In-Scope VMs: 'In_Scope_VMs.csv'")
print("📁 Out-of-Scope VMs: 'Out_of_Scope_VMs.csv'")
print("📁 Unsupported Controllers: 'Unsupported_disk_Controllers.csv'")
# --- notebook cell 23 ---
import pandas as pd

# Select the in-scope vCenter instances
inscope_vinfo_condition = filtered_vinfo_df['vCenter'].isin(inscope_vcenter_instances)
inscope_vinfo_df = filtered_vinfo_df[inscope_vinfo_condition]

# Summary stats for in-scope VMs
total_vm_count = len(filtered_vinfo_df)
inscope_vm_count = len(inscope_vinfo_df)
percent_inscope_vms = (inscope_vm_count / total_vm_count * 100.0) if total_vm_count > 0 else 0.0

print("\n🔍 VM (vInfo) Summary")
print(f"✅ {inscope_vm_count:,} VMs are in-scope ({percent_inscope_vms:0.2f}% of total VMs).\n")

# Create a pivot table for VMs by vCenter
vm_pivot = inscope_vinfo_df.pivot_table(index="vCenter", aggfunc="size").reset_index()
vm_pivot.columns = ["vCenter", "VM Count"]
display(vm_pivot)

# Select the in-scope hosts
inscope_vhost_condition = consolidated_vhost_df['vCenter'].isin(inscope_vcenter_instances)
inscope_vhost_df = consolidated_vhost_df[inscope_vhost_condition]

# Summary stats for in-scope hosts
total_host_count = len(consolidated_vhost_df)
inscope_host_count = len(inscope_vhost_df)
percent_inscope_hosts = (inscope_host_count / total_host_count * 100.0) if total_host_count > 0 else 0.0

print("\n🔍 Host (vHost) Summary")
print(f"✅ {inscope_host_count:,} hosts are in-scope ({percent_inscope_hosts:0.2f}% of total hosts).\n")

# Create a pivot table for hosts by vCenter
host_pivot = inscope_vhost_df.pivot_table(index="vCenter", aggfunc="size").reset_index()
host_pivot.columns = ["vCenter", "Host Count"]
display(host_pivot)
# --- notebook cell 26 ---
import pandas as pd

# === vInfo Pivot Table (VM-Level Info) ===
vinfo_pivot_df = filtered_vinfo_df.pivot_table(
    index='vCenter',
    values=['VM', 'CPUs', 'Memory', 'NICs', 'Provisioned MiB'],
    aggfunc={
        'VM': 'count',
        'CPUs': 'sum',
        'Memory': 'sum',
        'NICs': 'sum',
        'Provisioned MiB': 'sum'
    },
    margins=False
)

# === vHost Pivot Table (Host-Level Info) ===
vhost_pivot_df = consolidated_vhost_df.pivot_table(
    index='vCenter',
    values=['Host', '# VMs total', '# CPU', '# Memory', '# Cores'],
    aggfunc={
        'Host': 'count',
        '# CPU': 'sum',
        '# Memory': 'sum',
        '# Cores': 'sum'
    },
    margins=False
)

# === Convert Memory to GB/TB ===
def format_storage(mib_value):
    if pd.isna(mib_value):
        return "N/A"
    if mib_value >= 1_000_000:  # Convert to TB if ≥ 1,000,000 MiB
        return f"{mib_value / 1_048_576:.2f} TB"
    return f"{mib_value / 1024:.2f} GB"  # Convert to GB otherwise

# --- DEBUGGING STEP (optional) ---
# print("vinfo_pivot_df columns:", vinfo_pivot_df.columns)

# Check if 'Provisioned MiB' exists before applying
if 'Provisioned MiB' in vinfo_pivot_df.columns:
    vinfo_pivot_df['Total Disk Capacity'] = vinfo_pivot_df['Provisioned MiB'].apply(format_storage)
    vinfo_pivot_df = vinfo_pivot_df.drop(columns=['Provisioned MiB'])
else:
    vinfo_pivot_df['Total Disk Capacity'] = "N/A"

# Apply formatting to Memory
if 'Memory' in vinfo_pivot_df.columns:
    vinfo_pivot_df['Memory'] = vinfo_pivot_df['Memory'].apply(format_storage)

if '# Memory' in vhost_pivot_df.columns:
    vhost_pivot_df['# Memory'] = vhost_pivot_df['# Memory'].apply(format_storage)

# === Pretty Display for Each Table ===
try:
      # Works for Jupyter Notebook

    print("\n🔍 VM Info (vInfo)")
    display(vinfo_pivot_df)

    print("\n🔍 Host Info (vHost)")
    display(vhost_pivot_df)

except ImportError:
    print("\n🔍 VM Info (vInfo)")
    print(vinfo_pivot_df)

    print("\n🔍 Host Info (vHost)")
    print(vhost_pivot_df)
# --- notebook cell 28 ---
import re
import pandas as pd
import matplotlib.pyplot as plt

# Load the data
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'Cleaned OS', 'VM'}
if not required_columns.issubset(in_scope_df.columns):
    raise ValueError(f"Missing required columns: {required_columns - set(in_scope_df.columns)}")

# Drop rows where VM or Cleaned OS is missing
in_scope_df = in_scope_df.dropna(subset=['VM', 'Cleaned OS'])

# If DataFrame is empty after cleaning
if in_scope_df.empty:
    print("Warning: No VMs are in scope or input data is empty.")
    fig, ax = plt.subplots(figsize=(10, 2))
    ax.text(0.5, 0.5, "No VMs are in scope", fontsize=14, ha='center', va='center')
    ax.axis('off')
    plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.1)
    _capture_fig()
else:
    inscope_guest_os_pivot = in_scope_df.pivot_table(index='Cleaned OS', values='VM', aggfunc='count')
    inscope_guest_os_pivot = inscope_guest_os_pivot.sort_values(by='VM', ascending=True)

    if inscope_guest_os_pivot.empty:
        print("Warning: The pivot table is empty after filtering.")
        fig, ax = plt.subplots(figsize=(10, 2))
        ax.text(0.5, 0.5, "No VMs are in scope", fontsize=14, ha='center', va='center')
        ax.axis('off')
        plt.subplots_adjust(left=0.1, right=0.9, top=0.9, bottom=0.1)
        _capture_fig()
    else:
        total_vms = inscope_guest_os_pivot['VM'].sum()
        percentages = (inscope_guest_os_pivot['VM'] / total_vms * 100).round(1)

        fig_height = max(6, len(inscope_guest_os_pivot) * 0.4)
        fig, ax = plt.subplots(figsize=(16, fig_height))  # Wider figure to avoid label cutoff

        bars = ax.barh(inscope_guest_os_pivot.index, inscope_guest_os_pivot['VM'], color=plt.cm.tab20.colors)

        for bar, count, percentage in zip(bars, inscope_guest_os_pivot['VM'], percentages):
            ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height()/2,
                    f"{count} VMs ({percentage}%)", va='center', fontsize=8, color='black')

        ax.set_xlabel("Number of VMs", fontsize=10)
        ax.set_ylabel("Operating Systems", fontsize=10)
        ax.set_title("OS Distribution", fontsize=12, pad=20)
        ax.grid(axis='x', linestyle='--', alpha=0.7)

        # Manually adjust margins
        plt.subplots_adjust(left=0.3, right=0.95, top=0.9, bottom=0.1)
        _capture_fig()
# --- notebook cell 30 ---
import pandas as pd
import matplotlib.pyplot as plt

# Load CSV
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Check required columns
required_columns = {'Cleaned OS', 'VM'}
if not required_columns.issubset(in_scope_df.columns):
    raise ValueError(f"Missing required columns: {required_columns - set(in_scope_df.columns)}")

# Drop rows with missing values in key columns
in_scope_df = in_scope_df.dropna(subset=['VM', 'Cleaned OS'])

# Ensure 'VM' is treated as a string (or any type that works well)
in_scope_df['VM'] = in_scope_df['VM'].astype(str)

# Group and count VMs per OS (equivalent to pivot with count)
inscope_guest_os_pivot = (
    in_scope_df.groupby('Cleaned OS')
    .size()
    .reset_index(name='VM_Count')
    .sort_values(by='VM_Count', ascending=False)
    .set_index('Cleaned OS')
)

# Filter for OSs with over 500 VMs
over_500_vms = inscope_guest_os_pivot[inscope_guest_os_pivot['VM_Count'] > 500]

# Display the table
display(over_500_vms)

# Plot pie chart
if over_500_vms.empty:
    print("⚠️ No operating systems have more than 500 VMs.")
else:
    plt.figure(figsize=(10, 10))
    colors = plt.cm.tab20.colors[:len(over_500_vms)]
    explode = [0.05] * len(over_500_vms)

    wedges, texts, autotexts = plt.pie(
        over_500_vms['VM_Count'],
        labels=over_500_vms.index,
        autopct='%1.1f%%',
        startangle=140,
        colors=colors,
        explode=explode,
        shadow=True,
    )

    for text in texts:
        text.set_fontsize(10)
    for autotext in autotexts:
        autotext.set_fontsize(10)
        autotext.set_color('white')

    plt.title("In-Scope OS's with Over 500 VMs", fontsize=12, pad=20)
    plt.tight_layout()
    _capture_fig()
# --- notebook cell 32 ---
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Define memory tiers (in GB) in ascending order
memory_tiers = {
    '0-4 GB': (0, 4),
    '4-16 GB': (4, 16),
    '16-32 GB': (16, 32),
    '32-64 GB': (32, 64),
    '64-128 GB': (64, 128),
    '128-256 GB': (128, 256),
    '256+ GB': (256, float('inf'))
}
memory_tier_order = list(memory_tiers.keys())  # Preserve tier order for sorting

# Function to categorize memory
def categorize_memory(memory_gb):
    for tier, (lower, upper) in memory_tiers.items():
        if lower <= memory_gb < upper:
            return tier
    return 'Unknown'

# Load the data
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'Cleaned OS', 'VM', 'Memory'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Convert memory to numeric and to GB
in_scope_df['Memory'] = pd.to_numeric(in_scope_df['Memory'], errors='coerce')
in_scope_df.dropna(subset=['Memory'], inplace=True)
in_scope_df['Memory GB'] = in_scope_df['Memory'] / 1024

# Apply memory tier categorization
in_scope_df['Memory Tier'] = in_scope_df['Memory GB'].apply(categorize_memory)

# Convert Memory Tier to categorical with correct order
in_scope_df['Memory Tier'] = pd.Categorical(in_scope_df['Memory Tier'], categories=memory_tier_order, ordered=True)

# Create summary table
memory_tier_summary = (
    in_scope_df.groupby('Memory Tier', observed=True)
    .agg({'VM': 'count'})
    .rename(columns={'VM': 'VM Count'})
    .sort_index()
)

# Remove tiers with zero VMs
memory_tier_summary = memory_tier_summary[memory_tier_summary['VM Count'] > 0]

# Handle empty case
if memory_tier_summary.empty:
    print("⚠️ Warning: No VMs are in-scope. Memory Tier Summary is empty.")
else:
    # Calculate original percentages
    total_vms = memory_tier_summary['VM Count'].sum()
    original_percentages = (memory_tier_summary['VM Count'] / total_vms) * 100

    # Adjust small slices
    min_percentage = 0.5
    new_min_threshold = 1
    adjusted_percentages = original_percentages.copy()

    below_threshold_mask = adjusted_percentages < min_percentage
    num_below_threshold = below_threshold_mask.sum()

    if num_below_threshold > 0:
        deficit = new_min_threshold * num_below_threshold - adjusted_percentages[below_threshold_mask].sum()
        adjusted_percentages[below_threshold_mask] = new_min_threshold
        large_slices_mask = ~below_threshold_mask
        if large_slices_mask.sum() > 0:
            scale_factor = (100 - new_min_threshold * num_below_threshold) / adjusted_percentages[large_slices_mask].sum()
            adjusted_percentages[large_slices_mask] *= scale_factor

    # Normalize to 100%
    adjusted_percentages = adjusted_percentages.round(1)
    if len(adjusted_percentages) > 0:
        adjusted_percentages.iloc[-1] += 100 - adjusted_percentages.sum()

    # Formatter for pie chart labels
    def autopct_format(pct):
        index = np.argmin(np.abs(adjusted_percentages - pct))
        return f"{original_percentages.iloc[index]:.1f}%"

    # Print table
    print("\n🔍 Memory Tier Summary (In-Scope OS's Only)")
    print(memory_tier_summary)

    # Plot
    plt.figure(figsize=(10, 10))
    explode_values = [0.05] * len(memory_tier_summary)
    colors = plt.cm.tab20.colors[:len(memory_tier_summary)]

    plt.pie(
        adjusted_percentages,
        labels=memory_tier_summary.index,
        autopct=autopct_format,
        startangle=200,
        explode=explode_values,
        shadow=True,
        colors=colors
    )
    plt.title("VM Distribution % by Memory Size Tier")
    plt.axis('equal')
    _capture_fig()
# --- notebook cell 34 ---
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Load the data
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure required columns exist
required_columns = {'Cleaned OS', 'VM', 'Provisioned MiB'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Convert disk size to TB
mib_to_tb_conversion_factor = 2**20 / 10**12
in_scope_df['Disk Size TB'] = in_scope_df['Provisioned MiB'] * mib_to_tb_conversion_factor

# Identify VMs with missing/zero disk size
no_disk_size_vms_df = in_scope_df[(in_scope_df['Disk Size TB'].isna()) | (in_scope_df['Disk Size TB'] == 0)]
no_disk_size_vm_count = no_disk_size_vms_df.shape[0]

# Filter valid disk size data
filtered_disk_df = in_scope_df[in_scope_df['Disk Size TB'] > 0].copy()

# Define disk tiers
disk_size_bins = [0, 1, 2, 10, 20, 50, 100, float('inf')]
disk_bin_labels = ['Tiny (<1 TB)', 'Easy (<=2 TB)', 'Medium (<=10 TB)', 'Hard (<=20 TB)', 
                   'Very Hard (<=50 TB)', 'White Glove (<=100 TB)', 'Extreme (>100 TB)']

filtered_disk_df['Disk Size Tiers'] = pd.cut(
    filtered_disk_df['Disk Size TB'],
    bins=disk_size_bins,
    labels=disk_bin_labels
).astype(str)

# Create pivot
disk_tier_pivot_df = filtered_disk_df.pivot_table(
    index='Disk Size Tiers', 
    values=['VM', 'Disk Size TB'], 
    aggfunc={'VM': 'count', 'Disk Size TB': 'sum'},
    observed=False
).reindex(disk_bin_labels).fillna(0)

# Check if pivot has expected columns before proceeding
if 'VM' not in disk_tier_pivot_df.columns or disk_tier_pivot_df['VM'].sum() == 0:
    print("⚠️ Warning: No VMs with disk size info. Cannot generate tier summary or pie chart.")
else:
    # Round disk sizes
    if 'Disk Size TB' in disk_tier_pivot_df.columns:
        disk_tier_pivot_df['Disk Size TB'] = disk_tier_pivot_df['Disk Size TB'].round(2)

    # Remove tiers with 0 VMs
    disk_tier_pivot_df = disk_tier_pivot_df[disk_tier_pivot_df['VM'] > 0]

    # Add total row
    total_row = pd.DataFrame({
        'VM': [disk_tier_pivot_df['VM'].sum()],
        'Disk Size TB': [round(disk_tier_pivot_df['Disk Size TB'].sum(), 2)]
    }, index=['Total'])
    disk_tier_pivot_with_total = pd.concat([disk_tier_pivot_df, total_row])

    # Display table
    print("\U0001F50D Tier Summary with Total Disk (Formatted):")
    print(disk_tier_pivot_with_total.to_string())

    # Calculate original percentages
    total_vms = disk_tier_pivot_df['VM'].sum()
    original_percentages = (disk_tier_pivot_df['VM'] / total_vms) * 100

    # Remove 0% categories
    valid_indices = original_percentages > 0
    disk_tier_pivot_df = disk_tier_pivot_df[valid_indices]
    original_percentages = original_percentages[valid_indices]
    disk_bin_labels = disk_tier_pivot_df.index.tolist()

    # Adjust small slices
    min_percentage = 0.5
    new_min_threshold = 1
    adjusted_percentages = original_percentages.copy()

    below_threshold_mask = adjusted_percentages < min_percentage
    num_below_threshold = below_threshold_mask.sum()

    if num_below_threshold > 0:
        deficit = new_min_threshold * num_below_threshold - adjusted_percentages[below_threshold_mask].sum()
        adjusted_percentages[below_threshold_mask] = new_min_threshold
        large_slices_mask = ~below_threshold_mask
        if large_slices_mask.sum() > 0:
            scale_factor = (100 - new_min_threshold * num_below_threshold) / adjusted_percentages[large_slices_mask].sum()
            adjusted_percentages[large_slices_mask] *= scale_factor

    # Normalize to 100%
    adjusted_percentages = adjusted_percentages.round(1)
    if len(adjusted_percentages) > 0:
        adjusted_percentages.iloc[-1] += 100 - adjusted_percentages.sum()

    # Label formatting
    def autopct_format(pct):
        index = np.argmin(np.abs(adjusted_percentages - pct))
        return f"{original_percentages.iloc[index]:.1f}%"

    # Generate pie chart
    plt.figure(figsize=(10, 10))
    colors = plt.cm.tab20c(np.linspace(0, 1, len(disk_bin_labels)))
    explode_values = [0.05] * len(disk_bin_labels)

    plt.pie(
        adjusted_percentages,
        labels=disk_bin_labels,
        autopct=autopct_format,
        startangle=200,
        explode=explode_values,
        shadow=True,
        colors=colors
    )
    plt.title('VM Distribution % by Disk Size Tier')
    plt.axis('equal')
    _capture_fig()

# Always show bar chart for missing disk size
plt.figure(figsize=(5, 5))
plt.bar(['No Disk Size'], [no_disk_size_vm_count], color='purple')
plt.title('VMs without Disk Size Information')
plt.ylabel('Number of VMs')
plt.tight_layout()
_capture_fig()
# --- notebook cell 36 ---
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors

# Group all hosts by model
all_host_model_pivot_df = consolidated_vhost_df.pivot_table(index=['Vendor', 'Model'], values='Host', aggfunc='count')
display(all_host_model_pivot_df)

# Bar chart for all host models
plt.figure(figsize=(12, 8))  # Make it wider to avoid label overlap

# Generate a colormap with enough distinct colors
norm = mcolors.Normalize(vmin=0, vmax=len(all_host_model_pivot_df)-1)
colors = cm.tab20(norm(range(len(all_host_model_pivot_df))))

# Create a bar chart with automatic colors
bar_plot = all_host_model_pivot_df['Host'].plot(kind='bar', color=colors, edgecolor='black', figsize=(12, 8))

# Add title and labels
plt.title('Host Node Models', fontsize=12)
plt.xlabel('Host Model', fontsize=10)
plt.ylabel('Host Count', fontsize=10)

# Improve x-tick readability by rotating the labels
plt.xticks(rotation=90, ha='right', fontsize=8)

# Add totals on top of each bar
for bar in bar_plot.patches:
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
             f'{int(bar.get_height())}', ha='center', va='bottom', fontsize=10)

# Show the bar chart
plt.tight_layout()  # Adjust layout to prevent overlapping labels
_capture_fig()
# --- notebook cell 38 ---
import matplotlib.pyplot as plt
import numpy as np

# Group all the hosts by their model and vCenter
all_host_model_vcenter_pivot_df = consolidated_vhost_df.pivot_table(
    index=['vCenter', 'Vendor', 'Model'],
    values=['Host'],
    aggfunc={'Host': 'count'},
    observed=False,
    margins=False,
    sort=True
)

print("🔍 "f'Distribution of ALL host models by vCenter:\n')
print(all_host_model_vcenter_pivot_df)
pass  # to_clipboard skipped
# Bar chart creation based on the pivot table (sorted by host count)
plt.figure(figsize=(14, 8))  # Increase figure size for better visibility

# Prepare labels and data
labels = all_host_model_vcenter_pivot_df.index.map(lambda x: f'{x[1]} {x[2]} ({x[0]})')  # Combine Vendor, Model, and vCenter in the label
sizes = all_host_model_vcenter_pivot_df['Host']

# Automatically assign colors using the 'tab20' colormap
colors = plt.cm.tab20(np.linspace(0, 1, len(sizes)))

# Create the vertical bar chart
bars = plt.bar(labels, sizes, color=colors, edgecolor='black')

# Add text annotations (totals) on top of each bar
for bar in bars:
    yval = bar.get_height()
    plt.text(
        bar.get_x() + bar.get_width() / 2, 
        yval, 
        int(yval), 
        ha='center', 
        va='bottom', 
        fontsize=10
    )

# Add title and formatting
plt.title('Host Node Models', fontsize=14)
plt.xlabel('Host Model', fontsize=12)
plt.ylabel('Number of Hosts', fontsize=12)

# Rotate x-axis labels for better readability
plt.xticks(rotation=45, ha='right')

# Display the bar chart
plt.tight_layout()  # Adjust layout to prevent clipping
_capture_fig()
# --- notebook cell 40 ---
import pandas as pd
import matplotlib.pyplot as plt

# Load the data with low_memory=False to suppress dtype warnings
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'Cleaned OS', 'VM', 'Datacenter', 'Cluster'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Drop rows with NaN in critical columns
in_scope_df = in_scope_df.dropna(subset=['Datacenter', 'Cluster', 'VM'])

# Filter out rows where 'VM' is an empty string or just whitespace
in_scope_df = in_scope_df[in_scope_df['VM'].astype(str).str.strip() != '']

# Get unique Datacenters
datacenters = in_scope_df['Datacenter'].unique()
print("🔍 "f'Total VMware Datacenters: {len(datacenters):,}')

# Get unique Clusters
clusters = in_scope_df['Cluster'].unique()
print("🔍 "f'Total ESXi clusters: {len(clusters):,}')

# Group by Datacenter and count unique Clusters
inscope_datacenter_pivot = in_scope_df.groupby('Datacenter')['Cluster'].nunique().reset_index(name='Cluster_Count')
inscope_datacenter_pivot.set_index('Datacenter', inplace=True)

# Sort by Cluster_Count in descending order
inscope_datacenter_pivot = inscope_datacenter_pivot.sort_values(by='Cluster_Count', ascending=False)

# Calculate the total number of clusters from the pivot table
total_clusters_from_pivot = int(inscope_datacenter_pivot['Cluster_Count'].sum())

# Calculate the total number of datacenters
total_datacenters = int(inscope_datacenter_pivot.shape[0])

# Show only the top 10 datacenters in the summary
print(f'\n🔍 Distribution of Clusters to Datacenters (Top 10 by Cluster Count):')
print(inscope_datacenter_pivot.head(10).to_string(index=True))
print(f'\n🔥 Total Clusters across all Datacenters: {total_clusters_from_pivot}')
print(f'🔥 Total number of Datacenters: {total_datacenters}')

# Debug: Compare Total ESXi clusters vs. Sum of clusters per datacenter
if len(clusters) != total_clusters_from_pivot:
    print("\n⚠️ Warning: The total ESXi clusters count does not match the sum of clusters across datacenters.")
    print(f"‼️ Total ESXi clusters (unique across dataset): {len(clusters):,}")
    print(f"‼️ Total Clusters from pivot table (sum per datacenter): {total_clusters_from_pivot:,}")

    # Find clusters mapped to multiple datacenters
    cluster_datacenter_mapping = in_scope_df.groupby('Cluster')['Datacenter'].nunique()
    multi_dc_clusters = cluster_datacenter_mapping[cluster_datacenter_mapping > 1]

    if not multi_dc_clusters.empty:
        print("\n🔍 Clusters that appear in multiple datacenters (Top 10 shown):")
        print(multi_dc_clusters.head(10).to_string(index=True))

# Copy full results to clipboard for easy pasting into Excel
pass  # to_clipboard skipped
# Save the full pivot table to a CSV file
csv_filename = str(SAVED_DIR / "Cluster_Distribution_by_Datacenter.csv")
inscope_datacenter_pivot.to_csv(csv_filename, index=True)
print(f"\n📂 Data saved to: {csv_filename}")

# Create a pie chart (using only the top 10 datacenters for clarity)
top_10_pivot = inscope_datacenter_pivot.head(10)

plt.figure(figsize=(10, 10))
plt.pie(top_10_pivot['Cluster_Count'], labels=top_10_pivot.index, 
        autopct='%1.1f%%', startangle=140, shadow=True, explode=[0.05] * len(top_10_pivot))
plt.title('\nClusters Distribution (Top 10 Datacenters)')
_capture_fig()
# --- notebook cell 42 ---
import pandas as pd
import matplotlib.pyplot as plt

# Load the data with low_memory=False to suppress dtype warnings
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'Cleaned OS', 'VM', 'Cluster'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Drop rows with missing or empty Cluster/VM names
in_scope_df = in_scope_df.dropna(subset=['Cluster', 'VM'])
in_scope_df = in_scope_df[in_scope_df['VM'].astype(str).str.strip() != ""]

# If DataFrame is empty after cleaning, exit early
if in_scope_df.empty:
    print("❌ No in-scope VMs found after cleaning. Exiting.")
else:
    # Pivot the VM information on the clusters
    inscope_cluster_pivot = in_scope_df.pivot_table(index='Cluster',
                                                    values=['VM'],  # Ensures it's a DataFrame
                                                    aggfunc='count')

    # Rename column for clarity, only if 'VM' exists
    if 'VM' in inscope_cluster_pivot.columns:
        inscope_cluster_pivot.rename(columns={'VM': 'VM_Count'}, inplace=True)
    else:
        raise KeyError("Expected column 'VM' not found in pivot result.")

    # Sort by VM_Count in descending order
    inscope_cluster_pivot = inscope_cluster_pivot.sort_values(by='VM_Count', ascending=False)

    # Calculate totals
    total_vms = int(inscope_cluster_pivot['VM_Count'].sum())
    total_clusters = int(inscope_cluster_pivot.shape[0])

    # Print summary for top 10 clusters
    print("\U0001F50D Distribution of VMs to Clusters (Top 10 by VM Count):")
    print(inscope_cluster_pivot.head(10).to_string(index=True))
    print(f'\n⚠️ VMs that belong to multiple ESXi clusters are counted only once.')
    print(f'\U0001F525 Total VMs across all clusters: {total_vms}')
    print(f'\U0001F525 Total number of clusters: {total_clusters}\n')

    # Save full VM distribution to a CSV file
    csv_filename = str(SAVED_DIR / "VM_Distribution_to_Clusters.csv")
    inscope_cluster_pivot.to_csv(csv_filename)
    print(f'\U0001F4BE VM distribution saved to {csv_filename}')

    # Copy full results to clipboard for easy pasting into Excel
    pass  # to_clipboard skipped
    # Create a pie chart for the top 10 clusters
    top_10_pivot = inscope_cluster_pivot.head(10)

    if not top_10_pivot.empty:
        plt.figure(figsize=(10, 10))
        plt.pie(top_10_pivot['VM_Count'], labels=top_10_pivot.index,
                autopct='%1.1f%%', startangle=140, shadow=True,
                explode=[0.05] * len(top_10_pivot))
        plt.title('\n VM Distribution (Top 10 Clusters)')
        _capture_fig()
    else:
        print("No data available to plot the pie chart.")
# --- notebook cell 44 ---
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# Load the data with low_memory=False to suppress dtype warnings
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'Cleaned OS', 'VM'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Handle missing 'Environment' column
if 'Environment' not in in_scope_df.columns:
    print("⚠️ 'Environment' column missing from in_scope_df. Creating it with default value 'Unknown'.")
    in_scope_df['Environment'] = 'Unknown'

# If environment_summary isn't defined, try building it
if 'environment_summary' not in globals():
    if 'filtered_vinfo_df' not in globals():
        raise ValueError("Neither environment_summary nor filtered_vinfo_df is defined. Ensure the required data is available.")

    if 'Environment' not in filtered_vinfo_df.columns:
        print("⚠️ 'Environment' column missing from filtered_vinfo_df. Creating it with default value 'Unknown'.")
        filtered_vinfo_df = filtered_vinfo_df.copy()
        filtered_vinfo_df['Environment'] = 'Unknown'

    filtered_vinfo_df = filtered_vinfo_df.copy()
    filtered_vinfo_df['Environment'] = filtered_vinfo_df['Environment'].fillna('Unknown')
    filtered_vinfo_df.loc[filtered_vinfo_df['Environment'].astype(str).str.strip() == '', 'Environment'] = 'Unknown'

    environment_summary = (
        filtered_vinfo_df.groupby('Environment', as_index=False)
        .size()
        .rename(columns={'size': 'VM_Count'})
    )

# Remove 'Total' row if present
environment_filtered = environment_summary[environment_summary['Environment'] != 'Total'].copy()

# Convert VM_Count to numeric
environment_filtered['VM_Count'] = pd.to_numeric(environment_filtered['VM_Count'], errors='coerce')

# Check if 'Environment' column exists (should always exist at this point)
if 'Environment' not in in_scope_df.columns:
    raise KeyError("'Environment' column is missing from in_scope_df. Check data source.")

# Filter in-scope VMs only if available
if not in_scope_df.empty:
    in_scope_vms = in_scope_df[['VM', 'Environment']].dropna(subset=['VM']).drop_duplicates()
    environment_filtered = environment_filtered[
        environment_filtered['Environment'].isin(in_scope_vms['Environment'].unique())
    ].copy()

# Plot only if there's data
if not environment_filtered.empty:
    env_counts = dict(zip(environment_filtered['Environment'], environment_filtered['VM_Count']))
    original_percentages = pd.Series(env_counts) / sum(env_counts.values()) * 100

    min_percentage = 1
    new_min_threshold = 1
    adjusted_percentages = original_percentages.copy()
    
    below_threshold_mask = adjusted_percentages < min_percentage
    num_below_threshold = below_threshold_mask.sum()
    
    if num_below_threshold > 0:
        deficit = new_min_threshold * num_below_threshold - adjusted_percentages[below_threshold_mask].sum()
        adjusted_percentages.loc[below_threshold_mask] = new_min_threshold
        large_slices_mask = ~below_threshold_mask
        if large_slices_mask.sum() > 0:
            scale_factor = (100 - new_min_threshold * num_below_threshold) / adjusted_percentages[large_slices_mask].sum()
            adjusted_percentages.loc[large_slices_mask] *= scale_factor

    # Normalize adjusted percentages
    adjusted_percentages = adjusted_percentages.round(1)
    if adjusted_percentages.sum() != 100:
        adjusted_percentages.iloc[-1] += 100 - adjusted_percentages.sum()

    def autopct_format(pct):
        try:
            index = np.argmin(np.abs(adjusted_percentages.values - pct))
            return f"{original_percentages.iloc[index]:.1f}%"
        except IndexError:
            return f"{pct:.1f}%"

    explode_values = [0.05] * len(env_counts)

    # Plot pie chart
    plt.figure(figsize=(10, 10))
    plt.pie(
        adjusted_percentages,
        labels=environment_filtered['Environment'],
        autopct=autopct_format,
        startangle=140,
        colors=plt.cm.tab20.colors[:len(env_counts)],
        shadow=True,
        explode=explode_values
    )
    plt.title('\n VM Distribution % by Environment')
    _capture_fig()

else:
    print("⚠️ No matching in-scope environments found. Pie chart will not be generated.")
# --- notebook cell 46 ---
import pandas as pd
import matplotlib.pyplot as plt

# Function to truncate OS names, ensuring input is always a string
def truncate_os_names(series):
    return series.rename(lambda x: str(x) if len(str(x)) <= 40 else str(x)[:37] + '...')

# Load the data
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)
out_of_scope_df = pd.read_csv(str(SAVED_DIR / "Out_of_Scope_VMs.csv"), low_memory=False)

# Drop rows with missing or invalid 'VM' or 'Cleaned OS'
in_scope_df = in_scope_df.dropna(subset=['VM', 'Cleaned OS'])
out_of_scope_df = out_of_scope_df.dropna(subset=['VM', 'Cleaned OS'])

# Filter out rows where 'VM' is 0
in_scope_df = in_scope_df[in_scope_df['VM'] != 0]
out_of_scope_df = out_of_scope_df[out_of_scope_df['VM'] != 0]

# Pie Chart: In-Scope vs Out-of-Scope
if not in_scope_df.empty or not out_of_scope_df.empty:
    plt.figure(figsize=(8, 8))
    plt.pie(
        [len(in_scope_df), len(out_of_scope_df)],
        labels=["In-Scope VM's", "Out-of-Scope VM's"],
        autopct='%1.1f%%', shadow=True, startangle=200, explode=(0.1, 0),
        colors=['lightgreen', 'lightcoral']
    )
    plt.title("In-Scope vs Out-of-Scope")
    _capture_fig()
else:
    print("\u26a0\ufe0f No VM data available for Pie Chart.")

# Pivot and Bar Chart: In-Scope
if not in_scope_df.empty:
    in_scope_os_counts_df = in_scope_df.pivot_table(index='Cleaned OS', values='VM', aggfunc='count')
    in_scope_os_counts = in_scope_os_counts_df.iloc[:, 0]  # Convert to Series
    in_scope_os_counts.index = truncate_os_names(pd.Series(in_scope_os_counts.index.astype(str))).values

    plt.figure(figsize=(16, 8))
    bars = in_scope_os_counts.sort_values(ascending=False).plot(kind='bar', color='green')
    plt.title('In-Scope OS Counts')
    plt.xlabel('Operating System')
    plt.ylabel('Number of VMs')
    plt.xticks(rotation=45, ha='right')
    plt.subplots_adjust(bottom=0.3, top=0.9)

    for bar in bars.patches:
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f'{int(bar.get_height())}',
                 ha='center', va='bottom', fontsize=10)

    _capture_fig()
else:
    print("\u26a0\ufe0f No In-Scope VM data available for Bar Chart.")

# Pivot and Bar Chart: Out-of-Scope
if not out_of_scope_df.empty:
    out_of_scope_os_counts_df = out_of_scope_df.pivot_table(index='Cleaned OS', values='VM', aggfunc='count')
    out_of_scope_os_counts = out_of_scope_os_counts_df.iloc[:, 0]  # Convert to Series
    out_of_scope_os_counts.index = truncate_os_names(pd.Series(out_of_scope_os_counts.index.astype(str))).values

    plt.figure(figsize=(16, 8))
    bars = out_of_scope_os_counts.sort_values(ascending=False).plot(kind='bar', color='red')
    plt.title('Out-of-Scope OS Counts')
    plt.xlabel('Operating System')
    plt.ylabel('Number of VMs')
    plt.xticks(rotation=45, ha='right')
    plt.subplots_adjust(bottom=0.3, top=0.9)

    for bar in bars.patches:
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, f'{int(bar.get_height())}',
                 ha='center', va='bottom', fontsize=10)

    _capture_fig()
else:
    print("\u26a0\ufe0f No Out-of-Scope VM data available for Bar Chart.")
# --- notebook cell 48 ---
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Categorize supported OS into difficulty levels
os_difficulty_mapping = {
    'Red Hat': 'Easy',
    'CentOS': 'Medium',
    'Windows': 'Medium',
    'Ubuntu': 'Hard',
    'SUSE Linux Enterprise': 'Hard',
    'Oracle': 'White Glove',
    'Microsoft SQL': 'White Glove'
}

# Load the data with low_memory=False to suppress dtype warnings
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure the dataframe exists and is not empty
if 'filtered_vinfo_df' in locals() or 'filtered_vinfo_df' in globals():
    if not filtered_vinfo_df.empty:
        # Count OS instances from in-scope VMs
        in_scope_os_counts = in_scope_df['Cleaned OS'].value_counts()

        # Initialize difficulty counts
        difficulty_counts = {'Easy': 0, 'Medium': 0, 'Hard': 0, 'White Glove': 0, 'Unsupported': 0}

        # Map OS instances to difficulty levels
        for os_name, count in in_scope_os_counts.items():
            difficulty = next((difficulty for key, difficulty in os_difficulty_mapping.items() if key in os_name), 'Unsupported')
            difficulty_counts[difficulty] += count

        # Identify unsupported OS instances within in-scope VMs
        unsupported_count = difficulty_counts['Unsupported']

        # Summary Section
        total_os_instances = sum(difficulty_counts.values())

        print("🔍 Migration Complexity Summary")
        print(f"🧐 Total OS Instances Analyzed: {total_os_instances}")
        for level, count in difficulty_counts.items():
            print(f"  {level}: {count}")
        print(f"\n🔴 Unsupported Instances: {unsupported_count}")

        # Print White Glove OS instances
        white_glove_os = [os for os in in_scope_os_counts.index if 'Oracle' in os or 'Microsoft SQL' in os]
        print("\n🧤 White Glove Instances:")
        for os in white_glove_os:
            print(f"🚨 {os}: {in_scope_os_counts[os]}")

        # Filter and print VMs running unsupported OS instances
        unsupported_vms = filtered_vinfo_df[filtered_vinfo_df['Cleaned OS'].apply(
            lambda x: next((difficulty for key, difficulty in os_difficulty_mapping.items() if key in str(x)), 'Unsupported')
        ) == 'Unsupported']

        if not unsupported_vms.empty:
            print("\n🚨 VMs Running Unsupported (but migratable) OS Instances:")
            for vm_name, os_name in zip(unsupported_vms['VM'], unsupported_vms['Cleaned OS']):
                print(f"⚠️ VM: {vm_name}, OS: {os_name}")

        # Create a bar chart with automatic colors
        plt.figure(figsize=(10, 6))

        difficulty_levels = list(difficulty_counts.keys())
        os_counts = list(difficulty_counts.values())

        # Generate a colormap automatically
        colors = plt.cm.tab20(np.linspace(0, 1, len(difficulty_levels)))

        bars = plt.bar(difficulty_levels, os_counts, color=colors)
        plt.title('\n Migration Complexity by OS')
        plt.xlabel('Difficulty Level')
        plt.ylabel('Number of OS Instances')

        # Add numeric labels on bars
        for bar in bars:
            yval = bar.get_height()
            plt.text(bar.get_x() + bar.get_width()/2, yval + 0.5, yval, ha='center', va='bottom', fontsize=10)

        plt.tight_layout()
        _capture_fig()
    else:
        print("⚠️ The dataframe 'filtered_vinfo_df' is empty.")
else:
    print("⚠️ The dataframe 'filtered_vinfo_df' is not defined.")
# --- notebook cell 50 ---
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load the data
in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)

# Ensure necessary columns exist
required_columns = {'VM', 'Provisioned MiB'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Drop rows with NaN or non-numeric values in 'Provisioned MiB'
in_scope_df = in_scope_df[pd.to_numeric(in_scope_df['Provisioned MiB'], errors='coerce').notnull()]
in_scope_df['Provisioned MiB'] = in_scope_df['Provisioned MiB'].astype(float)

# Convert disk size to TB
mib_to_tb_conversion_factor = 2**20 / 10**12
in_scope_df['Disk Size TB'] = in_scope_df['Provisioned MiB'] * mib_to_tb_conversion_factor

# Filter out VMs with zero or negative disk size
filtered_vinfo_df = in_scope_df[in_scope_df['Disk Size TB'] > 0].copy()

if filtered_vinfo_df.empty:
    print("⚠️ No VMs with valid disk size > 0 found. Skipping chart generation.")
else:
    # Define disk size categories
    size_bins = [0, 10, 20, 50, float('inf')]
    size_labels = ['Easy (0-10TB)', 'Medium (10-20TB)', 'Hard (20-50TB)', 'White Glove (>50TB)']

    # Categorize VMs by disk size
    filtered_vinfo_df['Disk Size Category'] = pd.cut(
        filtered_vinfo_df['Disk Size TB'], bins=size_bins, labels=size_labels, include_lowest=True
    )

    # Create summary
    disk_size_summary = filtered_vinfo_df['Disk Size Category'].value_counts().reindex(size_labels, fill_value=0).reset_index()
    disk_size_summary.columns = ['Disk Size Category', 'VM Count']

    # Display summary
    print("\U0001F50D Migration Complexity by Disk:")
    print(disk_size_summary.to_string(index=False))

    # Generate dynamic colors
    plt.figure(figsize=(10, 6))
    colors = plt.cm.tab10(np.linspace(0, 1, len(size_labels)))

    # Plot bar chart with dynamic colors
    bars = plt.bar(disk_size_summary['Disk Size Category'], disk_size_summary['VM Count'], color=colors)

    plt.xlabel('Disk Size Category')
    plt.ylabel('Number of VMs')
    plt.title('\n Migration Complexity by Disk Size')
    plt.xticks(rotation=45, ha='right')

    # Add numeric labels on bars
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval + 0.5, int(yval), ha='center', va='bottom', fontsize=10)

    plt.tight_layout()
    _capture_fig()
# --- notebook cell 52 ---
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Load the data safely
try:
    in_scope_df = pd.read_csv(str(SAVED_DIR / "In_Scope_VMs.csv"), low_memory=False)
except FileNotFoundError:
    raise FileNotFoundError("CSV file not found. Ensure the file path is correct.")

# Ensure required columns exist
required_columns = {'VM', 'Provisioned MiB', 'Cleaned OS'}
missing_columns = required_columns - set(in_scope_df.columns)
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Convert disk size to TB
mib_to_tb_conversion_factor = 2**20 / 10**12
in_scope_df['Disk Size TB'] = in_scope_df['Provisioned MiB'] * mib_to_tb_conversion_factor

# Filter out VMs with missing or zero disk size
filtered_vinfo_df = in_scope_df[in_scope_df['Disk Size TB'] > 0].copy()

# Define disk size categories
size_bins = [0, 10, 20, 50, float('inf')]
size_labels = ['Easy (0-10TB)', 'Medium (10-20TB)', 'Hard (20-50TB)', 'White Glove (>50TB)']
filtered_vinfo_df['Disk Size Category'] = pd.cut(
    filtered_vinfo_df['Disk Size TB'], bins=size_bins, labels=size_labels, include_lowest=True
)

# OS difficulty mapping
os_difficulty_mapping = {
    'Red Hat': 'Easy',
    'CentOS': 'Medium',
    'Windows': 'Medium',
    'Ubuntu': 'Hard',
    'SUSE Linux Enterprise': 'Hard',
    'Oracle': 'Database',
    'Microsoft SQL': 'Database'
}

# Map OS to difficulty level safely
filtered_vinfo_df['OS Difficulty'] = filtered_vinfo_df['Cleaned OS'].astype(str).apply(
    lambda os: next((difficulty for key, difficulty in os_difficulty_mapping.items() if key in os), 'Unsupported')
)

# Define complexity mapping function
def determine_complexity(row):
    os_difficulty = row['OS Difficulty']
    disk_category = row['Disk Size Category']
    
    if os_difficulty == 'Database':
        return 'White Glove'
    
    if os_difficulty == 'Easy':
        return 'Easy' if disk_category in ['Easy (0-10TB)', 'Medium (10-20TB)'] else 'Hard'
    
    if os_difficulty == 'Medium':
        return 'Medium' if disk_category in ['Easy (0-10TB)', 'Medium (10-20TB)'] else 'Hard'
    
    if os_difficulty == 'Hard':
        return 'Medium' if disk_category in ['Easy (0-10TB)', 'Medium (10-20TB)'] else 'Hard'
    
    return 'Unsupported'

# Apply complexity mapping
filtered_vinfo_df['Migration Complexity'] = filtered_vinfo_df.apply(determine_complexity, axis=1)

# Create summary table counting VMs per complexity level
complexity_order = ['Easy', 'Medium', 'Hard', 'White Glove', 'Unsupported']
complexity_summary = filtered_vinfo_df['Migration Complexity'].value_counts().reindex(complexity_order, fill_value=0).reset_index()
complexity_summary.columns = ['Migration Complexity', 'VM Count']
complexity_summary = complexity_summary[complexity_summary['VM Count'] > 0]

# Display complexity summary
print("\U0001F50D Migration Summary:")
print(complexity_summary.to_string(index=False, header=True))

# Plot bar chart
plt.figure(figsize=(10, 6))
bars = plt.bar(complexity_summary['Migration Complexity'], complexity_summary['VM Count'], color=plt.cm.tab10.colors)
plt.xlabel('Migration Complexity')
plt.ylabel('Number of VMs')
plt.title('Migration Complexity Distribution')
plt.xticks(rotation=45, ha='right')
plt.grid(axis='y', linestyle='--', alpha=0.7)

# Add value labels
for bar in bars:
    yval = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2, yval, int(yval), ha='center', va='bottom', fontsize=10)

_capture_fig()

# Calculate percentage for pie chart
complexity_summary = complexity_summary.copy()
complexity_summary['Percentage'] = (complexity_summary['VM Count'] / complexity_summary['VM Count'].sum()) * 100

# Normalize small percentages
def adjust_percentages(percentages, min_threshold=0.5, new_min=1):
    percentages = percentages.copy()
    below_threshold = percentages < min_threshold
    num_below = below_threshold.sum()
    
    if num_below > 0:
        deficit = new_min * num_below - percentages[below_threshold].sum()
        percentages.loc[below_threshold] = new_min
        large_mask = ~below_threshold
        percentages.loc[large_mask] *= (100 - new_min * num_below) / percentages.loc[large_mask].sum()
    
    return percentages.round(1)

complexity_summary['Adjusted Percentage'] = adjust_percentages(complexity_summary['Percentage'])

# Filter out zero percentages
valid_indices = complexity_summary['Adjusted Percentage'] > 0
adjusted_percentages = complexity_summary.loc[valid_indices, 'Adjusted Percentage']
valid_labels = complexity_summary.loc[valid_indices, 'Migration Complexity']

# Plot pie chart
fig, ax = plt.subplots(figsize=(10, 10))
explode = [0.05 if p > 0 else 0 for p in adjusted_percentages]
wedges, texts, autotexts = ax.pie(
    adjusted_percentages, labels=valid_labels,
    autopct=lambda pct: f"{pct:.1f}%" if pct > 0 else '',
    colors=plt.cm.tab20.colors,
    startangle=200, explode=explode, shadow=True
)

for text in texts + autotexts:
    text.set_fontsize(8)
    text.set_weight('normal')

plt.title('Migration Complexity Distribution (Percentage)')
_capture_fig()
# --- notebook cell 54 ---
import pandas as pd

# Constants
migration_time_per_500gb = 110   # minutes (1 hour 50 minutes per 500GB)
te_hours_per_day = 8             # 8 hours per day per FTE
fte_count = 10                   # 10 FTEs available
pmt_hours = 1                    # Post-migration troubleshooting time per VM in hours

# Check if filtered_vinfo_df is defined
try:
    filtered_vinfo_df
except NameError:
    raise ValueError("filtered_vinfo_df is not defined. Ensure it is loaded before running this script.")

# Ensure required columns are present
required_columns = {'Cleaned OS', 'Disk Size TB', 'VM', 'Cluster'}
missing_columns = required_columns - set(filtered_vinfo_df.columns)

if missing_columns:
    raise ValueError(f"The following required columns are missing in filtered_vinfo_df: {missing_columns}")

# Copy and preprocess DataFrame
inscope_vinfo_df = filtered_vinfo_df.copy()
inscope_vinfo_df['Cleaned OS'] = inscope_vinfo_df['Cleaned OS'].fillna("Unknown OS").astype(str).str.strip()
inscope_vinfo_df['Disk Size TB'] = pd.to_numeric(inscope_vinfo_df['Disk Size TB'], errors='coerce').fillna(0)
inscope_vinfo_df['VM'] = inscope_vinfo_df['VM'].fillna('Unknown VM')
inscope_vinfo_df['Cluster'] = inscope_vinfo_df['Cluster'].fillna('').str.lower()

# Define disk size classification
size_bins = [0, 10, 20, 50, float('inf')]
size_labels = ['Easy (0-10TB)', 'Medium (10-20TB)', 'Hard (20-50TB)', 'White Glove (>50TB)']
inscope_vinfo_df['Disk Size Category'] = pd.cut(inscope_vinfo_df['Disk Size TB'], bins=size_bins, labels=size_labels)

# Generate supported OS list dynamically
supported_os_counts = filtered_vinfo_df['Cleaned OS'].value_counts().index.tolist()
inscope_vinfo_df['OS Support'] = inscope_vinfo_df['Cleaned OS'].apply(
    lambda os: 'Supported' if any(supported_os in os for supported_os in supported_os_counts) else 'Not Supported'
)

# Complexity classification
def classify_complexity(row):
    cluster = str(row.get('Cluster', '')).lower()
    disk_size_category = row.get('Disk Size Category', '')

    if cluster.startswith('sql-') or 'oracle' in cluster:
        return 'White Glove'

    complexity_map = {
        'Easy (0-10TB)': 'Easy',
        'Medium (10-20TB)': 'Medium',
        'Hard (20-50TB)': 'Hard',
        'White Glove (>50TB)': 'White Glove'
    }
    return complexity_map.get(disk_size_category, 'Unknown')

inscope_vinfo_df['Complexity'] = inscope_vinfo_df.apply(classify_complexity, axis=1)

# Sort complexity order
complexity_order = ['Easy', 'Medium', 'Hard', 'White Glove', 'Database']
inscope_vinfo_df['Complexity'] = pd.Categorical(inscope_vinfo_df['Complexity'], categories=complexity_order, ordered=True)
inscope_vinfo_df = inscope_vinfo_df.sort_values('Complexity')

# Compute Migration Time
inscope_vinfo_df['Migration Time (minutes)'] = inscope_vinfo_df['Disk Size TB'].apply(
    lambda size: ((size * 1024) / 500) * migration_time_per_500gb
)

# Compute Total Time (Migration + Post-Migration)
pmt_minutes = pmt_hours * 60
inscope_vinfo_df['Total Time (minutes)'] = inscope_vinfo_df['Migration Time (minutes)'] + pmt_minutes

# Summarize data
disk_classification_summary = inscope_vinfo_df.groupby(['Complexity', 'OS Support'], observed=True).agg(
    VM_Count=('VM', 'count'),
    Total_Disk=('Disk Size TB', 'sum'),
    Total_Mig_Time_Minutes=('Total Time (minutes)', 'sum')
).reset_index()

# Compute Total Days and Weeks before formatting
disk_classification_summary['Total_Days'] = disk_classification_summary['Total_Mig_Time_Minutes'] / (te_hours_per_day * 60 * fte_count)
disk_classification_summary['Total_Weeks'] = disk_classification_summary['Total_Days'] / 5

# Add totals row before formatting
totals_row = {
    'Complexity': 'Total',
    'OS Support': '',
    'VM_Count': disk_classification_summary['VM_Count'].sum(),
    'Total_Disk': disk_classification_summary['Total_Disk'].sum(),
    'Total_Mig_Time_Minutes': disk_classification_summary['Total_Mig_Time_Minutes'].sum(),
    'Total_Days': disk_classification_summary['Total_Days'].sum(),
    'Total_Weeks': disk_classification_summary['Total_Weeks'].sum()
}
disk_classification_summary = pd.concat([disk_classification_summary, pd.DataFrame([totals_row])], ignore_index=True)

# Format numeric columns for display
disk_classification_summary['Total_Disk'] = disk_classification_summary['Total_Disk'].apply(lambda x: f"{x:.2f} TB")
disk_classification_summary['Total_Days'] = disk_classification_summary['Total_Days'].apply(lambda x: f"{x:.1f}")
disk_classification_summary['Total_Weeks'] = disk_classification_summary['Total_Weeks'].apply(lambda x: f"{x:.1f}")

# Drop intermediate column
disk_classification_summary = disk_classification_summary.drop(columns=['Total_Mig_Time_Minutes'])

# Function to format the summary table
def format_table(headers, rows):
    horizontal_line = "─"
    vertical_line = "│"
    corner_tl, corner_tr = "╭", "╮"
    corner_bl, corner_br = "╰", "╯"
    join_t, join_b, join_c = "┬", "┴", "┼"
    col_widths = [max(len(str(item)) for item in col) for col in zip(headers, *rows)]

    def make_row(items):
        return vertical_line + vertical_line.join(f"{str(item).rjust(width)}" for item, width in zip(items, col_widths)) + vertical_line

    top_line = corner_tl + join_t.join(horizontal_line * width for width in col_widths) + corner_tr
    header_row = make_row(headers)
    divider_row = join_c.join(horizontal_line * width for width in col_widths).join(["├", "┤"])
    data_rows = [make_row(row) for row in rows[:-1]]
    totals_divider_row = join_c.join(horizontal_line * width for width in col_widths).join(["├", "┤"])
    totals_row = make_row(rows[-1])
    bottom_line = corner_bl + join_b.join(horizontal_line * width for width in col_widths) + corner_br
    return "\n".join([top_line, header_row, divider_row] + data_rows + [totals_divider_row, totals_row, bottom_line])

# Convert DataFrame to formatted table
headers = list(disk_classification_summary.columns)
rows = disk_classification_summary.values.tolist()
formatted_table = format_table(headers, rows)

# Print formatted summary table
print(f"🔍 Migration Summary")
print(formatted_table)
# --- notebook cell 56 ---
import pandas as pd

# Constants
fte_hours_per_day = 8  # 8 hours per day per FTE
fte_count = 10         # 10 FTEs available

# Ensure required columns exist
required_columns = {'Complexity', 'OS Support', 'VM', 'Disk Size TB', 'Total Time (minutes)', 'vCenter'}
missing_columns = required_columns - set(inscope_vinfo_df.columns)

# Handle missing columns
if 'OS Support' in missing_columns:
    inscope_vinfo_df['OS Support'] = 'Unknown'  # Defaulting to 'Unknown'

# If 'Complexity' is missing, classify based on disk size or other available data
if 'Complexity' in missing_columns:
    # Define disk size classification
    size_bins = [0, 10, 20, 50, float('inf')]
    size_labels = ['Easy', 'Medium', 'Hard', 'White Glove']
    inscope_vinfo_df['Disk Size Category'] = pd.cut(inscope_vinfo_df['Disk Size TB'], bins=size_bins, labels=size_labels)

    # Define complexity based on disk size and vCenter name
    def classify_complexity(row):
        cluster = str(row.get('vCenter', '')).lower()
        disk_size_category = row.get('Disk Size Category', '')

        if cluster.startswith('sql-') or 'oracle' in cluster:
          return 'White Glove'

        complexity_map = {
            'Easy': 'Easy',
            'Medium': 'Medium',
            'Hard': 'Hard',
            'White Glove': 'White Glove'
        }
        return complexity_map.get(disk_size_category, 'Unknown')  # Default to 'Tiny'

    inscope_vinfo_df['Complexity'] = inscope_vinfo_df.apply(classify_complexity, axis=1)

# Recheck if any required columns are missing after handling defaults
missing_columns = required_columns - set(inscope_vinfo_df.columns)
if missing_columns:
    raise ValueError(f"The following required columns are missing in inscope_vinfo_df: {missing_columns}")

# Define complexity order
complexity_order = ['Easy', 'Medium', 'Hard', 'White Glove']
inscope_vinfo_df['Complexity'] = pd.Categorical(
    inscope_vinfo_df['Complexity'],
    categories=complexity_order,
    ordered=True
)

# Get unique vCenters
vcenters = inscope_vinfo_df['vCenter'].unique()

# Dictionary to store summaries for each vCenter
vcenter_summaries = {}

# Function to format the table output
def format_table(headers, rows):
    horizontal_line = "─"
    vertical_line = "│"
    corner_tl, corner_tr = "╭", "╮"
    corner_bl, corner_br = "╰", "╯"
    join_t, join_b, join_c = "┬", "┴", "┼"
    col_widths = [max(len(str(item)) for item in col) for col in zip(headers, *rows)]
    
    def make_row(items):
        return vertical_line + vertical_line.join(f"{str(item).rjust(width)}" for item, width in zip(items, col_widths)) + vertical_line
    
    top_line = corner_tl + join_t.join(horizontal_line * width for width in col_widths) + corner_tr
    header_row = make_row(headers)
    divider_row = join_c.join(horizontal_line * width for width in col_widths).join(["├", "┤"])
    data_rows = [make_row(row) for row in rows[:-1]]
    totals_divider_row = join_c.join(horizontal_line * width for width in col_widths).join(["├", "┤"])
    totals_row = make_row(rows[-1])
    bottom_line = corner_bl + join_b.join(horizontal_line * width for width in col_widths) + corner_br
    return "\n".join([top_line, header_row, divider_row] + data_rows + [totals_divider_row, totals_row, bottom_line])

# Process each vCenter separately
for vcenter in vcenters:
    vcenter_df = inscope_vinfo_df[inscope_vinfo_df['vCenter'] == vcenter]
    disk_classification_summary = vcenter_df.groupby(['Complexity', 'OS Support'], observed=True).agg(
        VM_Count=('VM', 'count'),
        Total_Disk=('Disk Size TB', 'sum'),
        Total_Mig_Time_Minutes=('Total Time (minutes)', 'sum')
    ).reset_index()
    
    # Ensure all categories exist
    for complexity in complexity_order:
        for os_support in ['Supported', 'Not Supported', 'Unknown']:
            if not ((disk_classification_summary['Complexity'] == complexity) &
                    (disk_classification_summary['OS Support'] == os_support)).any():
                disk_classification_summary = pd.concat([
                    disk_classification_summary,
                    pd.DataFrame({
                        'Complexity': [complexity],
                        'OS Support': [os_support],
                        'VM_Count': [0],
                        'Total_Disk': [0.0],
                        'Total_Mig_Time_Minutes': [0]
                    })
                ], ignore_index=True)
    
    # Remove rows where VM_Count is zero
    disk_classification_summary = disk_classification_summary[disk_classification_summary['VM_Count'] > 0]
    
    # Set complexity order
    disk_classification_summary['Complexity'] = pd.Categorical(
        disk_classification_summary['Complexity'], categories=complexity_order, ordered=True
    )
    disk_classification_summary = disk_classification_summary.sort_values('Complexity')

    # Compute total migration time and disk
    total_disk_tb_numeric = disk_classification_summary['Total_Disk'].astype(float).sum()
    total_mig_time_minutes = disk_classification_summary['Total_Mig_Time_Minutes'].sum()

    # Format columns
    disk_classification_summary['Formatted_Mig_Time'] = disk_classification_summary['Total_Mig_Time_Minutes'].apply(
        lambda minutes: f"{minutes / 60:,.1f}h"
    )
    disk_classification_summary['Days_Per_FTEs'] = disk_classification_summary['Total_Mig_Time_Minutes'].apply(
        lambda minutes: f"{minutes / (fte_hours_per_day * 60 * fte_count):,.1f}"
    )

    disk_classification_summary['VM_Count'] = disk_classification_summary['VM_Count'].astype(int).apply(lambda x: f"{x:,}")
    disk_classification_summary['Total_Disk'] = disk_classification_summary['Total_Disk'].astype(float).apply(lambda x: f"{x:,.0f}")

    # Add totals row
    totals_row = {
        'Complexity': 'Totals',
        'OS Support': '',
        'VM_Count': f"{disk_classification_summary['VM_Count'].astype(str).replace(',', '', regex=True).astype(int).sum():,}",
        'Total_Disk': f"{total_disk_tb_numeric:,.0f}",
        'Formatted_Mig_Time': f"{total_mig_time_minutes / 60:,.1f}h",
        'Days_Per_FTEs': f"{total_mig_time_minutes / (fte_hours_per_day * 60 * fte_count):,.1f}"
    }
    disk_classification_summary = pd.concat([
        disk_classification_summary, pd.DataFrame([totals_row])
    ], ignore_index=True)
    
    vcenter_summaries[vcenter] = disk_classification_summary
    print(f"\n🔍 Migration Summary for vCenter: {vcenter}")
    headers = ["Complexity", "OS Support", "VM Count", "Total Disk (TB)", "Total Migration Time", "Total Days"]
    rows = disk_classification_summary[['Complexity', 'OS Support', 'VM_Count', 'Total_Disk', 'Formatted_Mig_Time', 'Days_Per_FTEs']].values.tolist()
    print(format_table(headers, rows))
# --- notebook cell 58 ---
import pandas as pd
import numpy as np

# Constants
MIGRATION_TIME_PER_500GB = 110   # minutes (1 hour 50 minutes per 500GB)
TE_HOURS_PER_DAY = 8             # 8 hours per day per FTE
FTE_COUNT = 10                   # 10 FTEs available
PMT_HOURS = 1                    # Post-migration troubleshooting time per VM in hours
PMT_MINUTES = PMT_HOURS * 60

# Validate input DataFrame
try:
    filtered_vinfo_df
except NameError:
    raise ValueError("filtered_vinfo_df is not defined. Ensure it is loaded before running this script.")

# Normalize column names
filtered_vinfo_df.columns = filtered_vinfo_df.columns.str.strip()

# Required columns
REQUIRED_COLUMNS = {'Environment', 'Disk Size TB', 'VM'}
missing_columns = REQUIRED_COLUMNS - set(filtered_vinfo_df.columns)

# Handle missing "Environment" column
if 'Environment' in missing_columns:
    print("⚠️ 'Environment' column is missing. Creating it with default value 'Unknown'.")
    filtered_vinfo_df['Environment'] = 'Unknown'
    missing_columns.remove('Environment')

# If other required columns are still missing, raise an error
if missing_columns:
    raise ValueError(f"Missing required columns: {missing_columns}")

# Preprocess DataFrame
inscope_vinfo_df = filtered_vinfo_df.copy()
inscope_vinfo_df['Environment'] = inscope_vinfo_df['Environment'].fillna('Unknown').astype(str).str.strip()
inscope_vinfo_df['VM'] = inscope_vinfo_df['VM'].fillna('Unknown VM')
inscope_vinfo_df['Disk Size TB'] = pd.to_numeric(inscope_vinfo_df['Disk Size TB'], errors='coerce').fillna(0)

# Compute Migration and Total Time
inscope_vinfo_df['Total Time (minutes)'] = inscope_vinfo_df['Disk Size TB'].apply(
    lambda size: ((size * 1024) / 500) * MIGRATION_TIME_PER_500GB + PMT_MINUTES
)

# Summarize data
environment_summary = inscope_vinfo_df.groupby('Environment', observed=True).agg(
    VM_Count=('VM', 'count'),
    Total_Disk_TB=('Disk Size TB', 'sum'),
    Total_Time_Minutes=('Total Time (minutes)', 'sum')
).reset_index()

# Compute Total Days and Weeks
environment_summary['Total_Days'] = environment_summary['Total_Time_Minutes'] / (TE_HOURS_PER_DAY * 60 * FTE_COUNT)
environment_summary['Total_Weeks'] = environment_summary['Total_Days'] / 5

# Add totals row (replace None with np.nan to avoid warning)
totals_row = {
    'Environment': 'Total',
    'VM_Count': environment_summary['VM_Count'].sum(),
    'Total_Disk_TB': environment_summary['Total_Disk_TB'].sum(),
    'Total_Time_Minutes': environment_summary['Total_Time_Minutes'].sum(),
    'Total_Days': environment_summary['Total_Days'].sum(),
    'Total_Weeks': environment_summary['Total_Weeks'].sum()
}

totals_df = pd.DataFrame([totals_row])
environment_summary = pd.concat([environment_summary, totals_df], ignore_index=True)

# Format columns for display
environment_summary['Total_Disk_TB'] = environment_summary['Total_Disk_TB'].map(lambda x: f"{x:.2f} TB" if pd.notnull(x) else "")
environment_summary['Total_Days'] = environment_summary['Total_Days'].map(lambda x: f"{x:.1f}" if pd.notnull(x) else "")
environment_summary['Total_Weeks'] = environment_summary['Total_Weeks'].map(lambda x: f"{x:.1f}" if pd.notnull(x) else "")

# Drop time in minutes for display purposes
environment_summary.drop(columns=['Total_Time_Minutes'], inplace=True)

# Display summary
display(environment_summary)
# --- notebook cell 60 ---
# Calculate global totals across all vCenters
global_total_mig_time = sum(
    summary['Total_Mig_Time_Minutes'].sum() for summary in vcenter_summaries.values()
)
global_total_days = global_total_mig_time / (fte_hours_per_day * 60 * fte_count)

# Calculate total weeks (assuming each week has 5 workdays)
total_global_weeks = global_total_days / 5

# Ensure all values are correctly formatted
print(f"✅️ Global Total Migration Time: {global_total_mig_time / 60:,.1f}h")
print(f"✅️ Global Total Days: {global_total_days:,.1f}")
print(f"✅️ Global Total Weeks: {total_global_weeks:,.1f}")

# --- overall risk score (web UI) ---
__risk_summary__ = _compute_overall_risk_summary()
__discovered_os__ = _discovered_os_lists()
__duration_recalc__ = _duration_recalc_payload()
