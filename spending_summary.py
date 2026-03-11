#!/usr/bin/env python3
"""
Analyze spending by category, week, and month.
Creates summaries and CSV reports of spending patterns.
Separates positive spending from negative amounts (payments/credits).
"""

import pandas as pd
from pathlib import Path

def analyze_spending():
    """Read transactions and generate spending summaries by week and month."""

    # Read the combined transactions CSV
    csv_file = Path(__file__).parent / 'transactions' / 'combined_transactions.csv'

    if not csv_file.exists():
        print(f"Error: {csv_file} not found")
        return False

    print(f"Reading transactions from {csv_file}...")
    df = pd.read_csv(csv_file)

    # Convert Date to datetime
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')

    # Remove rows with missing dates or amounts
    df = df.dropna(subset=['Date', 'Amount'])

    # Get the category column (use Unified_Category if available, otherwise Category)
    category_col = 'Unified_Category' if 'Unified_Category' in df.columns else 'Category'

    # Find categories with negative values
    categories_with_negatives = set(df[df['Amount'] < 0][category_col].unique())

    print(f"Total transactions: {len(df)}")
    print(f"Date range: {df['Date'].min().date()} to {df['Date'].max().date()}")
    print(f"Using category column: {category_col}")
    print(f"Categories with negative amounts: {len(categories_with_negatives)}\n")

    # === OVERALL SPENDING BY CATEGORY ===
    print("=" * 60)
    print("OVERALL SPENDING BY CATEGORY")
    print("=" * 60)

    category_spending = df.groupby(category_col)['Amount'].agg(['sum', 'count']).sort_values('sum', ascending=False)
    category_spending.columns = ['Total Spent', 'Transaction Count']

    for category, row in category_spending.iterrows():
        if category in categories_with_negatives:
            positive = df[(df[category_col] == category) & (df['Amount'] > 0)]['Amount'].sum()
            negative = df[(df[category_col] == category) & (df['Amount'] < 0)]['Amount'].sum()
            print(f"{category:45} Positive: ${positive:>10.2f}  Negative: ${negative:>10.2f}  Net: ${row['Total Spent']:>10.2f}  ({int(row['Transaction Count']):>3} transactions)")
        else:
            print(f"{category:45} ${row['Total Spent']:>10.2f}  ({int(row['Transaction Count']):>3} transactions)")

    total_positive = df[df['Amount'] > 0]['Amount'].sum()
    total_negative = df[df['Amount'] < 0]['Amount'].sum()
    print(f"\nTotal positive (spending): ${total_positive:.2f}")
    print(f"Total negative (payments): ${total_negative:.2f}")
    print(f"Net total: ${df['Amount'].sum():.2f}\n")

    # === WEEKLY SPENDING ===
    print("=" * 60)
    print("WEEKLY SPENDING BY CATEGORY")
    print("=" * 60)

    # Create week-year column for grouping
    df['Year'] = df['Date'].dt.isocalendar().year
    df['Week'] = df['Date'].dt.isocalendar().week
    df['Week_Start'] = df['Date'] - pd.to_timedelta(df['Date'].dt.dayofweek, unit='d')

    # Group by year, week, and category
    weekly_spending = df.groupby(['Year', 'Week', 'Week_Start', category_col])['Amount'].sum().reset_index()
    weekly_spending.columns = ['Year', 'Week', 'Week_Start', 'Category', 'Amount']
    weekly_spending = weekly_spending.sort_values(['Week_Start', 'Amount'], ascending=[False, False])

    # Display weekly summary
    for (year, week), group in weekly_spending.groupby(['Year', 'Week']):
        week_start = group.iloc[0]['Week_Start'].strftime('%Y-%m-%d')
        total_week = group['Amount'].sum()
        print(f"\nWeek of {week_start} (Total: ${total_week:.2f})")
        for _, row in group.iterrows():
            cat = row['Category']
            if cat in categories_with_negatives:
                positive = df[(df[category_col] == cat) & (df['Amount'] > 0) & (df['Week'] == week) & (df['Year'] == year)]['Amount'].sum()
                negative = df[(df[category_col] == cat) & (df['Amount'] < 0) & (df['Week'] == week) & (df['Year'] == year)]['Amount'].sum()
                if positive != 0 or negative != 0:
                    print(f"  {cat:40} Pos: ${positive:>10.2f}  Neg: ${negative:>10.2f}")
            else:
                if row['Amount'] != 0:
                    print(f"  {cat:40} ${row['Amount']:>10.2f}")

    # Save weekly spending to CSV with split columns for categories with negatives
    weekly_csv = csv_file.parent / 'weekly_spending.csv'

    # Build weekly data with split columns
    weekly_data = []
    for (year, week), group_data in df.groupby(['Year', 'Week']):
        week_start = group_data.iloc[0]['Week_Start'].strftime('%Y-%m-%d')
        row = {'Year': year, 'Week': week, 'Week_Start': week_start}

        # Add spending by category
        for cat in df[category_col].unique():
            cat_data = group_data[group_data[category_col] == cat]
            if len(cat_data) > 0:
                if cat in categories_with_negatives:
                    positive = cat_data[cat_data['Amount'] > 0]['Amount'].sum()
                    negative = cat_data[cat_data['Amount'] < 0]['Amount'].sum()
                    row[f"{cat}_Positive"] = positive
                    row[f"{cat}_Negative"] = negative
                else:
                    row[cat] = cat_data['Amount'].sum()

        weekly_data.append(row)

    weekly_df = pd.DataFrame(weekly_data)

    # Add total columns
    category_cols = [col for col in weekly_df.columns if col not in ['Year', 'Week', 'Week_Start']]

    # Calculate totals
    def sum_positives(row):
        total = 0
        for cat in df[category_col].unique():
            if cat not in categories_with_negatives:
                col = cat
                if col in row.index:
                    total += row[col] if row[col] > 0 else 0
            else:
                col = f"{cat}_Positive"
                if col in row.index:
                    total += row[col] if row[col] > 0 else 0
        return total

    def sum_negatives(row):
        total = 0
        for cat in categories_with_negatives:
            col = f"{cat}_Negative"
            if col in row.index:
                total += row[col] if row[col] < 0 else 0
        return total

    weekly_df['Total_Positive'] = weekly_df.apply(sum_positives, axis=1)
    weekly_df['Total_Negative'] = weekly_df.apply(sum_negatives, axis=1)
    weekly_df['Net_Total'] = weekly_df['Total_Positive'] + weekly_df['Total_Negative']

    # Reorder columns
    col_order = ['Year', 'Week', 'Week_Start'] + [col for col in weekly_df.columns if col not in ['Year', 'Week', 'Week_Start', 'Total_Positive', 'Total_Negative', 'Net_Total']] + ['Total_Positive', 'Total_Negative', 'Net_Total']
    weekly_df = weekly_df[col_order]
    weekly_df = weekly_df.sort_values('Week_Start', ascending=False)
    weekly_df.to_csv(weekly_csv, index=False)
    print(f"\n✓ Weekly spending saved to {weekly_csv}")

    # === MONTHLY SPENDING ===
    print("\n" + "=" * 60)
    print("MONTHLY SPENDING BY CATEGORY")
    print("=" * 60)

    df['Year_Month'] = df['Date'].dt.to_period('M')

    monthly_spending = df.groupby(['Year_Month', category_col])['Amount'].sum().reset_index()
    monthly_spending.columns = ['Year_Month', 'Category', 'Amount']
    monthly_spending = monthly_spending.sort_values(['Year_Month', 'Amount'], ascending=[False, False])

    # Display monthly summary
    for year_month, group in monthly_spending.groupby('Year_Month'):
        total_month = group['Amount'].sum()
        print(f"\n{year_month} (Total: ${total_month:.2f})")
        for _, row in group.iterrows():
            cat = row['Category']
            if cat in categories_with_negatives:
                positive = df[(df[category_col] == cat) & (df['Amount'] > 0) & (df['Year_Month'] == year_month)]['Amount'].sum()
                negative = df[(df[category_col] == cat) & (df['Amount'] < 0) & (df['Year_Month'] == year_month)]['Amount'].sum()
                if positive != 0 or negative != 0:
                    print(f"  {cat:40} Pos: ${positive:>10.2f}  Neg: ${negative:>10.2f}")
            else:
                if row['Amount'] != 0:
                    print(f"  {cat:40} ${row['Amount']:>10.2f}")

    # Save monthly spending to CSV with split columns for categories with negatives
    monthly_csv = csv_file.parent / 'monthly_spending.csv'

    # Build monthly data with split columns
    monthly_data = []
    for year_month in df['Year_Month'].unique():
        group_data = df[df['Year_Month'] == year_month]
        row = {'Year_Month': str(year_month)}

        # Add spending by category
        for cat in df[category_col].unique():
            cat_data = group_data[group_data[category_col] == cat]
            if len(cat_data) > 0:
                if cat in categories_with_negatives:
                    positive = cat_data[cat_data['Amount'] > 0]['Amount'].sum()
                    negative = cat_data[cat_data['Amount'] < 0]['Amount'].sum()
                    row[f"{cat}_Positive"] = positive
                    row[f"{cat}_Negative"] = negative
                else:
                    row[cat] = cat_data['Amount'].sum()

        monthly_data.append(row)

    monthly_df = pd.DataFrame(monthly_data)

    # Add total columns
    monthly_df['Total_Positive'] = monthly_df.apply(sum_positives, axis=1)
    monthly_df['Total_Negative'] = monthly_df.apply(sum_negatives, axis=1)
    monthly_df['Net_Total'] = monthly_df['Total_Positive'] + monthly_df['Total_Negative']

    # Reorder columns
    col_order = ['Year_Month'] + [col for col in monthly_df.columns if col not in ['Year_Month', 'Total_Positive', 'Total_Negative', 'Net_Total']] + ['Total_Positive', 'Total_Negative', 'Net_Total']
    monthly_df = monthly_df[col_order]
    monthly_df = monthly_df.sort_values('Year_Month', ascending=False)
    monthly_df.to_csv(monthly_csv, index=False)
    print(f"\n✓ Monthly spending saved to {monthly_csv}")

    # === SUMMARY TABLES ===
    print("\n" + "=" * 60)
    print("SUMMARY: WEEKLY SPENDING BY CATEGORY")
    print("=" * 60)
    print(weekly_df.to_string(index=False))

    print("\n" + "=" * 60)
    print("SUMMARY: MONTHLY SPENDING BY CATEGORY")
    print("=" * 60)
    print(monthly_df.to_string(index=False))

    return True


if __name__ == '__main__':
    analyze_spending()
