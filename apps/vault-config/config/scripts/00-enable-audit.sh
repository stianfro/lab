#!/bin/bash
# Enable audit logging to file
set -e

echo "Enabling audit logging..."
vault audit enable file file_path=/vault/audit/audit.log || echo "Audit device already enabled"
echo "Audit logging enabled."
