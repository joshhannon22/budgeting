#!/usr/bin/env python3
"""
Weekly spending report: compares the last two complete weeks,
builds a structured summary, then uses Claude to generate a
human-readable breakdown with week-over-week analysis.
"""

import os
from pathlib import Path

import anthropic
import pandas as pd

from notifications import Notifier, build_tldr_prompt


# ─────────────────────────────────────────────
# Data extraction
# ─────────────────────────────────────────────

def get_last_two_complete_weeks(df: pd.DataFrame):
    """
    Return (week1_df, week2_df) for the two weeks BEFORE the current week.
    Also return start and end dates for each week.
    """
    df = df.copy()
    df["Week_Start"] = df["Date"] - pd.to_timedelta(df["Date"].dt.dayofweek, unit="d")
    df["Week_Start"] = df["Week_Start"].dt.normalize()

    week_starts = sorted(df["Week_Start"].unique(), reverse=True)

    if len(week_starts) < 3:
        raise ValueError("Not enough weekly data — need at least three distinct weeks.")

    # Skip the current week (week_starts[0]) and get the two weeks before it
    week1_start = week_starts[1]  # Most recent of the two weeks before current
    week2_start = week_starts[2]  # Second most recent of the two weeks before current

    week1_df = df[df["Week_Start"] == week1_start].copy()
    week2_df = df[df["Week_Start"] == week2_start].copy()

    # Calculate end dates (Sunday of each week)
    week1_end = pd.Timestamp(week1_start) + pd.Timedelta(days=6)
    week2_end = pd.Timestamp(week2_start) + pd.Timedelta(days=6)

    return week1_df, week2_df, week1_start, week1_end, week2_start, week2_end


def build_week_summary(week_df: pd.DataFrame, category_col: str,
                       categories_with_negatives: set) -> dict:
    """
    Build a dict: { category: {positive, negative, net} }
    plus overall totals.
    """
    summary = {}

    for cat, group in week_df.groupby(category_col):
        positive = group[group["Amount"] > 0]["Amount"].sum()
        negative = group[group["Amount"] < 0]["Amount"].sum()
        net = positive + negative

        if cat in categories_with_negatives:
            summary[cat] = {
                "positive": round(positive, 2),
                "negative": round(negative, 2),
                "net":      round(net, 2),
            }
        else:
            summary[cat] = {
                "positive": round(positive, 2),
                "negative": 0.0,
                "net":      round(net, 2),
            }

    total_positive = week_df[week_df["Amount"] > 0]["Amount"].sum()
    total_negative = week_df[week_df["Amount"] < 0]["Amount"].sum()
    summary["__totals__"] = {
        "total_positive": round(total_positive, 2),
        "total_negative": round(total_negative, 2),
        "net_total":      round(total_positive + total_negative, 2),
    }

    return summary


def build_differences(current: dict, previous: dict) -> dict:
    """
    For each category present in either week, compute the change in
    positive spend, negative spend, and net.
    """
    all_cats = set(current.keys()) | set(previous.keys())
    all_cats.discard("__totals__")

    diffs = {}
    for cat in all_cats:
        c = current.get(cat,  {"positive": 0, "negative": 0, "net": 0})
        p = previous.get(cat, {"positive": 0, "negative": 0, "net": 0})
        diffs[cat] = {
            "positive_change": round(c["positive"] - p["positive"], 2),
            "negative_change": round(c["negative"] - p["negative"], 2),
            "net_change":      round(c["net"]      - p["net"],      2),
        }

    ct = current.get("__totals__",  {"total_positive": 0, "total_negative": 0, "net_total": 0})
    pt = previous.get("__totals__", {"total_positive": 0, "total_negative": 0, "net_total": 0})
    diffs["__totals__"] = {
        "total_positive_change": round(ct["total_positive"] - pt["total_positive"], 2),
        "total_negative_change": round(ct["total_negative"] - pt["total_negative"], 2),
        "net_total_change":      round(ct["net_total"]      - pt["net_total"],      2),
    }

    return diffs


# ─────────────────────────────────────────────
# Claude prompt construction
# ─────────────────────────────────────────────

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


def format_diff_block(diffs: dict) -> str:
    lines = ["=== WEEK-OVER-WEEK DIFFERENCES (current vs previous) ==="]
    totals = diffs.pop("__totals__", {})

    for cat, vals in sorted(diffs.items()):
        net_change = vals["net_change"]
        direction  = "up" if net_change > 0 else ("down" if net_change < 0 else "unchanged")
        pos_change = vals["positive_change"]
        neg_change = vals["negative_change"]

        parts = [f"  {cat}: net {direction} ${abs(net_change):,.2f}"]
        if pos_change != 0:
            parts.append(f"spending change ${pos_change:+,.2f}")
        if neg_change != 0:
            parts.append(f"credits change ${neg_change:+,.2f}")
        lines.append(" | ".join(parts))

    lines.append("")
    lines.append(
        f"  TOTAL SPENDING CHANGE:  ${totals.get('total_positive_change', 0):+,.2f}"
    )
    lines.append(
        f"  TOTAL CREDITS CHANGE:   ${totals.get('total_negative_change', 0):+,.2f}"
    )
    lines.append(
        f"  NET TOTAL CHANGE:       ${totals.get('net_total_change', 0):+,.2f}"
    )
    diffs["__totals__"] = totals
    return "\n".join(lines)


def build_prompt(week1_label: str, week2_label: str,
                 week1_summary: dict, week2_summary: dict,
                 diffs: dict) -> str:
    week1_block = format_category_block(f"WEEK 1  ({week1_label})",  week1_summary)
    week2_block = format_category_block(f"WEEK 2 ({week2_label})", week2_summary)
    diff_block  = format_diff_block(diffs)

    return f"""You are a personal finance assistant. Below is a structured summary of two weeks of credit card spending. Write a clear, human-friendly breakdown of my finances.

Your summary should:
1. Open with a short high-level overview for week 1 (total spent, any notable credits/payments).
2. Go through each spending category for week 1 — how much was spent, and any credits/refunds.
3. Highlight the week-over-week differences: which categories went up or down significantly, and by how much.
4. Conclude with a brief observation or tip based on the patterns you see.

Use plain language, dollar amounts, and be concise. Do not repeat every single number — focus on what's notable or actionable.

---

{week1_block}

{week2_block}

{diff_block}
"""


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    csv_file = Path(__file__).parent / "transactions" / "combined_transactions.csv"

    if not csv_file.exists():
        print(f"Error: {csv_file} not found. Run combine.py first.")
        return

    print("Reading transactions...")
    df = pd.read_csv(csv_file)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Amount"])

    category_col = "Unified_Category" if "Unified_Category" in df.columns else "Category"
    categories_with_negatives = set(df[df["Amount"] < 0][category_col].unique())

    print(f"Category column: {category_col}")
    print(f"Categories with negative amounts: {len(categories_with_negatives)}\n")

    # ── Extract the two weeks before the current week ──
    week1_df, week2_df, week1_start, week1_end, week2_start, week2_end = get_last_two_complete_weeks(df)

    week1_label = pd.Timestamp(week1_start).strftime("%Y-%m-%d")
    week2_label = pd.Timestamp(week2_start).strftime("%Y-%m-%d")

    week1_start_str = pd.Timestamp(week1_start).strftime("%A, %B %d, %Y")
    week1_end_str = pd.Timestamp(week1_end).strftime("%A, %B %d, %Y")
    week2_start_str = pd.Timestamp(week2_start).strftime("%A, %B %d, %Y")
    week2_end_str = pd.Timestamp(week2_end).strftime("%A, %B %d, %Y")

    print(f"Week 1:  {week1_label}  ({len(week1_df)} transactions)")
    print(f"  {week1_start_str} to {week1_end_str}")
    print(f"Week 2:  {week2_label}  ({len(week2_df)} transactions)")
    print(f"  {week2_start_str} to {week2_end_str}\n")

    # ── Build summaries ──
    week1_summary = build_week_summary(week1_df,  category_col, categories_with_negatives)
    week2_summary = build_week_summary(week2_df, category_col, categories_with_negatives)
    diffs         = build_differences(
        # pass copies so __totals__ isn't mutated by format helpers
        {**week1_summary},
        {**week2_summary},
    )

    # ── Print structured data ──
    print("=" * 60)
    print(format_category_block(f"WEEK 1 ({week1_label})",  {**week1_summary}))
    print()
    print(format_category_block(f"WEEK 2 ({week2_label})", {**week2_summary}))
    print()
    print(format_diff_block({**diffs}))
    print()

    # ── Call Claude ──
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        return

    prompt = build_prompt(week1_label, week2_label,
                          {**week1_summary}, {**week2_summary}, {**diffs})

    print("=" * 60)
    print("Generating AI summary with Claude...")
    print("=" * 60)
    print()

    client   = anthropic.Anthropic(api_key=api_key)
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

    tldr_prompt = build_tldr_prompt("weekly", format_category_block(f"WEEK 1 ({week1_label})", {**week1_summary}))

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

    # ── Create weekly_exports directory ──
    export_dir = Path(__file__).parent / "weekly_exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # ── Export CSV files ──
    week1_csv = export_dir / f"weekly_data_{week1_label}.csv"
    week2_csv = export_dir / f"weekly_data_{week2_label}.csv"
    week1_df.to_csv(week1_csv, index=False)
    week2_df.to_csv(week2_csv, index=False)
    print(f"✓ Week 1 data exported to {week1_csv}")
    print(f"✓ Week 2 data exported to {week2_csv}")

    # ── Save report to file ──
    output_file = export_dir / f"weekly_report_{week1_label}.txt"

    with open(output_file, "w") as f:
        f.write(f"Weekly Spending Report\n")
        f.write(f"Week 1: {week1_label} ({week1_start_str} to {week1_end_str})\n")
        f.write(f"Week 2: {week2_label} ({week2_start_str} to {week2_end_str})\n")
        f.write("=" * 60 + "\n\n")
        f.write(full_summary_text)
        f.write("\n\n" + "=" * 60 + "\n")
        f.write("RAW DATA\n")
        f.write("=" * 60 + "\n\n")
        f.write(format_category_block(f"WEEK 1 ({week1_label})",   {**week1_summary}))
        f.write("\n\n")
        f.write(format_category_block(f"WEEK 2 ({week2_label})", {**week2_summary}))
        f.write("\n\n")
        f.write(format_diff_block({**diffs}))
        f.write("\n")

    print(f"✓ Report saved to {output_file}")
    print(f"  Tokens used — input: {final.usage.input_tokens}, output: {final.usage.output_tokens}")

    # Send notification
    notifier = Notifier()
    if notifier.is_enabled():
        notifier.send(
            message=tldr_text,
            title=f"📊 Weekly Spending Report — {week1_label}"
        )
    else:
        print("⚠ Pushover notification not configured (set PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY)")


if __name__ == "__main__":
    main()
