"""
ReviveRoute Milestone 1: Tests for Synthetic Data Generator (REVISED)

Tests validate BOTH structural and realism requirements:

STRUCTURAL TESTS:
- Row count (5000 records)
- Required columns are present
- Action values are valid
- Amounts are non-negative
- Reproducibility with seed 42
- Chronological ordering
- No missing values

REALISM TESTS:
- 700-1,300 unique customers
- 20-40% overall recovery rate
- 5-15% NO_CONTACT recovery (spontaneous)
- Median amount between ₹1,000-₹5,000
- Mean amount below ₹8,000
- Minimum amount ≥ ₹199
- Every action has ≥5% of records
- Context-action relationships hold
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

# Add parent directories to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ml'))

from generate_synthetic_data import generate_synthetic_recovery_dataset


class TestSyntheticDataGenerator:
    """Test suite for the synthetic data generator."""
    
    @pytest.fixture
    def dataset(self):
        """Generate a dataset for testing."""
        return generate_synthetic_recovery_dataset(num_records=5000, seed=42)
    
    def test_row_count(self, dataset):
        """Test that exactly 5000 rows are generated."""
        assert len(dataset) == 5000, f"Expected 5000 rows, got {len(dataset)}"
    
    def test_required_columns_present(self, dataset):
        """Test that all required columns are present."""
        required_columns = [
            'event_id', 'customer_id', 'timestamp_utc', 'amount_inr',
            'payment_method', 'failure_reason', 'hour', 'weekday',
            'customer_tenure_days', 'prior_successes', 'prior_failures',
            'prior_recoveries', 'contacts_last_7_days', 'recent_method_failure_rate',
            'degradation_flag', 'historical_action', 'action_delay_minutes',
            'recovered_within_72_hours', 'recovered_amount_inr'
        ]
        
        missing_columns = set(required_columns) - set(dataset.columns)
        assert not missing_columns, f"Missing columns: {missing_columns}"
        
        assert len(dataset.columns) == len(required_columns), \
            f"Expected {len(required_columns)} columns, got {len(dataset.columns)}"
    
    def test_valid_actions(self, dataset):
        """Test that historical_action contains only valid actions."""
        valid_actions = {'NO_CONTACT', 'LINK_NOW', 'LINK_AFTER_2H', 'LINK_NEXT_MORNING', 'HUMAN_REVIEW'}
        actual_actions = set(dataset['historical_action'].unique())
        
        invalid_actions = actual_actions - valid_actions
        assert not invalid_actions, f"Invalid actions found: {invalid_actions}"
        assert actual_actions.issubset(valid_actions), \
            f"Actions not in valid set: {actual_actions - valid_actions}"
    
    def test_all_actions_represented(self, dataset):
        """Test that each valid action appears in the dataset."""
        valid_actions = {'NO_CONTACT', 'LINK_NOW', 'LINK_AFTER_2H', 'LINK_NEXT_MORNING', 'HUMAN_REVIEW'}
        actual_actions = set(dataset['historical_action'].unique())
        
        assert actual_actions == valid_actions, \
            f"Expected all actions {valid_actions}, got {actual_actions}"
    
    def test_non_negative_amounts(self, dataset):
        """Test that all amounts are non-negative."""
        assert (dataset['amount_inr'] >= 0).all(), \
            f"Found negative amounts: {dataset['amount_inr'].min()}"
        assert (dataset['recovered_amount_inr'] >= 0).all(), \
            f"Found negative recovered amounts: {dataset['recovered_amount_inr'].min()}"
    
    def test_amount_ranges(self, dataset):
        """Test that amounts fall within expected ranges."""
        assert dataset['amount_inr'].min() >= 100, \
            f"Minimum amount {dataset['amount_inr'].min()} is less than 100"
        assert dataset['amount_inr'].max() <= 50000, \
            f"Maximum amount {dataset['amount_inr'].max()} exceeds 50000"
    
    def test_recovered_amount_not_exceeds_original(self, dataset):
        """Test that recovered amount does not exceed original amount."""
        exceeds = (dataset['recovered_amount_inr'] > dataset['amount_inr']).sum()
        assert exceeds == 0, \
            f"Found {exceeds} rows where recovered_amount_inr > amount_inr"
    
    def test_reproducibility(self):
        """Test that same seed produces identical results."""
        df1 = generate_synthetic_recovery_dataset(num_records=5000, seed=42)
        df2 = generate_synthetic_recovery_dataset(num_records=5000, seed=42)
        
        # Compare DataFrames (allowing for float precision)
        pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))
    
    def test_chronological_order(self, dataset):
        """Test that records are chronologically sorted."""
        assert dataset['timestamp_utc'].is_monotonic_increasing, \
            "Dataset is not chronologically sorted"
    
    def test_no_missing_values(self, dataset):
        """Test that there are no missing values in the dataset."""
        missing_counts = dataset.isnull().sum()
        total_missing = missing_counts.sum()
        
        assert total_missing == 0, \
            f"Found {total_missing} missing values:\n{missing_counts[missing_counts > 0]}"
    
    def test_event_id_uniqueness(self, dataset):
        """Test that event_ids are unique and sequential."""
        assert dataset['event_id'].is_unique, "event_id contains duplicates"
        assert list(dataset['event_id']) == list(range(1, 5001)), \
            "event_ids are not sequential from 1 to 5000"
    
    def test_valid_temporal_features(self, dataset):
        """Test that hour and weekday are within valid ranges."""
        assert (dataset['hour'] >= 0).all() and (dataset['hour'] <= 23).all(), \
            f"Invalid hours found: min={dataset['hour'].min()}, max={dataset['hour'].max()}"
        
        assert (dataset['weekday'] >= 0).all() and (dataset['weekday'] <= 6).all(), \
            f"Invalid weekdays found: min={dataset['weekday'].min()}, max={dataset['weekday'].max()}"
    
    def test_valid_customer_metrics(self, dataset):
        """Test that customer metrics are non-negative."""
        assert (dataset['prior_successes'] >= 0).all(), "Found negative prior_successes"
        assert (dataset['prior_failures'] >= 0).all(), "Found negative prior_failures"
        assert (dataset['prior_recoveries'] >= 0).all(), "Found negative prior_recoveries"
        assert (dataset['contacts_last_7_days'] >= 0).all(), "Found negative contacts_last_7_days"
        assert (dataset['customer_tenure_days'] > 0).all(), "Found non-positive customer_tenure_days"
    
    def test_valid_failure_reasons(self, dataset):
        """Test that failure_reason contains only valid values."""
        valid_reasons = {
            'insufficient_funds', 'temporary_network_issue', 'card_blocked',
            'risk_declined', 'bank_limit_exceeded'
        }
        actual_reasons = set(dataset['failure_reason'].unique())
        
        invalid_reasons = actual_reasons - valid_reasons
        assert not invalid_reasons, f"Invalid failure reasons: {invalid_reasons}"
    
    def test_valid_payment_methods(self, dataset):
        """Test that payment_method contains only valid values."""
        valid_methods = {'credit_card', 'debit_card', 'net_banking', 'upi', 'wallet'}
        actual_methods = set(dataset['payment_method'].unique())
        
        invalid_methods = actual_methods - valid_methods
        assert not invalid_methods, f"Invalid payment methods: {invalid_methods}"
    
    def test_valid_recovery_flags(self, dataset):
        """Test that recovered_within_72_hours contains only 0 or 1."""
        assert set(dataset['recovered_within_72_hours'].unique()).issubset({0, 1}), \
            "recovered_within_72_hours contains values other than 0 or 1"
    
    def test_valid_degradation_flags(self, dataset):
        """Test that degradation_flag contains only 0 or 1."""
        assert set(dataset['degradation_flag'].unique()).issubset({0, 1}), \
            "degradation_flag contains values other than 0 or 1"
    
    def test_action_delay_minutes_range(self, dataset):
        """Test that action_delay_minutes are non-negative."""
        assert (dataset['action_delay_minutes'] >= 0).all(), \
            f"Found negative action delays: {dataset['action_delay_minutes'].min()}"
    
    def test_recovery_probability_not_exposed(self, dataset):
        """Test that hidden recovery probability is not in the CSV."""
        recovery_prob_cols = [col for col in dataset.columns if 'probability' in col.lower()]
        assert not recovery_prob_cols, \
            f"Recovery probability columns found in output: {recovery_prob_cols}"
    
    def test_recovery_consistency(self, dataset):
        """Test that recovered_amount is 0 when not recovered, non-zero when recovered."""
        not_recovered = dataset[dataset['recovered_within_72_hours'] == 0]
        recovered = dataset[dataset['recovered_within_72_hours'] == 1]
        
        assert (not_recovered['recovered_amount_inr'] == 0).all(), \
            "Found non-zero recovered_amount_inr for unrecovered transactions"
        
        assert (recovered['recovered_amount_inr'] > 0).all(), \
            "Found zero recovered_amount_inr for recovered transactions"
    
    def test_recent_method_failure_rate_range(self, dataset):
        """Test that recent_method_failure_rate is between 0 and 1."""
        assert (dataset['recent_method_failure_rate'] >= 0).all(), \
            f"Found negative rates: {dataset['recent_method_failure_rate'].min()}"
        assert (dataset['recent_method_failure_rate'] <= 1).all(), \
            f"Found rates > 1: {dataset['recent_method_failure_rate'].max()}"
    
    def test_action_distribution_reasonable(self, dataset):
        """Test that action distribution is reasonable (each action appears)."""
        action_counts = dataset['historical_action'].value_counts()
        
        # Each action should appear at least 10 times (more than 0.2% of 5000)
        for action, count in action_counts.items():
            assert count >= 10, f"Action '{action}' appears only {count} times"
    
    def test_recovery_rate_reasonable(self, dataset):
        """Test that overall recovery rate is realistic (20-40%)."""
        recovery_rate = dataset['recovered_within_72_hours'].mean()
        
        # Should be between 20% and 40% (realistic for diverse failure types and actions)
        assert 0.20 <= recovery_rate <= 0.40, \
            f"Recovery rate {recovery_rate:.2%} outside expected range [20%-40%]"
    
    # ===== REALISM TESTS =====
    
    def test_unique_customers_realistic(self, dataset):
        """Test that unique customer count is realistic (700-1,300)."""
        unique_customers = dataset['customer_id'].nunique()
        assert 700 <= unique_customers <= 1300, \
            f"Unique customers {unique_customers} outside range [700-1300]"
    
    def test_no_contact_recovery_rate(self, dataset):
        """Test that NO_CONTACT recovery rate is spontaneous (5-15%)."""
        no_contact_mask = dataset['historical_action'] == 'NO_CONTACT'
        no_contact_recovery = dataset[no_contact_mask]['recovered_within_72_hours'].mean()
        
        assert 0.05 <= no_contact_recovery <= 0.15, \
            f"NO_CONTACT recovery {no_contact_recovery:.2%} outside expected range [5%-15%]"
    
    def test_amount_median_realistic(self, dataset):
        """Test that amount median is between ₹1,000-₹5,000."""
        median_amount = dataset['amount_inr'].median()
        assert 1000 <= median_amount <= 5000, \
            f"Median amount ₹{median_amount:.2f} outside range [₹1,000-₹5,000]"
    
    def test_amount_mean_realistic(self, dataset):
        """Test that amount mean is below ₹8,000."""
        mean_amount = dataset['amount_inr'].mean()
        assert mean_amount < 8000, \
            f"Mean amount ₹{mean_amount:.2f} exceeds ₹8,000 limit"
    
    def test_amount_minimum_realistic(self, dataset):
        """Test that minimum amount is at least ₹199."""
        min_amount = dataset['amount_inr'].min()
        assert min_amount >= 199, \
            f"Minimum amount ₹{min_amount:.2f} is below ₹199"
    
    def test_action_minimum_representation(self, dataset):
        """Test that every action has at least 5% representation."""
        action_counts = dataset['historical_action'].value_counts()
        total_records = len(dataset)
        min_threshold = total_records * 0.05
        
        for action, count in action_counts.items():
            pct = count / total_records * 100
            assert count >= min_threshold, \
                f"Action '{action}' has only {pct:.2f}% of records (need ≥5%)"
    
    def test_delayed_link_better_than_immediate_for_temp_issues(self, dataset):
        """Test that LINK_AFTER_2H outperforms LINK_NOW for temporary_network_issue."""
        # Subset to temporary network issues only
        temp_mask = dataset['failure_reason'] == 'temporary_network_issue'
        
        # Get recovery rates for each action
        link_now_mask = (temp_mask) & (dataset['historical_action'] == 'LINK_NOW')
        link_2h_mask = (temp_mask) & (dataset['historical_action'] == 'LINK_AFTER_2H')
        
        if link_now_mask.sum() > 10 and link_2h_mask.sum() > 10:  # Ensure sufficient samples
            link_now_recovery = dataset[link_now_mask]['recovered_within_72_hours'].mean()
            link_2h_recovery = dataset[link_2h_mask]['recovered_within_72_hours'].mean()
            
            # LINK_AFTER_2H should have higher recovery than LINK_NOW
            assert link_2h_recovery > link_now_recovery, \
                f"LINK_AFTER_2H ({link_2h_recovery:.2%}) not better than LINK_NOW ({link_now_recovery:.2%}) for temp issues"
    
    def test_next_morning_good_for_insufficient_funds(self, dataset):
        """Test that LINK_NEXT_MORNING is effective for insufficient_funds."""
        # Subset to insufficient funds only
        insuff_mask = dataset['failure_reason'] == 'insufficient_funds'
        
        next_morning_mask = (insuff_mask) & (dataset['historical_action'] == 'LINK_NEXT_MORNING')
        
        if next_morning_mask.sum() > 10:  # Ensure sufficient samples
            next_morning_recovery = dataset[next_morning_mask]['recovered_within_72_hours'].mean()
            
            # LINK_NEXT_MORNING should have meaningful recovery rate (>15%)
            assert next_morning_recovery > 0.15, \
                f"LINK_NEXT_MORNING recovery for insufficient_funds ({next_morning_recovery:.2%}) too low"
    
    def test_human_review_best_for_risk_declined(self, dataset):
        """Test that HUMAN_REVIEW is effective for risk_declined cases."""
        # Subset to risk_declined only
        risk_mask = dataset['failure_reason'] == 'risk_declined'
        
        human_review_mask = (risk_mask) & (dataset['historical_action'] == 'HUMAN_REVIEW')
        
        if human_review_mask.sum() > 10:  # Ensure sufficient samples
            human_recovery = dataset[human_review_mask]['recovered_within_72_hours'].mean()
            
            # HUMAN_REVIEW should have meaningful recovery rate (>20%)
            assert human_recovery > 0.20, \
                f"HUMAN_REVIEW recovery for risk_declined ({human_recovery:.2%}) too low"
    
    def test_link_now_worse_during_degradation(self, dataset):
        """Test that LINK_NOW performs worse during degradation."""
        # Subset to LINK_NOW action
        link_now_mask = dataset['historical_action'] == 'LINK_NOW'
        
        no_degradation_mask = link_now_mask & (dataset['degradation_flag'] == 0)
        degradation_mask = link_now_mask & (dataset['degradation_flag'] == 1)
        
        if no_degradation_mask.sum() > 10 and degradation_mask.sum() > 5:
            recovery_no_degrad = dataset[no_degradation_mask]['recovered_within_72_hours'].mean()
            recovery_degrad = dataset[degradation_mask]['recovered_within_72_hours'].mean()
            
            # Recovery should be worse during degradation
            assert recovery_degrad < recovery_no_degrad, \
                f"LINK_NOW performs same/better during degradation ({recovery_degrad:.2%}) vs normal ({recovery_no_degrad:.2%})"
    
    def test_contact_fatigue_reduces_recovery(self, dataset):
        """Test that high contact counts reduce recovery probability."""
        low_contact_mask = dataset['contacts_last_7_days'] <= 1
        high_contact_mask = dataset['contacts_last_7_days'] >= 5
        
        if low_contact_mask.sum() > 50 and high_contact_mask.sum() > 50:
            recovery_low_contact = dataset[low_contact_mask]['recovered_within_72_hours'].mean()
            recovery_high_contact = dataset[high_contact_mask]['recovered_within_72_hours'].mean()
            
            # Recovery should be lower with high contact
            assert recovery_high_contact < recovery_low_contact, \
                f"High contacts recovery ({recovery_high_contact:.2%}) not lower than low contacts ({recovery_low_contact:.2%})"
    
    def test_date_range_2026(self, dataset):
        """Test that data is from 2026."""
        min_date = dataset['timestamp_utc'].min()
        max_date = dataset['timestamp_utc'].max()
        
        assert min_date.year == 2026, f"Min date year {min_date.year} should be 2026"
        assert max_date.year == 2026, f"Max date year {max_date.year} should be 2026"
        
        # Should end near August 2026
        assert 7 <= max_date.month <= 9, f"End date month {max_date.month} should be near August"
    
    def test_dataframe_dtypes(self, dataset):
        """Test that columns have appropriate data types."""
        expected_dtypes = {
            'event_id': np.integer,
            'customer_id': np.integer,
            'amount_inr': (np.floating, np.integer),
            'hour': np.integer,
            'weekday': np.integer,
            'customer_tenure_days': (np.floating, np.integer),
            'prior_successes': np.integer,
            'prior_failures': np.integer,
            'prior_recoveries': np.integer,
            'contacts_last_7_days': np.integer,
            'recent_method_failure_rate': (np.floating, np.integer),
            'degradation_flag': np.integer,
            'action_delay_minutes': np.integer,
            'recovered_within_72_hours': np.integer,
            'recovered_amount_inr': (np.floating, np.integer),
        }
        
        for col, expected_type in expected_dtypes.items():
            actual_type = dataset[col].dtype
            if isinstance(expected_type, tuple):
                assert any(np.issubdtype(actual_type, t) for t in expected_type), \
                    f"Column {col} has type {actual_type}, expected one of {expected_type}"
            else:
                assert np.issubdtype(actual_type, expected_type), \
                    f"Column {col} has type {actual_type}, expected {expected_type}"


class TestDataPersistence:
    """Test that generated data can be properly saved and loaded."""
    
    def test_csv_generation(self, tmp_path):
        """Test that CSV can be generated and read back."""
        # Generate dataset
        df = generate_synthetic_recovery_dataset(num_records=5000, seed=42)
        
        # Save to temp CSV
        csv_path = tmp_path / "test_synthetic_data.csv"
        df.to_csv(csv_path, index=False)
        
        # Read back
        df_loaded = pd.read_csv(csv_path)
        
        # Check row count
        assert len(df_loaded) == 5000, \
            f"Loaded dataset has {len(df_loaded)} rows, expected 5000"
        
        # Check column count
        assert len(df_loaded.columns) == 19, \
            f"Loaded dataset has {len(df_loaded.columns)} columns, expected 19"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
