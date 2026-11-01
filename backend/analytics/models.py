"""
No models.

Support-effectiveness analytics are computed from tickets, executions and playbooks at
query time (see `analytics/services/metrics.py`). Materialising them would create a second
source of truth that can silently drift from the records it summarises — and the brief is
explicit that hardcoded numbers must never be presented as live analytics. Every figure
this app returns is derived from rows that exist, and each one reports the window and the
row count it was computed from.
"""
