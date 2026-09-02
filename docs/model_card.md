# ReviveRoute Action Model Card

## Purpose

Rank bounded recovery actions for a failed payment using payment context, failure context and pre-decision customer history.

## Model

The training pipeline compares calibrated logistic regression and calibrated histogram gradient boosting. The final artifact is selected using the lowest Brier score on a chronological validation period. The current selected model is calibrated logistic regression.

## Data and evaluation

- 5,000 synthetic records; no real Razorpay transactions or PII
- Chronological 70/15/15 train, calibration/selection and test split
- ROC-AUC: 0.614
- PR-AUC: 0.348
- Brier score: 0.197
- Log loss: 0.575

Moderate metrics are expected and preferable to suspiciously perfect performance on a noisy recovery problem.

## Prohibited claims

- Do not claim real revenue was recovered.
- Do not call the offline policy comparison causal uplift.
- Do not present synthetic rupee totals as production outcomes.
- Do not allow the model to bypass deterministic guardrails.

## Limitations

The generator encodes assumed relationships, so the model can only learn those assumptions. The S-learner predicts conditional outcomes and cannot observe what would have happened under actions not taken. Production validation requires randomised action assignment, monitoring, recalibration and human compliance review.
