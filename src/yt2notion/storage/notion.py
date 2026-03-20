"""Notion storage backend. Creates pages with rich content."""

from __future__ import annotations

# TODO: Implement NotionStorage
# - __init__(token, database_id, directory_rules)
# - save(): create Notion page with:
#   - Title (Chinese title from content)
#   - Credit block (source channel, title, link)
#   - Sections with timestamp links
#   - Overall summary
#   - Tags as multi-select property
#   - Route to correct parent based on directory_rules
# - Handle 2000-char block limit by splitting long sections
