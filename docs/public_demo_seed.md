# Idempotent public-demo seeding

The deployed `app.main:app` enables `REVIVEROUTE_AUTO_SEED` by default. After database initialization and before the autonomous worker starts, an empty database receives:

- 40 synthetic failed-payment cases;
- multiple complete signed simulated recoveries covering different failure reasons and the `LINK_NOW`, `LINK_AFTER_2H`, and `LINK_NEXT_MORNING` options;
- six fictional promise-to-pay records covering active, due, broken, kept and late-paid states.

This guarantees that a judge sees meaningful batch metrics immediately after a Render filesystem reset. The seed checks recovery and promise tables independently and does not duplicate existing data on restart.

An older ReviveRoute fictional demo containing at most 30 demo-only cases and one observed outcome is upgraded once with the varied recovered portfolio. Databases containing merchant or other non-demo event IDs are never upgraded by this compatibility path.

Set `REVIVEROUTE_AUTO_SEED=false` for an empty local or controlled deployment. Programmatic tests and integrations using `create_app()` remain empty unless `auto_seed=True` is explicitly passed.

Seeded records are demonstration evidence only. They are not real customers, production revenue or causal uplift.
