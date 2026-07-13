# Umami operations

## Secrets

Before Flux reconciliation, write a random 32-byte hexadecimal value to
`secret/umami/app` as `app_secret`. Vault Secrets Operator creates the
`umami-app` Kubernetes Secret. CNPG creates the database credentials.

## First login

The dashboard is internal and the HTTPRoute fails closed through Authentik.
After the first successful reconciliation:

1. Confirm the `Umami analytics` Authentik blueprint is healthy and assigned to
   the embedded outpost.
2. Open `https://analytics.talos.froystein.jp` through Authentik.
3. Sign in to Umami with its one-time upstream default credentials.
4. Replace the default password with a generated password stored in the
   password manager, then sign out and prove the old password fails.
5. Create the `www.froystein.jp` website and record its website ID for the site
   repository.

Do not make the public collector route available until step 4 is complete.

## Acceptance checks

Use the repository kubeconfig explicitly.

```sh
kubectl --kubeconfig ./kubeconfig -n umami get cluster,pods,cronjobs
curl -I https://analytics.talos.froystein.jp/
curl -I https://analytics.talos.froystein.jp/outpost.goauthentik.io/ping
curl -I https://www.froystein.jp/_analytics/script.js
curl -I https://www.froystein.jp/_analytics/api/send
curl -I https://www.froystein.jp/api/admin/websites
```

Expected results:

- an unauthenticated dashboard request redirects to Authentik;
- the outpost ping returns 204;
- the tracker is reachable;
- the collector accepts only its configured endpoint;
- an Umami admin API path on the public hostname is handled by the website,
  not Umami.

## Backup and restore test

The job mounts the existing `/mnt/user/backup` NFS export and creates the
`umami/daily` and `umami/monthly` directories itself. The resulting storage
path is `/mnt/user/backup/umami`. Daily files are kept for 14 days and
first-of-month copies for about six months.

After the first backup succeeds, create a temporary database in the CNPG
cluster, restore the newest dump with `pg_restore`, compare the table list and
row counts, then drop the temporary database. Record the test date in the pull
request. A successful CronJob alone is not proof that a backup is restorable.

## Retention

The hourly maintenance job removes region and city values, preserving country
only. It deletes sessions and related analytics data after 13 months. The SQL
matches the Umami v3.2.0 Prisma schema and must be reviewed when the image is
upgraded.
