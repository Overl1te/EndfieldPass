from django import template

from core.localization import get_request_language, translate


register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, key, **kwargs):
    """Translate key inside template using current request language."""
    request = context.get("request")
    lang = context.get("current_lang") or get_request_language(request)
    return translate(lang, key, **kwargs)
