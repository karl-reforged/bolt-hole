"""One small policy for deciding whether a listing belongs in the shortlist."""

import re


ACTIVE_STATUS = "active"
POSSIBLY_UNAVAILABLE_STATUS = "possibly_unavailable"
ARCHIVED_STATUSES = frozenset({"under_offer", "sold", "withdrawn", "archived"})
ALLOWED_STATUSES = frozenset({ACTIVE_STATUS, POSSIBLY_UNAVAILABLE_STATUS}) | ARCHIVED_STATUSES

_UNDER_OFFER = re.compile(r"\b(under offer|under contract|deposit taken)\b", re.IGNORECASE)
_SOLD = re.compile(r"^\W*sold\W*$", re.IGNORECASE)
_WITHDRAWN = re.compile(r"^\W*(withdrawn|off market)\W*$", re.IGNORECASE)

STATUS_LABELS = {
    ACTIVE_STATUS: "Available",
    POSSIBLY_UNAVAILABLE_STATUS: "Possibly unavailable",
    "under_offer": "Under offer",
    "sold": "Sold",
    "withdrawn": "Withdrawn",
    "archived": "No longer listed",
}


def availability_status(prop, *, missing_from_latest=False, missing_days=0):
    """Return the normalized availability status for one property.

    Explicit database statuses win. Otherwise only short, status-like listing
    fields are inspected; descriptions are deliberately ignored to avoid
    false matches such as "auction unless sold prior" or historic sales copy.
    """
    explicit = str(prop.get("status") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if explicit in ARCHIVED_STATUSES:
        return explicit

    status_labels = [
        str(prop.get(key) or "").strip()
        for key in ("listing_status", "badge", "display_price", "headline")
    ]
    if any(_UNDER_OFFER.search(label) for label in status_labels):
        return "under_offer"
    if any(_SOLD.match(label) for label in status_labels):
        return "sold"
    if any(_WITHDRAWN.match(label) for label in status_labels):
        return "withdrawn"
    if missing_from_latest:
        return "archived" if int(missing_days or 0) > 21 else POSSIBLY_UNAVAILABLE_STATUS
    return ACTIVE_STATUS


def is_archived_status(status):
    return status in ARCHIVED_STATUSES


def status_label(status):
    return STATUS_LABELS.get(status, STATUS_LABELS[ACTIVE_STATUS])
