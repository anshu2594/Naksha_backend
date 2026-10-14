from django.conf import settings
from django.core.checks import Error, Warning, register, Tags


@register(Tags.security, deploy=True)
def check_production_configuration(app_configs, **kwargs):
    if settings.DEBUG:
        return []

    errors = []
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        errors.append(
            Error(
                "Set explicit ALLOWED_HOSTS values for production.",
                id="backoffice.E001",
            )
        )
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        errors.append(
            Error(
                "Production must use PostgreSQL; SQLite is for development and tests.",
                id="backoffice.E002",
            )
        )
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        errors.append(
            Error(
                "Secure session and CSRF cookies must be enabled in production.",
                id="backoffice.E003",
            )
        )
    if not settings.SECURE_SSL_REDIRECT:
        errors.append(
            Warning(
                "Enable HTTPS redirects at Django or at a trusted edge proxy.",
                id="backoffice.W001",
            )
        )
    if settings.SECURE_HSTS_SECONDS < 1:
        errors.append(
            Warning(
                "Configure a positive SECURE_HSTS_SECONDS value after HTTPS is available.",
                id="backoffice.W002",
            )
        )
    key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
    if key_id and not key_id.startswith("rzp_test_"):
        errors.append(
            Error(
                "This integration accepts Razorpay test keys only.",
                id="backoffice.E004",
            )
        )
    return errors
