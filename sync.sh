#!/bin/bash
# Auto-sync claudecode repo to GitHub

cd /home/ubuntu/claudecode

# Pull latest first
git pull origin main --rebase 2>/dev/null

# Stage all changes
git add -A

# Only commit if there are changes
if ! git diff --cached --quiet; then
  git commit -m "auto-sync: $(date '+%Y-%m-%d %H:%M')"
  git push origin main
fi
