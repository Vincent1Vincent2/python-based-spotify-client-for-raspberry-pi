def account_menu_state(accounts, active_account):
    """Rows for the header account menu.

    ``accounts`` is any iterable of objects with ``id``, ``display_name``,
    ``avatar_url``, and ``spotify_user_id``. ``active_account`` is the
    session's account, or None. The result is plain data: it does not
    read or copy tokens.
    """
    active_id = getattr(active_account, "id", None)
    rows = []
    active_row = None
    for account in accounts or ():
        display_name = str(getattr(account, "display_name", "") or "").strip()
        user_id = str(getattr(account, "spotify_user_id", "") or "").strip()
        label = display_name or user_id or "Spotify account"
        row = {
            "id": account.id,
            "label": label,
            "avatar_url": getattr(account, "avatar_url", "") or "",
            "initial": label[:1].upper(),
            "active": account.id == active_id,
        }
        rows.append(row)
        if row["active"]:
            active_row = row
    if active_row:
        label = active_row["label"]
        initial = active_row["initial"]
        avatar_url = active_row["avatar_url"]
    else:
        label = "Account"
        initial = "A"
        avatar_url = ""
    return {
        "label": label,
        "initial": initial,
        "avatar_url": avatar_url,
        "active": active_row is not None,
        "rows": rows,
    }
