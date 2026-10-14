def document_canonical_routes(endpoints):
    aliases = {
        "/api/v1/cart/",
        "/api/v1/orders/",
        "/api/v1/wishlist/",
    }
    canonical_methods = {
        "/api/v1/cart": {"get", "delete"},
        "/api/v1/cart/items": {"post"},
    }
    filtered = []
    for path, path_regex, method, callback in endpoints:
        if path in aliases:
            continue
        allowed_methods = canonical_methods.get(path)
        if allowed_methods is not None and method.lower() not in allowed_methods:
            continue
        if path == "/api/v1/cart/items/{item_id}" and method.lower() not in {
            "patch",
            "delete",
        }:
            continue
        filtered.append((path, path_regex, method, callback))
    return filtered
