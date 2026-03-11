#!/usr/bin/env python3
"""
Combine credit card transactions from Amex and Discover into a single CSV
with unified categories.
"""

import pandas as pd
import os
from pathlib import Path
from numbers_parser import Document

# Define category mappings to consolidate similar categories from both cards
# Map specific categories to unified category names
CATEGORY_MAPPING = {
    # Travel/Transportation
    'travel': 'Travel',
    'travel/entertainment': 'Travel',
    'transportation': 'Travel',
    'flights': 'Travel',
    'hotels': 'Travel',
    'taxi': 'Travel',
    'uber': 'Travel',
    'gas': 'Travel',
    'parking': 'Travel',

    # Entertainment
    'entertainment': 'Entertainment',
    'movies': 'Entertainment',
    'concerts': 'Entertainment',
    'streaming': 'Entertainment',
    'sports': 'Entertainment',

    # Food & Dining
    'food': 'Food & Dining',
    'dining': 'Food & Dining',
    'restaurants': 'Food & Dining',
    'groceries': 'Food & Dining',
    'coffee': 'Food & Dining',
    'fast food': 'Food & Dining',

    # Shopping
    'shopping': 'Shopping',
    'retail': 'Shopping',
    'clothing': 'Shopping',
    'home': 'Shopping',
    'furniture': 'Shopping',

    # Utilities & Services
    'utilities': 'Utilities & Services',
    'phone': 'Utilities & Services',
    'internet': 'Utilities & Services',
    'subscription': 'Utilities & Services',
    'services': 'Utilities & Services',

    # Healthcare
    'healthcare': 'Healthcare',
    'medical': 'Healthcare',
    'pharmacy': 'Healthcare',
    'doctor': 'Healthcare',

    # Education
    'education': 'Education',
    'books': 'Education',
    'courses': 'Education',

    # Business Services
    'business': 'Business Services',
    'office': 'Business Services',

    # Miscellaneous
    'other': 'Other',
    'misc': 'Other',
}


def read_numbers_file(filepath):
    """Read a Numbers spreadsheet file and return a pandas DataFrame."""
    try:
        doc = Document(filepath)
        sheet = doc.sheets[0]
        table = sheet.tables[0]

        # Convert sheet data to list of lists
        data = []
        for row in table.rows():
            data.append([cell.value for cell in row])

        # First row is headers
        if len(data) > 0:
            headers = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=headers)
            return df
        else:
            return None
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None


def normalize_category(category):
    """Normalize a category string to the unified category system."""
    if pd.isna(category):
        return 'Other'

    category_lower = str(category).strip().lower()

    # Check if we have a direct mapping
    if category_lower in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[category_lower]

    # Check for partial matches
    for key, value in CATEGORY_MAPPING.items():
        if key in category_lower:
            return value

    # Default to the original category if no mapping found
    return category


def combine_transactions(amex_file, discover_file, output_file):
    """Combine transactions from both credit cards into a single CSV."""

    print("Reading Amex transactions...")
    amex_df = read_numbers_file(amex_file)

    print("Reading Discover transactions...")
    discover_df = read_numbers_file(discover_file)

    if amex_df is None or discover_df is None:
        print("Error: Could not read one or both files")
        return False

    print(f"\nAmex transactions: {len(amex_df)}")
    print(f"Discover transactions: {len(discover_df)}")

    print("\nAmex columns:", amex_df.columns.tolist())
    print("Discover columns:", discover_df.columns.tolist())

    # Identify category column (adjust these column names if different in your files)
    amex_category_col = None
    discover_category_col = None

    for col in amex_df.columns:
        if 'category' in str(col).lower():
            amex_category_col = col
            break

    for col in discover_df.columns:
        if 'category' in str(col).lower():
            discover_category_col = col
            break

    if amex_category_col is None:
        print("Warning: Could not find category column in Amex file")
        amex_category_col = amex_df.columns[2] if len(amex_df.columns) > 2 else amex_df.columns[-1]

    if discover_category_col is None:
        print("Warning: Could not find category column in Discover file")
        discover_category_col = discover_df.columns[2] if len(discover_df.columns) > 2 else discover_df.columns[-1]

    # Standardize date columns
    print("\nStandardizing date columns...")

    # Find date columns in each dataframe
    amex_date_col = None
    discover_date_col = None

    for col in amex_df.columns:
        if 'date' in str(col).lower():
            amex_date_col = col
            break

    for col in discover_df.columns:
        if 'date' in str(col).lower():
            discover_date_col = col
            break

    # Rename date columns to a standard "Date" column
    if amex_date_col:
        amex_df = amex_df.rename(columns={amex_date_col: 'Date'})
    if discover_date_col:
        discover_df = discover_df.rename(columns={discover_date_col: 'Date'})

    # Normalize categories
    print("\nNormalizing categories...")
    amex_df['Unified_Category'] = amex_df[amex_category_col].apply(normalize_category)
    discover_df['Unified_Category'] = discover_df[discover_category_col].apply(normalize_category)

    print("\nUnified categories in Amex:", amex_df['Unified_Category'].unique())
    print("Unified categories in Discover:", discover_df['Unified_Category'].unique())

    # Combine the dataframes
    combined_df = pd.concat([amex_df, discover_df], ignore_index=True)

    # Convert date column to datetime and sort
    if 'Date' in combined_df.columns:
        combined_df['Date'] = pd.to_datetime(combined_df['Date'], errors='coerce')
        combined_df = combined_df.sort_values(by='Date', ascending=False)

    # Save to CSV
    combined_df.to_csv(output_file, index=False)

    print(f"\n✓ Combined {len(combined_df)} transactions saved to {output_file}")
    print(f"\nCategory breakdown:")
    print(combined_df['Unified_Category'].value_counts())

    return True


if __name__ == '__main__':
    # Get the directory where this script is located
    script_dir = Path(__file__).parent

    amex_file = script_dir / 'transactions' / 'amex.numbers'
    discover_file = script_dir / 'transactions' / 'Discover.numbers'
    output_file = script_dir / 'transactions' / 'combined_transactions.csv'

    # If .csv files exist (with Numbers format), use those
    if not amex_file.exists():
        amex_file = script_dir / 'transactions' / 'amex.csv'
    if not discover_file.exists():
        discover_file = script_dir / 'transactions' / 'Discover.csv'

    print(f"Looking for files:")
    print(f"  Amex: {amex_file}")
    print(f"  Discover: {discover_file}")

    if not amex_file.exists() or not discover_file.exists():
        print("\nError: Input files not found")
        exit(1)

    combine_transactions(amex_file, discover_file, output_file)
