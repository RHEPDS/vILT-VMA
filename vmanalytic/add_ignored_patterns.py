import re

import pandas as pd

from pattern_io import append_unique_line

IGNORED_PATTERN_FILE = "helper_files/ignored_patterns.txt"


def clean_pattern(pattern):
    """Normalize patterns by removing extra spaces."""
    if pd.isna(pattern) or pattern.strip() == "":
        return ""
    return pattern.strip()


def format_pattern(pattern):
    """Build a case-insensitive regex pattern from user input."""
    cleaned_pattern = clean_pattern(pattern)
    return rf"(?i){re.escape(cleaned_pattern)}"


def main():
    while True:
        pattern = input("Enter pattern to ignore (or type 'exit' to quit): ").strip()
        if pattern.lower() == "exit":
            print("Exiting...")
            break

        formatted = format_pattern(pattern)
        if append_unique_line(IGNORED_PATTERN_FILE, formatted):
            print(f"[SUCCESS] Added pattern: {formatted}")
        else:
            print(f"[INFO] Pattern already exists: {formatted}")


if __name__ == "__main__":
    main()
