from django.urls import reverse

# liveaux has two sides: Live, out in the city, and Aux, at home. Every page belongs to one of them
# (or to neither, like account pages), which sets its colour and the navigation under the header.
LIVE_NAMESPACES = {"events", "logbook"}
AUX_NAMESPACES = {"library", "social_aux"}

# (url name, label, needs login)
NAV = {
    "live": [
        ("live", "Overview", False),
        ("events:this_week", "This week", False),
        ("events:event_list", "What's on", False),
        ("logbook:mine", "Log", True),
        ("events:submit_event", "Submit", True),
    ],
    "aux": [
        ("aux", "Overview", False),
        ("library:browse", "Everything", True),
        ("library:search", "Add", True),
        ("library:calendar", "Calendar", True),
        ("library:diary", "Diary", True),
        ("library:stats", "Stats", True),
        ("library:lists", "Lists", True),
        ("library:collection", "Collection", True),
        ("library:discover", "Discover", True),
    ],
}

# Pages that sit under another tab of the subnav, so that tab stays lit.
PARENT = {
    "events:city_week": "events:this_week",
    "logbook:my_year": "logbook:mine",
    "library:index": "aux",
    "library:item": "library:browse",
    "library:list_detail": "library:lists",
    "library:import": "library:browse",
    "library:connect": "library:browse",
}


def side_of(match):
    if match is None:
        return ""
    if match.view_name in ("live", "aux"):
        return match.view_name
    if match.namespace in LIVE_NAMESPACES:
        return "live"
    if match.namespace in AUX_NAMESPACES:
        return "aux"
    return ""


def sides(request):
    match = getattr(request, "resolver_match", None)
    side = side_of(match)
    current = PARENT.get(match.view_name, match.view_name) if match else ""
    nav = [
        {"href": reverse(name), "label": label, "current": name == current}
        for name, label, needs_login in NAV.get(side, [])
        if request.user.is_authenticated or not needs_login
    ]
    return {"side": side, "side_nav": nav}
