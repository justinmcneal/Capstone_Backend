#!/usr/bin/env python3
"""
Evaluate all AI system components and generate visual reports.

Covers:
  1. AI Chat Assistant (Groq LLM) — response times, token usage,
     language breakdown, usage trend.
  2. AI Loan Qualification Engine — eligibility score distribution,
     risk category breakdown, AI vs officer decision comparison,
     score-by-final-status analysis.

Usage:
    python scripts/evaluate_ai_systems.py

Output charts are saved to:
    documents/ml/reports/ai_evaluation/
"""
import sys
from pathlib import Path

# ── Django bootstrap ────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
# ────────────────────────────────────────────────────────────────────────────

from django.conf import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db():
    return settings.MONGODB


def _save(fig, path, label):
    fig.savefig(path, dpi=150, bbox_inches='tight')
    print(f"  📊 Saved: {path.name}  ({label})")


# ===========================================================================
# SECTION 1 — AI CHAT ASSISTANT
# ===========================================================================

def _load_chat_interactions():
    """Return all AI interaction documents from MongoDB."""
    db = _get_db()
    docs = list(db['ai_interactions'].find({}))
    return docs


def evaluate_chat(reports_dir, plt, np):
    """Generate charts for the AI Chat Assistant component."""
    print("\n── AI Chat Assistant ──────────────────────────────────────────")
    interactions = _load_chat_interactions()

    if not interactions:
        print("  ⚠️  No AI chat interactions found in the database.")
        print("     Use the chat feature first (POST /api/ai/chat/), then re-run.")
        return

    print(f"  Total interactions loaded: {len(interactions)}")

    # ── Extract fields ──────────────────────────────────────────────────────
    response_times = [
        d['response_time_ms'] for d in interactions
        if d.get('response_time_ms') is not None
    ]
    token_counts = [
        d['tokens_used'] for d in interactions
        if d.get('tokens_used') is not None
    ]
    languages = [
        str(d.get('language', 'en')).lower() for d in interactions
    ]
    # timestamps
    timestamps = []
    for d in interactions:
        ts = d.get('timestamp') or d.get('created_at')
        if ts:
            timestamps.append(ts)

    # ── Chart 1: Response Time Distribution ─────────────────────────────────
    if response_times:
        fig, ax = plt.subplots(figsize=(10, 5))
        bins = np.linspace(0, max(response_times) * 1.05, 30)
        ax.hist(response_times, bins=bins, color='#3498db', edgecolor='black',
                linewidth=0.7, alpha=0.85)
        avg = np.mean(response_times)
        median = np.median(response_times)
        ax.axvline(avg, color='#e74c3c', linestyle='--', linewidth=1.8,
                   label=f'Mean: {avg:.0f} ms')
        ax.axvline(median, color='#2ecc71', linestyle='--', linewidth=1.8,
                   label=f'Median: {median:.0f} ms')
        ax.set_xlabel('Response Time (ms)', fontsize=12)
        ax.set_ylabel('Number of Responses', fontsize=12)
        ax.set_title('AI Chat — Response Time Distribution', fontsize=14, fontweight='bold')
        ax.legend(fontsize=11)
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        _save(fig, reports_dir / 'chat_response_times.png', 'Response Times')
        plt.close(fig)
    else:
        print("  ℹ️  No response_time_ms data — skipping response time chart.")

    # ── Chart 2: Token Usage Distribution ───────────────────────────────────
    if token_counts:
        fig, ax = plt.subplots(figsize=(10, 5))
        bins = np.linspace(0, max(token_counts) * 1.05, 25)
        ax.hist(token_counts, bins=bins, color='#9b59b6', edgecolor='black',
                linewidth=0.7, alpha=0.85)
        avg_tok = np.mean(token_counts)
        ax.axvline(avg_tok, color='#e74c3c', linestyle='--', linewidth=1.8,
                   label=f'Mean: {avg_tok:.0f} tokens')
        ax.set_xlabel('Tokens Used per Response', fontsize=12)
        ax.set_ylabel('Number of Responses', fontsize=12)
        ax.set_title('AI Chat — Token Usage Distribution', fontsize=14, fontweight='bold')
        ax.legend(fontsize=11)
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        _save(fig, reports_dir / 'chat_token_usage.png', 'Token Usage')
        plt.close(fig)
    else:
        print("  ℹ️  No tokens_used data — skipping token usage chart.")

    # ── Chart 3: Language Breakdown ─────────────────────────────────────────
    lang_counts = {}
    for lang in languages:
        label = {'en': 'English', 'tl': 'Tagalog / Filipino'}.get(lang, lang.upper())
        lang_counts[label] = lang_counts.get(label, 0) + 1

    if lang_counts:
        colors = plt.cm.Set2(np.linspace(0, 1, len(lang_counts)))
        fig, ax = plt.subplots(figsize=(7, 7))
        wedges, texts, autotexts = ax.pie(
            list(lang_counts.values()),
            labels=list(lang_counts.keys()),
            autopct='%1.1f%%',
            colors=colors,
            startangle=90,
            textprops={'fontsize': 12},
            pctdistance=0.75,
        )
        for at in autotexts:
            at.set_fontweight('bold')
        ax.set_title('AI Chat — Language Breakdown', fontsize=14, fontweight='bold')
        plt.tight_layout()
        _save(fig, reports_dir / 'chat_language_breakdown.png', 'Language Breakdown')
        plt.close(fig)

    # ── Chart 4: Daily Message Volume ───────────────────────────────────────
    if timestamps:
        from collections import Counter
        day_counts = Counter()
        for ts in timestamps:
            try:
                day_counts[ts.strftime('%Y-%m-%d')] += 1
            except Exception:
                pass

        if day_counts:
            days = sorted(day_counts.keys())
            counts = [day_counts[d] for d in days]

            fig, ax = plt.subplots(figsize=(max(10, len(days) * 0.6), 5))
            ax.bar(days, counts, color='#1abc9c', edgecolor='black', linewidth=0.7)
            ax.set_xlabel('Date', fontsize=12)
            ax.set_ylabel('Messages Sent', fontsize=12)
            ax.set_title('AI Chat — Daily Message Volume', fontsize=14, fontweight='bold')
            plt.xticks(rotation=45, ha='right', fontsize=9)
            ax.grid(axis='y', alpha=0.3)
            plt.tight_layout()
            _save(fig, reports_dir / 'chat_daily_volume.png', 'Daily Volume')
            plt.close(fig)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n  Chat Summary:")
    print(f"    Total messages      : {len(interactions)}")
    if response_times:
        print(f"    Avg response time   : {np.mean(response_times):.0f} ms")
        print(f"    Median response time: {np.median(response_times):.0f} ms")
    if token_counts:
        print(f"    Avg tokens/response : {np.mean(token_counts):.0f}")
    for lang, cnt in lang_counts.items():
        pct = cnt / len(interactions) * 100
        print(f"    {lang:<24}: {cnt} ({pct:.1f}%)")


# ===========================================================================
# SECTION 2 — AI LOAN QUALIFICATION ENGINE
# ===========================================================================

def _load_loan_applications():
    """Return all loan applications from MongoDB."""
    db = _get_db()
    docs = list(db['loan_applications'].find({}))
    return docs


def evaluate_qualification(reports_dir, plt, np):
    """Generate charts for the AI Loan Qualification Engine."""
    print("\n── AI Loan Qualification Engine ───────────────────────────────")
    applications = _load_loan_applications()

    if not applications:
        print("  ⚠️  No loan applications found in the database.")
        print("     Submit at least one loan application first, then re-run.")
        return

    # Only those that went through AI qualification
    ai_apps = [a for a in applications if a.get('eligibility_score') is not None]
    print(f"  Total applications          : {len(applications)}")
    print(f"  AI-scored applications      : {len(ai_apps)}")

    if not ai_apps:
        print("  ⚠️  No AI-scored applications found.")
        return

    # ── Extract fields ──────────────────────────────────────────────────────
    scores = [float(a['eligibility_score']) for a in ai_apps]
    risk_categories = [str(a.get('risk_category', 'unknown')).lower() for a in ai_apps]
    statuses = [str(a.get('status', 'unknown')).lower() for a in ai_apps]

    ai_eligible = [
        bool(a.get('ai_recommendation', {}).get('eligible', False))
        for a in ai_apps
    ]
    requested_amounts = [float(a.get('requested_amount', 0)) for a in ai_apps]
    recommended_amounts = [
        float(a.get('recommended_amount') or 0) for a in ai_apps
    ]
    approved_amounts = [
        float(a.get('approved_amount') or 0) for a in ai_apps
    ]

    # ── Chart 1: Eligibility Score Distribution ──────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    bins = np.linspace(0, 100, 21)
    color_map = {
        'approved': '#2ecc71',
        'disbursed': '#27ae60',
        'rejected': '#e74c3c',
        'submitted': '#3498db',
        'under_review': '#9b59b6',
        'draft': '#95a5a6',
        'cancelled': '#bdc3c7',
        'unknown': '#bdc3c7',
    }
    status_groups = {}
    for score, status in zip(scores, statuses):
        status_groups.setdefault(status, []).append(score)

    bottom = np.zeros(len(bins) - 1)
    for status, slist in sorted(status_groups.items()):
        hist, _ = np.histogram(slist, bins=bins)
        ax.bar(
            (bins[:-1] + bins[1:]) / 2,
            hist,
            width=(bins[1] - bins[0]) * 0.9,
            bottom=bottom,
            label=status.replace('_', ' ').title(),
            color=color_map.get(status, '#bdc3c7'),
            edgecolor='black',
            linewidth=0.6,
            alpha=0.85,
        )
        bottom += hist

    ax.axvline(75, color='green', linestyle='--', linewidth=1.5, label='Low Risk (≥75)')
    ax.axvline(50, color='orange', linestyle='--', linewidth=1.5, label='Medium Risk (≥50)')
    ax.set_xlabel('AI Eligibility Score', fontsize=12)
    ax.set_ylabel('Number of Applications', fontsize=12)
    ax.set_title('AI Qualification — Eligibility Score Distribution', fontsize=14, fontweight='bold')
    ax.legend(fontsize=9, loc='upper left')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    _save(fig, reports_dir / 'qualification_score_distribution.png', 'Eligibility Scores')
    plt.close(fig)

    # ── Chart 2: Risk Category Breakdown ────────────────────────────────────
    risk_counts = {}
    for r in risk_categories:
        risk_counts[r] = risk_counts.get(r, 0) + 1

    if risk_counts:
        risk_colors = {'low': '#2ecc71', 'medium': '#f39c12', 'high': '#e74c3c',
                       'unknown': '#bdc3c7'}
        fig, ax = plt.subplots(figsize=(7, 7))
        labels = list(risk_counts.keys())
        sizes = list(risk_counts.values())
        colors = [risk_colors.get(l, '#95a5a6') for l in labels]
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=[l.title() for l in labels],
            autopct='%1.1f%%',
            colors=colors,
            startangle=90,
            pctdistance=0.75,
            textprops={'fontsize': 12},
        )
        for at in autotexts:
            at.set_fontweight('bold')
        ax.set_title('AI Qualification — Risk Category Breakdown', fontsize=14, fontweight='bold')
        plt.tight_layout()
        _save(fig, reports_dir / 'qualification_risk_breakdown.png', 'Risk Categories')
        plt.close(fig)

    # ── Chart 3: AI Eligible vs Final Loan Status ───────────────────────────
    # Shows how often the AI's eligibility decision matched the final outcome
    outcome_map = {
        True:  {'approved': 0, 'disbursed': 0, 'rejected': 0, 'pending': 0},
        False: {'approved': 0, 'disbursed': 0, 'rejected': 0, 'pending': 0},
    }
    pending_statuses = {'submitted', 'under_review', 'draft'}
    for eligible, status in zip(ai_eligible, statuses):
        if status in ('approved', 'disbursed'):
            outcome_map[eligible]['approved'] += 1
        elif status == 'rejected':
            outcome_map[eligible]['rejected'] += 1
        elif status in pending_statuses:
            outcome_map[eligible]['pending'] += 1

    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(3)
    outcome_labels = ['Approved / Disbursed', 'Rejected', 'Pending']
    outcome_keys = ['approved', 'rejected', 'pending']
    width = 0.35
    bars1 = ax.bar(x - width / 2,
                   [outcome_map[True][k] for k in outcome_keys],
                   width, label='AI: Eligible', color='#2ecc71',
                   edgecolor='black', linewidth=0.8)
    bars2 = ax.bar(x + width / 2,
                   [outcome_map[False][k] for k in outcome_keys],
                   width, label='AI: Not Eligible', color='#e74c3c',
                   edgecolor='black', linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(outcome_labels, fontsize=11)
    ax.set_ylabel('Number of Applications', fontsize=12)
    ax.set_title('AI Eligibility Decision vs Final Loan Status', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    for bar in list(bars1) + list(bars2):
        h = bar.get_height()
        if h > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.1,
                    str(int(h)), ha='center', va='bottom', fontsize=10, fontweight='bold')
    plt.tight_layout()
    _save(fig, reports_dir / 'qualification_ai_vs_outcome.png', 'AI vs Outcome')
    plt.close(fig)

    # ── Chart 4: Requested vs Recommended vs Approved Amount ────────────────
    # Only include applications where all three amounts exist
    amount_apps = [
        (req, rec, apr)
        for req, rec, apr in zip(requested_amounts, recommended_amounts, approved_amounts)
        if req > 0 and (rec > 0 or apr > 0)
    ]

    if amount_apps:
        req_vals = [a[0] for a in amount_apps]
        rec_vals = [a[1] for a in amount_apps]
        apr_vals = [a[2] for a in amount_apps]
        idx = range(len(amount_apps))

        fig, ax = plt.subplots(figsize=(max(10, len(amount_apps) * 0.8), 5))
        bw = 0.28
        x = np.arange(len(amount_apps))
        ax.bar(x - bw, req_vals, bw, label='Requested', color='#3498db',
               edgecolor='black', linewidth=0.6)
        ax.bar(x, rec_vals, bw, label='AI Recommended', color='#2ecc71',
               edgecolor='black', linewidth=0.6)
        ax.bar(x + bw, apr_vals, bw, label='Officer Approved', color='#e67e22',
               edgecolor='black', linewidth=0.6)
        ax.set_xlabel('Application #', fontsize=12)
        ax.set_ylabel('Amount (₱)', fontsize=12)
        ax.set_title('Requested vs AI Recommended vs Officer Approved Amount',
                     fontsize=13, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels([str(i + 1) for i in idx], fontsize=9)
        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f'₱{v:,.0f}')
        )
        ax.legend(fontsize=10)
        ax.grid(axis='y', alpha=0.3)
        plt.tight_layout()
        _save(fig, reports_dir / 'qualification_amount_comparison.png', 'Amount Comparison')
        plt.close(fig)
    else:
        print("  ℹ️  No approved amounts yet — skipping amount comparison chart.")

    # ── Chart 5: Avg Eligibility Score by Final Status ───────────────────────
    score_by_status = {}
    for score, status in zip(scores, statuses):
        score_by_status.setdefault(status, []).append(score)

    if score_by_status:
        sorted_statuses = sorted(score_by_status.keys())
        avg_scores = [np.mean(score_by_status[s]) for s in sorted_statuses]
        bar_colors = [color_map.get(s, '#bdc3c7') for s in sorted_statuses]

        fig, ax = plt.subplots(figsize=(10, 5))
        bars = ax.bar(sorted_statuses, avg_scores, color=bar_colors,
                      edgecolor='black', linewidth=0.8)
        ax.axhline(75, color='green', linestyle='--', linewidth=1.5, alpha=0.7,
                   label='Low Risk threshold (75)')
        ax.axhline(50, color='orange', linestyle='--', linewidth=1.5, alpha=0.7,
                   label='Medium Risk threshold (50)')
        for bar, avg in zip(bars, avg_scores):
            ax.text(bar.get_x() + bar.get_width() / 2, avg + 0.8,
                    f'{avg:.1f}', ha='center', va='bottom',
                    fontsize=11, fontweight='bold')
        ax.set_xlabel('Final Application Status', fontsize=12)
        ax.set_ylabel('Avg AI Eligibility Score', fontsize=12)
        ax.set_title('Average AI Score by Final Application Status',
                     fontsize=14, fontweight='bold')
        ax.set_ylim(0, 110)
        ax.legend(fontsize=10)
        ax.grid(axis='y', alpha=0.3)
        plt.xticks(rotation=15, ha='right', fontsize=10)
        plt.tight_layout()
        _save(fig, reports_dir / 'qualification_score_by_status.png', 'Score by Status')
        plt.close(fig)

    # ── Summary ─────────────────────────────────────────────────────────────
    eligible_count = sum(1 for e in ai_eligible if e)
    print(f"\n  Qualification Summary:")
    print(f"    AI-eligible        : {eligible_count}/{len(ai_apps)} "
          f"({eligible_count/len(ai_apps)*100:.1f}%)")
    print(f"    Avg eligibility score: {np.mean(scores):.1f}")
    for r, cnt in sorted(risk_counts.items()):
        print(f"    Risk '{r:<8}': {cnt} ({cnt/len(ai_apps)*100:.1f}%)")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("❌ matplotlib / numpy not installed.")
        print("   Run: pip install matplotlib numpy")
        sys.exit(1)

    reports_dir = Path(__file__).parent.parent / 'documents' / 'ml' / 'reports' / 'ai_evaluation'
    reports_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  AI SYSTEMS EVALUATION")
    print("=" * 64)
    print(f"  Output directory: {reports_dir}")

    evaluate_chat(reports_dir, plt, np)
    evaluate_qualification(reports_dir, plt, np)

    print("\n" + "=" * 64)
    print(f"  ✅ All charts saved to:")
    for f in sorted(reports_dir.iterdir()):
        print(f"     {f.name}")
    print("=" * 64)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
