# ReviveRoute: AI Revenue-Recovery Agent for Failed Razorpay Payments

An intelligent revenue-recovery system designed to automatically detect and recover failed Razorpay payments by intelligently routing customer re-engagement actions based on failure context and historical patterns.

---

## Milestone 1: Synthetic Historical Recovery Dataset Generator

**Status:** ✅ Complete

### Overview

Milestone 1 implements a reproducible synthetic dataset generator that simulates 5,000 historical payment failures and recovery attempts. This dataset serves as the foundation for developing and testing the recovery recommendation system in future milestones.

### Dataset Characteristics

**Important:** This dataset is **entirely synthetic and generated programmatically**. It does not represent real Razorpay transactions or actual merchant data. The statistics and recovery patterns observed in this dataset are artifacts of the synthetic generation process and **do not prove or demonstrate real merchant uplift** or effectiveness in production systems.

#### Record Count
- **5,000 chronologically sorted records** spanning 6 months (2024-01-01 to 2024-06-28)
- Records generated with seed 42 for reproducibility

#### Features Generated

**Transaction Context:**
- `event_id`: Unique event identifier (1-5000)
- `customer_id`: Customer identifier with realistic power-law distribution (750 unique customers)
- `timestamp_utc`: UTC timestamp, chronologically sorted
- `amount_inr`: Payment amount in INR (₹100-₹50,000)
- `payment_method`: Payment method (credit_card, debit_card, net_banking, upi, wallet)

**Failure Context:**
- `failure_reason`: Reason for initial failure (insufficient_funds, temporary_network_issue, card_blocked, risk_declined, bank_limit_exceeded)
- `degradation_flag`: Platform degradation event indicator (5.16% of records)

**Temporal Features:**
- `hour`: Hour of day (0-23)
- `weekday`: Day of week (0-6, Monday-Sunday)

**Customer History:**
- `customer_tenure_days`: Days since account creation (median: 262.5 days)
- `prior_successes`: Count of prior successful transactions
- `prior_failures`: Count of prior failed transactions
- `prior_recoveries`: Count of prior successful recoveries
- `contacts_last_7_days`: Re-engagement contact attempts in last 7 days (0-10)
- `recent_method_failure_rate`: Recent failure rate for customer's payment method (0.0-1.0)

**Recovery Action & Outcome:**
- `historical_action`: Recovery action taken (NO_CONTACT, LINK_NOW, LINK_AFTER_2H, LINK_NEXT_MORNING, HUMAN_REVIEW)
- `action_delay_minutes`: Delay before taking action (0-720 minutes)
- `recovered_within_72_hours`: Binary outcome (1=recovered, 0=not recovered)
- `recovered_amount_inr`: Amount recovered if successful (0 if not recovered)

#### Dataset Statistics

```
Row Count: 5,000
Column Count: 19
Recovery Rate: 75.82% (3,791 recovered, 1,209 not recovered)

Action Distribution:
  LINK_NEXT_MORNING:  24.44% (1,222 cases)
  LINK_NOW:           22.52% (1,126 cases)
  LINK_AFTER_2H:      22.06% (1,103 cases)
  HUMAN_REVIEW:       15.84% (792 cases)
  NO_CONTACT:         15.14% (757 cases)

Recovery by Action:
  HUMAN_REVIEW:       83.21%
  LINK_NEXT_MORNING:  83.14%
  LINK_AFTER_2H:      83.32%
  LINK_NOW:           79.66%
  NO_CONTACT:         39.63%

Failure Reason Distribution:
  insufficient_funds:           33.96%
  temporary_network_issue:      24.54%
  card_blocked:                 15.72%
  risk_declined:                15.04%
  bank_limit_exceeded:          10.74%

Data Quality:
  Missing Values: 0
  Duplicate event_ids: 0
  Chronological Order: ✓
```

### Context-Action Interactions

The synthetic data encodes realistic interactions between failure contexts and recovery actions:

1. **Delayed Links for Temporary Failures:** Delayed recovery attempts (2-hour and next-morning links) show higher recovery rates for temporary network issues than immediate retry attempts.

2. **Next-Morning Links for Insufficient Funds:** Customers experiencing insufficient funds benefit from next-morning re-engagement, likely reflecting behavioral changes (salary deposits, etc.).

3. **Human Review for High-Risk Cases:** Human review is assigned more frequently and shows higher effectiveness for risk-blocked cases that require manual evaluation.

4. **Degradation Impact:** During platform degradation events, immediate links show reduced effectiveness, while human review is preferred.

5. **Contact Fatigue:** Repeated contacts in the last 7 days reduce recovery probability, reflecting diminishing returns from excessive customer outreach.

### Implementation Details

**Generator:** [ml/generate_synthetic_data.py](ml/generate_synthetic_data.py)
- Implements hidden recovery probability function with context-action interactions
- Uses NumPy/pandas for efficient data generation
- Applies realistic probability adjustments based on failure context, temporal factors, and customer history
- Output: [data/synthetic_recovery_history.csv](data/synthetic_recovery_history.csv)

**Tests:** [tests/test_data_generator.py](tests/test_data_generator.py)
- 25 automated tests validating:
  - Row count (5,000 records)
  - Required columns presence
  - Valid actions, failure reasons, payment methods
  - Non-negative amounts and reasonable ranges
  - Reproducibility with seed 42
  - Chronological ordering
  - Zero missing values
  - Recovery outcome consistency
  - Data type correctness

### Test Results

```
============================= 25 passed in 4.85s ==============================

✓ Row count validation
✓ Required columns present
✓ Valid action values
✓ All actions represented
✓ Non-negative amounts
✓ Amount ranges (₹100-₹50,000)
✓ Recovered amount ≤ original amount
✓ Reproducibility with seed 42
✓ Chronological ordering
✓ No missing values
✓ Unique sequential event_ids
✓ Valid temporal features
✓ Valid customer metrics
✓ Valid failure reasons
✓ Valid payment methods
✓ Valid recovery flags
✓ Valid degradation flags
✓ Valid action delays
✓ Hidden probability not exposed
✓ Recovery outcome consistency
✓ Recent method failure rate in [0,1]
✓ Action distribution reasonable
✓ Recovery rate reasonable [20%-80%]
✓ Correct data types
✓ CSV persistence
```

### Running the Generator

```bash
python ml/generate_synthetic_data.py
```

Output: `data/synthetic_recovery_history.csv` with comprehensive dataset statistics printed to stdout.

### Running Tests

```bash
pytest tests/test_data_generator.py -v
```

### Dependencies

- NumPy 1.26.4
- Pandas 2.2.1
- Pytest 9.1.1

### Files Modified/Created

- ✅ [ml/generate_synthetic_data.py](ml/generate_synthetic_data.py) - Synthetic data generator
- ✅ [tests/test_data_generator.py](tests/test_data_generator.py) - Test suite
- ✅ [data/synthetic_recovery_history.csv](data/synthetic_recovery_history.csv) - Generated dataset
- ✅ [requirements.txt](requirements.txt) - Updated with dependencies

### Future Milestones

- **Milestone 2:** Data exploration and feature engineering
- **Milestone 3:** ML model development (recovery prediction)
- **Milestone 4:** Recovery recommendation system
- **Milestone 5:** API and dashboard integration

---

## Important Disclaimer

This dataset is **entirely synthetic**. All recovery rates, action effectiveness metrics, and correlations observed are artifacts of the synthetic generation process and do not reflect real-world payment recovery dynamics. When real transaction data becomes available, model behavior and predictions will need to be recalibrated. This synthetic dataset is intended for system development and testing only.

