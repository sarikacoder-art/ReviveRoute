# Durable Render storage

ReviveRoute uses SQLite when `DATABASE_URL` is unset, which keeps local setup and
tests simple. Hosted deployments should set `DATABASE_URL` to a managed
PostgreSQL connection URL. Cases, scheduled actions, outcomes, promises and the
audit chain then survive web-service restarts and redeployments.

## Render setup

1. In the same Render workspace and region as the web service, create a Render
   Postgres database.
2. Open the database's **Info** page and copy its **Internal Database URL**.
3. Open the ReviveRoute web service, select **Environment**, and add:

   ```text
   DATABASE_URL=<internal database URL>
   ```

4. Save and deploy.
5. Open `/health` and confirm `storage` is `POSTGRESQL`.
6. Add one fictional dashboard case, restart the web service, and confirm that
   the case remains before creating another Razorpay Test Mode failure.

Never commit a database URL. It contains database credentials. Render's Free
Postgres plan expires after 30 days and has no backups, so it is suitable for
the Buildathon demonstration but not long-term production storage.