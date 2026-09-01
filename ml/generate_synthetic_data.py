"""
ReviveRoute Milestone 1: Synthetic Historical Recovery Dataset Generator (REVISED)

Generates 5,000 chronologically sorted records with REALISTIC payment failure
and recovery scenarios. Revised to meet realism requirements:

- 700-1,300 unique customers with realistic repeat distribution  
- Right-skewed amount distribution (median ₹1,000-₹5,000, mean <₹8,000)
- Overall recovery rate 20-40% (not 75.82%)
- NO_CONTACT recovery 5-15% (spontaneous recovery only)
- Active action recovery 15-50% (heterogeneous, context-dependent)
- Every action has ≥5% representation
- 2026 date range ending near August 2026
- Meaningful random noise and interaction effects
- Context-action relationships validated with test coverage
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import os


def generate_synthetic_recovery_dataset(
    num_records=5000,
    seed=42,
    start_date="2026-03-01",
    degradation_rate=0.05,
):
    """
    Generate synthetic recovery dataset with realistic context-action interactions.
    
    Args:
        num_records: Number of records to generate (default 5000)
        seed: Random seed for reproducibility (default 42)
        start_date: Start date for generated records
        degradation_rate: Proportion of records with degradation flag (0.05 = 5%)
    
    Returns:
        pd.DataFrame with all required columns
    """
    np.random.seed(seed)
    
    # Time range: 180 days from March 1, 2026 to August 27, 2026
    base_start = pd.to_datetime(start_date)
    
    # Generate chronologically sorted timestamps
    days_elapsed = np.linspace(0, 179, num_records)
    timestamps = pd.to_datetime([base_start + timedelta(days=float(d)) for d in days_elapsed])
    
    # Create realistic customer distribution: 700-1,300 unique customers
    num_unique_customers = np.random.randint(700, 1301)
    
    # Strategy: Ensure all customers appear at least once, then use Zipf 
    # to determine additional appearances for power-law distribution
    
    # Each customer appears at least once
    customer_ids = np.arange(1, num_unique_customers + 1)
    
    # Remaining slots to fill: num_records - num_unique_customers
    remaining_slots = num_records - num_unique_customers
    
    # Generate Zipf weights for which customers get additional appearances
    zipf_values = np.random.zipf(a=1.2, size=num_unique_customers).astype(float)
    zipf_weights = zipf_values / zipf_values.sum()
    
    # Sample additional customer appearances using Zipf weights
    additional_customers = np.random.choice(
        num_unique_customers,
        size=remaining_slots,
        p=zipf_weights,
        replace=True
    ) + 1  # Convert from 0-indexed to 1-indexed
    
    # Combine base appearances (all customers once) with additional appearances
    customer_ids = np.concatenate([customer_ids, additional_customers])
    
    # Shuffle to randomize order
    np.random.shuffle(customer_ids)
    
    # Extract temporal features
    hours = np.array([ts.hour for ts in timestamps])
    weekdays = np.array([ts.weekday() for ts in timestamps])
    
    # Generate customer history features with customer-level patterns
    customer_tenure = {}
    customer_priors = {}
    
    for cid in np.unique(customer_ids):
        # Tenure in days from account creation (1-1000 days)
        customer_tenure[cid] = np.random.exponential(scale=150) + 1
        
        # Prior successes, failures, recoveries
        customer_priors[cid] = {
            'successes': np.random.poisson(lam=2),
            'failures': np.random.poisson(lam=1.5),
            'recoveries': np.random.poisson(lam=0.3),
        }
    
    customer_tenure_arr = np.array([customer_tenure[cid] for cid in customer_ids])
    customer_successes = np.array([customer_priors[cid]['successes'] for cid in customer_ids])
    customer_failures = np.array([customer_priors[cid]['failures'] for cid in customer_ids])
    customer_recoveries = np.array([customer_priors[cid]['recoveries'] for cid in customer_ids])
    
    # Contacts in last 7 days (0-10)
    contacts_7d = np.random.poisson(lam=1.2, size=num_records)
    contacts_7d = np.minimum(contacts_7d, 10)
    
    # Failure reasons with realistic distribution
    failure_reasons = np.random.choice(
        ['insufficient_funds', 'temporary_network_issue', 'card_blocked', 'risk_declined', 'bank_limit_exceeded'],
        size=num_records,
        p=[0.35, 0.25, 0.15, 0.15, 0.10]
    )
    
    # Payment methods with realistic distribution
    payment_methods = np.random.choice(
        ['credit_card', 'debit_card', 'net_banking', 'upi', 'wallet'],
        size=num_records,
        p=[0.25, 0.30, 0.20, 0.20, 0.05]
    )
    
    # Recent method failure rate (0-0.5)
    recent_method_failure_rate = np.random.beta(a=2, b=8, size=num_records)
    
    # Degradation flag (5% of records)
    degradation_flag = np.random.choice(
        [True, False],
        size=num_records,
        p=[degradation_rate, 1 - degradation_rate]
    )
    
    # Amount in INR: right-skewed distribution
    # Target: min ≥199, median 1000-5000, mean <8000, max ≤50000
    amounts = generate_realistic_amounts(num_records)
    
    # Historical actions with overlapping probabilities for realistic distribution
    actions = assign_actions_with_overlaps(
        num_records,
        customer_ids,
        failure_reasons,
        hours,
        degradation_flag,
        contacts_7d
    )
    
    # Action delay in minutes
    action_delays = generate_action_delays(actions)
    
    # Hidden recovery probability function
    recovery_probs = compute_hidden_recovery_probability(
        failure_reasons=failure_reasons,
        payment_methods=payment_methods,
        actions=actions,
        action_delays=action_delays,
        hours=hours,
        customer_tenure=customer_tenure_arr,
        customer_recoveries=customer_recoveries,
        contacts_7d=contacts_7d,
        recent_method_failure_rate=recent_method_failure_rate,
        degradation_flag=degradation_flag,
        customer_successes=customer_successes,
        customer_failures=customer_failures,
    )
    
    # Sample recovery outcomes from hidden probabilities
    recovered = np.random.binomial(1, recovery_probs)
    
    # Recovered amount (0 if not recovered, otherwise 80-100% of original)
    recovered_amount = np.where(
        recovered == 1,
        amounts * np.random.uniform(0.80, 1.00, num_records),
        0
    )
    
    # Create DataFrame
    df = pd.DataFrame({
        'event_id': np.arange(1, num_records + 1),
        'customer_id': customer_ids.astype(int),
        'timestamp_utc': timestamps,
        'amount_inr': amounts.round(2),
        'payment_method': payment_methods,
        'failure_reason': failure_reasons,
        'hour': hours.astype(int),
        'weekday': weekdays.astype(int),
        'customer_tenure_days': customer_tenure_arr.round(1),
        'prior_successes': customer_successes.astype(int),
        'prior_failures': customer_failures.astype(int),
        'prior_recoveries': customer_recoveries.astype(int),
        'contacts_last_7_days': contacts_7d.astype(int),
        'recent_method_failure_rate': recent_method_failure_rate.round(3),
        'degradation_flag': degradation_flag.astype(int),
        'historical_action': actions,
        'action_delay_minutes': action_delays.astype(int),
        'recovered_within_72_hours': recovered.astype(int),
        'recovered_amount_inr': recovered_amount.round(2),
    })
    
    return df


def generate_realistic_amounts(num_records):
    """
    Generate right-skewed amount distribution targeting:
    - Minimum ≥ ₹199
    - Median ₹1,000-₹5,000
    - Mean < ₹8,000
    - Maximum ≤ ₹50,000
    """
    # Use lognormal with parameters tuned for right-skewed distribution
    amounts = np.random.lognormal(mean=np.log(2500), sigma=1.2, size=num_records)
    
    # Clip to valid range
    amounts = np.clip(amounts, 199, 50000)
    
    return amounts


def assign_actions_with_overlaps(
    num_records,
    customer_ids,
    failure_reasons,
    hours,
    degradation_flag,
    contacts_7d
):
    """
    Assign actions with overlapping probabilities so each action appears
    in different contexts. Ensure all actions have at least 5% representation.
    """
    actions = np.empty(num_records, dtype=object)
    
    action_list = ['NO_CONTACT', 'LINK_NOW', 'LINK_AFTER_2H', 'LINK_NEXT_MORNING', 'HUMAN_REVIEW']
    
    for i in range(num_records):
        # Base probabilities for each action - more balanced distribution
        probs = np.array([0.20, 0.20, 0.20, 0.20, 0.20], dtype=float)
        
        # Adjust based on failure reason (but keep overlap)
        if failure_reasons[i] == 'insufficient_funds':
            probs[3] += 0.05  # Slight preference for next-morning
            probs[1] -= 0.03
        elif failure_reasons[i] == 'temporary_network_issue':
            probs[2] += 0.04  # Slight preference for delayed link
            probs[1] -= 0.02
        elif failure_reasons[i] == 'risk_declined':
            probs[4] += 0.06  # Preference for human review
            probs[1] -= 0.03
        
        # Adjust based on degradation flag (subtle adjustment)
        if degradation_flag[i]:
            probs[1] -= 0.05  # Immediate links less preferred
            probs[4] += 0.05  # Human review more preferred
        
        # Adjust based on contacts in last 7 days
        if contacts_7d[i] > 3:
            probs[0] += 0.03  # Slight preference for no contact
            probs[1] -= 0.03
        
        # Adjust based on time of day (subtle)
        if hours[i] < 6 or hours[i] > 22:  # Night hours
            probs[3] += 0.03
            probs[1] -= 0.02
        
        # Normalize to ensure probabilities sum to 1
        probs = np.maximum(probs, 0.05)  # Minimum 5% for each action
        probs = probs / probs.sum()
        
        actions[i] = np.random.choice(action_list, p=probs)
    
    return actions


def generate_action_delays(actions):
    """Generate action delay in minutes based on action type."""
    delays = np.empty(len(actions), dtype=int)
    
    for i, action in enumerate(actions):
        if action == 'NO_CONTACT':
            delays[i] = 0
        elif action == 'LINK_NOW':
            delays[i] = np.random.randint(0, 30)
        elif action == 'LINK_AFTER_2H':
            delays[i] = np.random.randint(90, 150)
        elif action == 'LINK_NEXT_MORNING':
            delays[i] = np.random.randint(480, 720)  # 8-12 hours
        elif action == 'HUMAN_REVIEW':
            delays[i] = np.random.randint(30, 120)
    
    return delays


def compute_hidden_recovery_probability(
    failure_reasons,
    payment_methods,
    actions,
    action_delays,
    hours,
    customer_tenure,
    customer_recoveries,
    contacts_7d,
    recent_method_failure_rate,
    degradation_flag,
    customer_successes,
    customer_failures,
):
    """
    Hidden nonlinear function that computes recovery probability from
    failure context and action. Calibrated for 20-40% overall recovery.
    
    Contains realistic context-action interactions:
    - Delayed links work better for temporary failures
    - Next-morning links help insufficient-funds cases
    - Human review is safest for risk-blocked cases
    - Immediate links perform worse during degradation
    - Repeated contacts reduce recovery probability
    
    This probability is NOT exposed in the CSV; only outcomes are saved.
    """
    n = len(failure_reasons)
    
    # Start with LOWER base probability (calibrated to target 20-40% overall)
    base_prob = np.full(n, 0.18, dtype=float)
    
    # Context factors (conservative adjustments)
    base_prob += 0.07 * (np.log1p(customer_tenure) / np.log1p(365))
    base_prob += 0.03 * (customer_successes / (customer_successes + customer_failures + 1))
    
    # Failure reason baseline (smaller adjustments than original)
    for i in range(n):
        if failure_reasons[i] == 'temporary_network_issue':
            base_prob[i] += 0.12  # Easiest to recover
        elif failure_reasons[i] == 'insufficient_funds':
            base_prob[i] += 0.06  # Moderate difficulty
        elif failure_reasons[i] == 'card_blocked':
            base_prob[i] += 0.04
        elif failure_reasons[i] == 'bank_limit_exceeded':
            base_prob[i] += 0.05
        elif failure_reasons[i] == 'risk_declined':
            base_prob[i] -= 0.07  # Harder to recover
    
    # Payment method factors (subtle)
    for i in range(n):
        if payment_methods[i] in ['upi', 'net_banking']:
            base_prob[i] += 0.02
        elif payment_methods[i] == 'wallet':
            base_prob[i] -= 0.02
    
    # Action-context interactions (THIS IS KEY - heterogeneous effects)
    for i in range(n):
        action = actions[i]
        reason = failure_reasons[i]
        
        if action == 'NO_CONTACT':
            # Spontaneous recovery only, target 5-15%
            # Reduce significantly - baseline becomes ~0.02-0.07 range
            base_prob[i] -= 0.14
        elif action == 'LINK_NOW':
            # Works moderately well in normal conditions
            if reason == 'temporary_network_issue':
                base_prob[i] += 0.10
            elif reason == 'insufficient_funds':
                base_prob[i] += 0.04
            elif degradation_flag[i]:
                base_prob[i] -= 0.07  # Worse during degradation
            else:
                base_prob[i] += 0.07
        elif action == 'LINK_AFTER_2H':
            # Delayed links work better for many failure types
            if reason == 'temporary_network_issue':
                base_prob[i] += 0.15  # BEST option for temp issues
            elif reason == 'insufficient_funds':
                base_prob[i] += 0.07
            else:
                base_prob[i] += 0.06
        elif action == 'LINK_NEXT_MORNING':
            # Good for insufficient funds and timing issues
            if reason == 'insufficient_funds':
                base_prob[i] += 0.14  # Strong for insufficient funds
            elif reason in ['bank_limit_exceeded', 'card_blocked']:
                base_prob[i] += 0.07
            else:
                base_prob[i] += 0.04
        elif action == 'HUMAN_REVIEW':
            # Best for risk-declined but good across the board
            if reason == 'risk_declined':
                base_prob[i] += 0.17  # BEST for risk declined
            elif reason in ['card_blocked', 'insufficient_funds']:
                base_prob[i] += 0.08
            else:
                base_prob[i] += 0.06
    
    # Contact fatigue: repeated contacts reduce recovery
    contact_fatigue = np.minimum(contacts_7d / 5.0, 1.0)
    base_prob -= 0.10 * contact_fatigue
    
    # Recent method failure rate
    base_prob -= 0.07 * recent_method_failure_rate
    
    # Degradation flag
    base_prob[degradation_flag == 1] -= 0.05
    
    # Hour effects (subtle)
    for i in range(n):
        if 9 <= hours[i] <= 17:  # Business hours
            base_prob[i] += 0.02
        elif hours[i] < 6 or hours[i] > 23:
            base_prob[i] -= 0.01
    
    # Add meaningful random noise to create realistic heterogeneity
    noise = np.random.normal(loc=0, scale=0.09, size=n)
    recovery_prob = base_prob + noise
    
    # Clip to valid probability range [0.01, 0.95]
    recovery_prob = np.clip(recovery_prob, 0.01, 0.95)
    
    return recovery_prob


def print_dataset_statistics(df):
    """Print comprehensive dataset statistics."""
    print("\n" + "="*70)
    print("REVIVEROUTE SYNTHETIC RECOVERY DATASET - MILESTONE 1 (REVISED)")
    print("="*70)
    
    print(f"\nDataset Dimensions:")
    print(f"  Row Count: {len(df):,}")
    print(f"  Column Count: {len(df.columns)}")
    print(f"  Unique Customers: {df['customer_id'].nunique():,}")
    
    print(f"\nTemporal Range:")
    print(f"  Start Date: {df['timestamp_utc'].min().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  End Date: {df['timestamp_utc'].max().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Duration: {(df['timestamp_utc'].max() - df['timestamp_utc'].min()).days} days")
    
    print(f"\nRecovery Metrics:")
    recovery_count = df['recovered_within_72_hours'].sum()
    recovery_rate = recovery_count / len(df) * 100
    print(f"  Total Recovered: {int(recovery_count):,} ({recovery_rate:.2f}%)")
    print(f"  Total Not Recovered: {len(df) - int(recovery_count):,} ({100-recovery_rate:.2f}%)")
    
    total_at_risk = df['amount_inr'].sum()
    total_recovered = df['recovered_amount_inr'].sum()
    total_lost = total_at_risk - total_recovered
    print(f"  Total Revenue at Risk: ₹{total_at_risk:,.2f}")
    print(f"  Total Amount Recovered: ₹{total_recovered:,.2f}")
    print(f"  Total Amount Lost (Unrecovered): ₹{total_lost:,.2f}")
    
    print(f"\nAction Distribution:")
    action_counts = df['historical_action'].value_counts()
    for action, count in action_counts.items():
        pct = count / len(df) * 100
        print(f"  {action}: {count:,} ({pct:.2f}%)")
    
    print(f"\nRecovery Rate by Action:")
    for action in sorted(df['historical_action'].unique()):
        mask = df['historical_action'] == action
        action_recovery = df[mask]['recovered_within_72_hours'].mean() * 100
        count = mask.sum()
        print(f"  {action}: {action_recovery:.2f}% ({count:,} cases)")
    
    print(f"\nFailure Reason Distribution:")
    reason_counts = df['failure_reason'].value_counts()
    for reason, count in reason_counts.items():
        pct = count / len(df) * 100
        print(f"  {reason}: {count:,} ({pct:.2f}%)")
    
    print(f"\nPayment Method Distribution:")
    method_counts = df['payment_method'].value_counts()
    for method, count in method_counts.items():
        pct = count / len(df) * 100
        print(f"  {method}: {count:,} ({pct:.2f}%)")
    
    print(f"\nAmount Metrics:")
    print(f"  Mean: ₹{df['amount_inr'].mean():.2f}")
    print(f"  Median: ₹{df['amount_inr'].median():.2f}")
    print(f"  Min: ₹{df['amount_inr'].min():.2f}")
    print(f"  Max: ₹{df['amount_inr'].max():.2f}")
    print(f"  Std Dev: ₹{df['amount_inr'].std():.2f}")
    
    print(f"\nCustomer Metrics:")
    print(f"  Unique Customers: {df['customer_id'].nunique():,}")
    print(f"  Avg Customer Tenure: {df['customer_tenure_days'].mean():.1f} days")
    print(f"  Avg Contacts (Last 7 Days): {df['contacts_last_7_days'].mean():.2f}")
    
    print(f"\nData Quality:")
    missing_counts = df.isnull().sum()
    total_missing = missing_counts.sum()
    print(f"  Total Missing Values: {total_missing}")
    if total_missing > 0:
        for col in missing_counts[missing_counts > 0].index:
            print(f"    {col}: {missing_counts[col]}")
    else:
        print(f"  ✓ No missing values detected")
    
    print(f"\nDegradation Events: {df['degradation_flag'].sum()} ({df['degradation_flag'].mean()*100:.2f}%)")
    print("\n" + "="*70 + "\n")


def main():
    """Main execution function."""
    # Create output directory if it doesn't exist
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate dataset
    print("Generating synthetic recovery dataset (REVISED)...")
    df = generate_synthetic_recovery_dataset(num_records=5000, seed=42)
    
    # Verify chronological order
    assert df['timestamp_utc'].is_monotonic_increasing, "Dataset not chronologically sorted!"
    
    # Save to CSV
    output_path = os.path.join(output_dir, 'synthetic_recovery_history.csv')
    df.to_csv(output_path, index=False)
    print(f"✓ Dataset saved to: {output_path}")
    
    # Print statistics
    print_dataset_statistics(df)


if __name__ == '__main__':
    main()
