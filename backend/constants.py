"""Shared database expressions."""

# Roster and suspension dates use the Blacksburg calendar.
LOCAL_TODAY = "(NOW() AT TIME ZONE 'America/New_York')::date"
