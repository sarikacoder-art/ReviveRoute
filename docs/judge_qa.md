# Judge Questions and Strong Answers

## Why is this AI rather than a rules engine?

The model estimates action-specific recovery probability from payment, failure and customer context. Rules do not predict the best intervention; they bound the model by blocking unsafe timing, excessive contact and sensitive automation. The useful design is the combination: **ML chooses among safe options; deterministic policy defines what safe means.**

## Why not build every example listed in the track?

Those are example directions. Combining checkout abandonment, subscriptions, receivables, voice and mandates in one solo-week prototype would produce shallow workflows. ReviveRoute implements one mandatory recovery loop deeply and can later add new event adapters without weakening its core controls.

## Is the ₹1,800 real recovered money?

No. It is a signed local demonstration outcome and is labelled as such. The system keeps it separate from model-based expected recovery. Production uplift would require real outcomes and randomized experimentation.

## Is the model causal?

No. It is a calibrated predictive model trained on synthetic data. Its estimates demonstrate the technical decision path, not incremental recovery caused by an action. A production version would use randomized exploration and uplift or contextual-bandit learning.

## How do you prevent harmful automation?

Opt-out, already-recovered, expiry, retry exhaustion and contact fatigue stop automation. Sensitive risk declines and high-value cases escalate. Quiet hours and degradation conditions block unsafe timing. Human-review actions are never sent through the contact executor.

## How do you prevent duplicate webhook processing?

The service stores the delivery ID, event type and exact-body hash. An identical retry returns the saved response; the same delivery ID with a changed body returns HTTP 409.

## How do you know a recovery belongs to the original failure?

Execution creates a deterministic unique reference. A paid outcome is accepted only when that reference exists and the amount matches the full failed amount.

## Can the audit chain be edited?

The local database itself is not immutable, but changing or reordering an event breaks the SHA-256 chain and the verifier reports the failing sequence. Production would anchor or store audit events in append-only infrastructure.

## What would you build next?

Razorpay test-mode Payment Link creation behind an explicit configuration switch, consent-aware messaging, randomized action assignment, outcome monitoring, production secret management and append-only audit storage.

