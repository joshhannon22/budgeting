#!/usr/bin/env python3
"""
Monthly budget report: compares current month spending against budget,
analyzes previous month performance, and generates a human-readable summary with Claude.
"""

import json
import os
from pathlib import Path
from datetime import datetime

import anthropic
import pandas as pd

from notifications import Notifier, build_tldr_prompt


# ─────────────────────────────────────────────
# Data extraction
# ─────────────────────────────────────────────

def load_budget(budget_file: Path) -> dict:
    """Load budget from JSON file."""
    with open(budget_file) as f:
        return json.load(f)


def get_current_and_previous_months(df: pd.DataFrame):
    """
    Return current month data and previous month data.
    Current month is based on the most recent transactions.
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])

    # Get the most recent date to determine current month
    max_date = df["Date"].max()
    current_year = max_date.year
    current_month = max_date.month

    # Determine if we should use today's date or max transaction date
    today = pd.Timestamp.today()
    if today.year == current_year and today.month == current_month:
        # Current month is ongoing, use today as the reference
        current_month_ts = pd.Timestamp(year=current_year, month=current_month, day=1)
    else:
        # Current month is in the past, use the month from the data
        current_month_ts = pd.Timestamp(year=current_year, month=current_month, day=1)

    # Calculate previous month
    if current_month == 1:
        prev_month_ts = pd.Timestamp(year=current_year - 1, month=12, day=1)
    else:
        prev_month_ts = pd.Timestamp(year=current_year, month=current_month - 1, day=1)

    # Filter data for each month
    current_month_df = df[
        (df["Date"].dt.year == current_month_ts.year) &
        (df["Date"].dt.month == current_month_ts.month)
    ].copy()

    prev_month_df = df[
        (df["Date"].dt.year == prev_month_ts.year) &
        (df["Date"].dt.month == prev_month_ts.month)
    ].copy()

    return (current_month_df, prev_month_df,
            current_month_ts, prev_month_ts)


def calculate_month_pace(current_month_df: pd.DataFrame,
                        current_month_ts: pd.Timestamp,
                        budget_amount: float) -> dict:
    """
    Calculate if spending is on pace for the month.
    Returns dict with spending data and pace analysis.
    """
    today = pd.Timestamp.today()

    # Days elapsed in month (from start to today or end of data)
    days_in_month = pd.Timestamp(
        year=current_month_ts.year,
        month=current_month_ts.month,
        day=1
    ).days_in_month

    if current_month_ts.year == today.year and current_month_ts.month == today.month:
        # Current month is ongoing
        days_elapsed = today.day
        max_date = today
    else:
        # Month is complete or partially complete based on data
        days_elapsed = days_in_month
        max_date = current_month_df["Date"].max() if len(current_month_df) > 0 else current_month_ts

    # Total spending (sum of positive amounts)
    total_spending = current_month_df[current_month_df["Amount"] > 0]["Amount"].sum()

    # Expected spending at this pace
    daily_budget = budget_amount / days_in_month
    expected_spending = daily_budget * days_elapsed

    # Pace percentage
    pace_pct = (days_elapsed / days_in_month) * 100
    spending_pct = (total_spending / budget_amount * 100) if budget_amount > 0 else 0

    # Determine if on track
    remaining_days = days_in_month - days_elapsed
    remaining_budget = budget_amount - total_spending

    if remaining_days > 0:
        daily_remaining = remaining_budget / remaining_days
        on_track = total_spending <= expected_spending
        status = "on track" if on_track else "over pace"
    else:
        daily_remaining = 0
        on_track = total_spending <= budget_amount
        status = "under budget" if on_track else "over budget"

    return {
        "total_spending": round(total_spending, 2),
        "budget": budget_amount,
        "spent_percentage": round(spending_pct, 1),
        "remaining": round(budget_amount - total_spending, 2),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "pace_percentage": round(pace_pct, 1),
        "expected_spending": round(expected_spending, 2),
        "daily_budget": round(daily_budget, 2),
        "daily_remaining": round(daily_remaining, 2),
        "on_track": on_track,
        "status": status,
    }


def build_month_summary(month_df: pd.DataFrame, category_col: str,
                       categories_with_negatives: set) -> dict:
    """
    Build a dict: { category: {positive, negative, net} }
    plus overall totals.
    """
    summary = {}

    for cat, group in month_df.groupby(category_col):
        positive = group[group["Amount"] > 0]["Amount"].sum()
        negative = group[group["Amount"] < 0]["Amount"].sum()
        net = positive + negative

        if cat in categories_with_negatives:
            summary[cat] = {
                "positive": round(positive, 2),
                "negative": round(negative, 2),
                "net": round(net, 2),
            }
        else:
            summary[cat] = {
                "positive": round(positive, 2),
                "negative": 0.0,
                "net": round(net, 2),
            }

    total_positive = month_df[month_df["Amount"] > 0]["Amount"].sum()
    total_negative = month_df[month_df["Amount"] < 0]["Amount"].sum()
    summary["__totals__"] = {
        "total_positive": round(total_positive, 2),
        "total_negative": round(total_negative, 2),
        "net_total": round(total_positive + total_negative, 2),
    }

    return summary


def format_category_block(label: str, summary: dict) -> str:
    lines = [f"=== {label} ==="]
    totals = summary.pop("__totals__", {})

    for cat, vals in sorted(summary.items()):
        if vals["negative"] != 0:
            lines.append(
                f"  {cat}: spending ${vals['positive']:,.2f} | "
                f"credits/payments ${vals['negative']:,.2f} | "
                f"net ${vals['net']:,.2f}"
            )
        else:
            lines.append(f"  {cat}: ${vals['positive']:,.2f}")

    lines.append("")
    lines.append(
        f"  TOTAL SPENDING:  ${totals.get('total_positive', 0):,.2f}"
    )
    lines.append(
        f"  TOTAL CREDITS:   ${totals.get('total_negative', 0):,.2f}"
    )
    lines.append(
        f"  NET TOTAL:       ${totals.get('net_total', 0):,.2f}"
    )
    # restore
    summary["__totals__"] = totals
    return "\n".join(lines)


def categorize_for_budget(unified_category: str) -> str:
    """Map unified categories to budget categories for analysis."""
    cat_lower = unified_category.lower()

    # Groceries: food & dining
    if any(x in cat_lower for x in ["food", "grocery", "dining"]):
        return "Food & Groceries"

    # Travel: transportation
    if any(x in cat_lower for x in ["travel", "transportation", "gas", "parking", "uber", "taxi", "flight"]):
        return "Travel & Transportation"

    # Everything else
    return "Other Expenses"


def build_previous_month_budget_analysis(prev_month_df: pd.DataFrame,
                                        category_col: str,
                                        categories_with_negatives: set) -> tuple:
    """
    Build analysis of previous month net spending by category (excluding Other).
    Returns (text_block, net_spending_dict) for use in summaries and Claude prompt.
    """
    prev_month_df = prev_month_df.copy()

    # Calculate net spending by unified category (excluding "Other")
    net_spending = {}
    for cat in sorted(prev_month_df[category_col].unique()):
        # Skip the "Other" category
        if cat.lower() == "other":
            continue

        cat_data = prev_month_df[prev_month_df[category_col] == cat]
        positive = cat_data[cat_data["Amount"] > 0]["Amount"].sum()
        negative = cat_data[cat_data["Amount"] < 0]["Amount"].sum()
        net = positive + negative

        net_spending[cat] = {
            "positive": round(positive, 2),
            "negative": round(negative, 2),
            "net": round(net, 2)
        }

    # Build the text block
    lines = ["=== PREVIOUS MONTH NET SPENDING BY CATEGORY (excluding Other category) ==="]
    lines.append("")

    total_net = 0
    for cat in sorted(net_spending.keys()):
        data = net_spending[cat]
        total_net += data["net"]

        if data["negative"] != 0:
            lines.append(
                f"{cat}: ${data['positive']:,.2f} (spend) + ${data['negative']:,.2f} (credits) = ${data['net']:,.2f} (net)"
            )
        else:
            lines.append(f"{cat}: ${data['net']:,.2f}")

    lines.append("")
    lines.append(f"TOTAL NET SPENDING (excluding Other): ${total_net:,.2f}")
    lines.append("")
    lines.append("This net spending is what actually left your account for each category,")
    lines.append("accounting for refunds and credits. Use this for budget analysis.")

    return "\n".join(lines), net_spending


def build_budget_analysis_prompt_section(net_spending: dict, budget_amount: float) -> str:
    """Build the budget analysis section for Claude's prompt."""
    lines = ["=== PREVIOUS MONTH BUDGET ANALYSIS (for budget planning) ==="]
    lines.append(f"Total monthly discretionary budget: ${budget_amount:,.2f}")
    lines.append("")
    lines.append("Previous month net spending by category (excluding Other category):")
    lines.append("")

    total_net = 0
    for cat in sorted(net_spending.keys()):
        data = net_spending[cat]
        total_net += data["net"]
        lines.append(f"  {cat}: ${data['net']:,.2f}")

    lines.append("")
    lines.append(f"Total: ${total_net:,.2f}")
    lines.append("")

    # Calculate how much over/under
    difference = budget_amount - total_net
    status = "UNDER" if difference > 0 else "OVER"
    lines.append(f"Previous month was ${abs(difference):,.2f} {status} budget")
    lines.append("")
    lines.append("Analyze which categories were the biggest drivers of overspending")
    lines.append("and recommend where to cut back to stay within budget.")

    return "\n".join(lines)


def build_prompt(current_label: str, previous_label: str,
                current_summary: dict, previous_summary: dict,
                current_pace: dict, budget_amount: float,
                prev_month_budget_analysis: str, net_spending: dict) -> str:
    current_block = format_category_block(f"CURRENT MONTH ({current_label})", {**current_summary})
    previous_block = format_category_block(f"PREVIOUS MONTH ({previous_label})", {**previous_summary})

    budget_analysis_section = build_budget_analysis_prompt_section(net_spending, budget_amount)

    pace_info = f"""
=== CURRENT MONTH BUDGET ANALYSIS ===
Budget for discretionary spending: ${budget_amount:,.2f}
Days elapsed: {current_pace['days_elapsed']} of {current_pace['days_in_month']}
Month progress: {current_pace['pace_percentage']:.1f}%

Current spending: ${current_pace['total_spending']:,.2f}
Spending progress: {current_pace['spent_percentage']:.1f}%
Status: {current_pace['status'].upper()}

Expected spending at this pace: ${current_pace['expected_spending']:,.2f}
Daily budget: ${current_pace['daily_budget']:,.2f}
Remaining budget: ${current_pace['remaining']:,.2f}
Daily remaining: ${current_pace['daily_remaining']:,.2f}
"""

    return f"""You are a personal finance assistant. Below is a structured summary of monthly spending data compared against a budget. Write a clear, human-friendly breakdown of my finances.

Your summary should:
1. Open with a short high-level overview of current month spending vs budget — am I on pace, over, or under?
2. Break down the current month by category — how much in each area, any credits/refunds?
3. **BUDGET ANALYSIS:** Use the "PREVIOUS MONTH BUDGET ANALYSIS" section to analyze which categories overspent and where cuts should be made. Calculate how much each category was over/under budget.
4. Compare previous month overall performance vs current month pacing.
5. Provide actionable insights: if on pace, what areas to watch? If over, where to cut? If under, where the savings are. Reference the previous month breakdown to show patterns.
6. Conclude with a brief outlook for the rest of the month.

Use plain language, dollar amounts, and be concise. Focus on what's notable or actionable, not every single number.

---

{current_block}

{previous_block}

{prev_month_budget_analysis}

{budget_analysis_section}

{pace_info}
"""


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    script_dir = Path(__file__).parent
    csv_file = script_dir / "transactions" / "combined_transactions.csv"
    budget_file = script_dir / "transactions" / "budget.json"

    if not csv_file.exists():
        print(f"Error: {csv_file} not found. Run combine.py first.")
        return

    if not budget_file.exists():
        print(f"Error: {budget_file} not found.")
        return

    print("Reading transactions...")
    df = pd.read_csv(csv_file)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Amount"])

    print("Loading budget...")
    budget_data = load_budget(budget_file)
    budget_amount = budget_data["monthly_budget"]["leftover_after_fixed"]

    # Extract months
    current_month_df, prev_month_df, current_month_ts, prev_month_ts = (
        get_current_and_previous_months(df)
    )

    category_col = "Unified_Category" if "Unified_Category" in df.columns else "Category"
    categories_with_negatives = set(df[df["Amount"] < 0][category_col].unique())

    current_label = current_month_ts.strftime("%Y-%m")
    prev_label = prev_month_ts.strftime("%Y-%m")

    current_start_str = current_month_ts.strftime("%B %d, %Y")
    current_end_str = pd.Timestamp(
        year=current_month_ts.year,
        month=current_month_ts.month,
        day=current_month_ts.days_in_month
    ).strftime("%B %d, %Y")

    prev_start_str = prev_month_ts.strftime("%B %d, %Y")
    prev_end_str = pd.Timestamp(
        year=prev_month_ts.year,
        month=prev_month_ts.month,
        day=prev_month_ts.days_in_month
    ).strftime("%B %d, %Y")

    print(f"\nCurrent Month: {current_label} ({len(current_month_df)} transactions)")
    print(f"  {current_start_str} to {current_end_str}")
    print(f"Previous Month: {prev_label} ({len(prev_month_df)} transactions)")
    print(f"  {prev_start_str} to {prev_end_str}")
    print(f"Monthly budget (leftover after fixed): ${budget_amount:,.2f}\n")

    # Build summaries
    current_summary = build_month_summary(current_month_df, category_col, categories_with_negatives)
    prev_summary = build_month_summary(prev_month_df, category_col, categories_with_negatives)

    # Calculate pace
    current_pace = calculate_month_pace(current_month_df, current_month_ts, budget_amount)

    # Build previous month budget analysis
    prev_month_budget_analysis, net_spending = build_previous_month_budget_analysis(
        prev_month_df, category_col, categories_with_negatives
    )

    # Print structured data
    print("=" * 60)
    print(format_category_block(f"CURRENT MONTH ({current_label})", {**current_summary}))
    print()
    print(format_category_block(f"PREVIOUS MONTH ({prev_label})", {**prev_summary}))
    print()
    print(prev_month_budget_analysis)
    print()
    print(f"=== CURRENT MONTH BUDGET ANALYSIS ===")
    print(f"Budget for discretionary spending: ${budget_amount:,.2f}")
    print(f"Days elapsed: {current_pace['days_elapsed']} of {current_pace['days_in_month']}")
    print(f"Month progress: {current_pace['pace_percentage']:.1f}%")
    print(f"")
    print(f"Current spending: ${current_pace['total_spending']:,.2f}")
    print(f"Spending progress: {current_pace['spent_percentage']:.1f}%")
    print(f"Status: {current_pace['status'].upper()}")
    print(f"")
    print(f"Expected spending at this pace: ${current_pace['expected_spending']:,.2f}")
    print(f"Daily budget: ${current_pace['daily_budget']:,.2f}")
    print(f"Remaining budget: ${current_pace['remaining']:,.2f}")
    print(f"Daily remaining: ${current_pace['daily_remaining']:,.2f}")
    print()

    # Call Claude
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        return

    prompt = build_prompt(current_label, prev_label,
                         {**current_summary}, {**prev_summary},
                         current_pace, budget_amount, prev_month_budget_analysis, net_spending)

    print("=" * 60)
    print("Generating AI summary with Claude...")
    print("=" * 60)
    print()

    client = anthropic.Anthropic(api_key=api_key)
    summary_text = ""

    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=(
            "You are a concise, friendly personal finance assistant. "
            "Write summaries in plain English with dollar amounts. "
            "Keep the tone helpful and non-judgmental."
        ),
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            summary_text += text

    final = stream.get_final_message()
    print("\n")

    # Generate TLDR for notifications
    print("=" * 60)
    print("Generating TLDR summary...")
    print("=" * 60)
    print()

    tldr_prompt = build_tldr_prompt("monthly", format_category_block(f"CURRENT MONTH ({current_label})", {**current_summary}))

    tldr_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=(
            "You are a concise personal finance assistant. "
            "Generate very brief, actionable summaries."
        ),
        messages=[{"role": "user", "content": tldr_prompt}],
    ) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
            tldr_text += text

    print("\n")

    # Prepend TLDR to summary
    full_summary_text = f"📱 TLDR\n{tldr_text}\n\n---\n\n{summary_text}"

    # Create monthly_exports directory
    export_dir = script_dir / "monthly_exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # Export CSV files
    current_csv = export_dir / f"monthly_data_{current_label}.csv"
    prev_csv = export_dir / f"monthly_data_{prev_label}.csv"
    current_month_df.to_csv(current_csv, index=False)
    prev_month_df.to_csv(prev_csv, index=False)
    print(f"✓ Current month data exported to {current_csv}")
    print(f"✓ Previous month data exported to {prev_csv}")

    # Export budget analysis data as JSON
    budget_analysis_json = export_dir / f"budget_analysis_{prev_label}.json"
    with open(budget_analysis_json, "w") as f:
        json.dump({
            "month": prev_label,
            "budget": budget_amount,
            "net_spending_by_category": net_spending,
            "total_net_spending": round(sum(cat["net"] for cat in net_spending.values()), 2)
        }, f, indent=2)
    print(f"✓ Budget analysis exported to {budget_analysis_json}")

    # Save report to file
    output_file = export_dir / f"monthly_report_{current_label}.txt"

    with open(output_file, "w") as f:
        f.write(f"Monthly Budget Report\n")
        f.write(f"Current Month: {current_label} ({current_start_str} to {current_end_str})\n")
        f.write(f"Previous Month: {prev_label} ({prev_start_str} to {prev_end_str})\n")
        f.write(f"Budget (leftover after fixed): ${budget_amount:,.2f}\n")
        f.write("=" * 60 + "\n\n")
        f.write(full_summary_text)
        f.write("\n\n" + "=" * 60 + "\n")
        f.write("RAW DATA\n")
        f.write("=" * 60 + "\n\n")
        f.write(format_category_block(f"CURRENT MONTH ({current_label})", {**current_summary}))
        f.write("\n\n")
        f.write(format_category_block(f"PREVIOUS MONTH ({prev_label})", {**prev_summary}))
        f.write("\n\n")
        f.write(prev_month_budget_analysis)
        f.write("\n\n")
        f.write(build_budget_analysis_prompt_section(net_spending, budget_amount))
        f.write("\n\n")
        f.write(f"=== CURRENT MONTH BUDGET ANALYSIS ===\n")
        f.write(f"Budget for discretionary spending: ${budget_amount:,.2f}\n")
        f.write(f"Days elapsed: {current_pace['days_elapsed']} of {current_pace['days_in_month']}\n")
        f.write(f"Month progress: {current_pace['pace_percentage']:.1f}%\n\n")
        f.write(f"Current spending: ${current_pace['total_spending']:,.2f}\n")
        f.write(f"Spending progress: {current_pace['spent_percentage']:.1f}%\n")
        f.write(f"Status: {current_pace['status'].upper()}\n\n")
        f.write(f"Expected spending at this pace: ${current_pace['expected_spending']:,.2f}\n")
        f.write(f"Daily budget: ${current_pace['daily_budget']:,.2f}\n")
        f.write(f"Remaining budget: ${current_pace['remaining']:,.2f}\n")
        f.write(f"Daily remaining: ${current_pace['daily_remaining']:,.2f}\n")
        f.write("\n")

    print(f"✓ Report saved to {output_file}")
    print(f"  Tokens used — input: {final.usage.input_tokens}, output: {final.usage.output_tokens}")

    # Send notification
    notifier = Notifier()
    if notifier.is_enabled():
        notifier.send(
            message=tldr_text,
            title=f"💰 Monthly Budget Report — {current_label}"
        )
    else:
        print("⚠ Pushover notification not configured (set PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY)")


if __name__ == "__main__":
    main()
