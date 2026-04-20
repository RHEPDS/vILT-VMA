import re

import pandas as pd

from pattern_io import append_unique_line

OS_FILTER_FILE = "helper_files/os_filter_patterns.txt"


def clean_os_name(os_name):
    """Normalize OS names by removing extra spaces and redundant information."""
    if pd.isna(os_name) or os_name.strip() == "":
        return ""
    os_name = os_name.strip()
    os_name = re.sub(r"\s*\(.*\)$", "", os_name)
    os_name = re.sub(r"\s+", " ", os_name)
    return os_name


def format_os_pattern(os_name):
    """Build a regex pattern for a cleaned OS name."""
    cleaned_os_name = clean_os_name(os_name)
    os_name_escaped = re.escape(cleaned_os_name)
    return rf"^{os_name_escaped}(?:\s*\(.*\))?$"


def main():
    while True:
        os_name = input("Enter OS name (or type 'exit' to quit): ").strip()
        if os_name.lower() == "exit":
            print("Exiting...")
            break

        pattern = format_os_pattern(os_name)
        if append_unique_line(OS_FILTER_FILE, pattern):
            print(f"[SUCCESS] Added pattern: {pattern}")
        else:
            print(f"[INFO] Pattern already exists: {pattern}")


if __name__ == "__main__":
    main()
