#!/bin/bash

REPO="COWI-MI/PM"         # Your repo
FROM_ISSUE_NUMBER=19     # Starting issue number to delete from

# Fetch up to 1000 issues, then loop
gh issue list --repo "$REPO" --state all --limit 1000 --json number,title |
  jq -c '.[]' | while read -r issue; do
    ISSUE_NUMBER=$(echo "$issue" | jq '.number')
    ISSUE_TITLE=$(echo "$issue" | jq -r '.title')

    if (( ISSUE_NUMBER >= FROM_ISSUE_NUMBER )); then
      echo "Deleting issue #$ISSUE_NUMBER: $ISSUE_TITLE"
      if ! gh issue delete "$ISSUE_NUMBER" --repo "$REPO" --yes; then
        echo "Failed to delete issue #$ISSUE_NUMBER" >> deletion_errors.log
      fi
    fi
  done

echo "Deletion complete for issues numbered $FROM_ISSUE_NUMBER and up."
