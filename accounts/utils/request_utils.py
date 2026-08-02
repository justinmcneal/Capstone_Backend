from rest_framework.settings import api_settings


def get_client_ip(request) -> str:
    """Return the client IP using DRF's explicitly configured proxy trust depth."""
    remote_addr = request.META.get("REMOTE_ADDR", "")
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    num_proxies = api_settings.NUM_PROXIES

    if num_proxies is None:
        return forwarded_for.replace(" ", "") if forwarded_for else remote_addr
    if num_proxies == 0 or not forwarded_for:
        return remote_addr

    addresses = [address.strip() for address in forwarded_for.split(",")]
    if len(addresses) < num_proxies:
        return remote_addr
    return addresses[-min(num_proxies, len(addresses))]
