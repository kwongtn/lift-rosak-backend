import json

from django.utils.safestring import mark_safe
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import JsonLexer


class JsonPrettifyAdminMixin:
    def prettify_json(self, body):
        """
        Return html formatted json body dict with style
        Taken from
        https://daniel.roygreenfeld.com/pretty-formatting-json-django-admin.html
        """
        prettified = json.dumps(body, sort_keys=True, indent=2)
        formatter = HtmlFormatter(style="colorful")
        prettified = highlight(prettified, JsonLexer(), formatter)
        style = "<style>" + formatter.get_style_defs() + "</style><br>"
        return mark_safe(style + prettified)
