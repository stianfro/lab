# Backup policy - allows taking Raft snapshots
# Used by the vault-backup CronJob

path "sys/storage/raft/snapshot" {
  capabilities = ["read"]
}
