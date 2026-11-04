"""Cap and dedupe recent search queries.

The player keeps the list in localStorage. These are the rules that list
follows: newest first, at most eight distinct queries, a repeat moves to
the front, and empty strings are ignored.
"""

LIMIT = 8


def remember_query(history, query):
    """Return a new recent-query list with ``query`` applied.

    ``history`` is not modified. Non-strings and blank strings are skipped.
    Stored text is stripped, so a later search for the same words replaces
    the older copy instead of sitting beside it.
    """
    previous = []
    for item in history or []:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text in previous:
            continue
        previous.append(text)

    if not isinstance(query, str):
        return previous[:LIMIT]
    query_text = query.strip()
    if not query_text:
        return previous[:LIMIT]
    previous = [item for item in previous if item != query_text]
    return [query_text, *previous][:LIMIT]
