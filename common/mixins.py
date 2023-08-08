from django.utils.safestring import mark_safe


class MediaMixin:
    def __str__(self) -> str:
        return self.file.name

    def image_widget_html(self, style: str = "max-width: 45vw;") -> str:
        return f'<img src="{self.file.url}" style="{style}" />'

    def image_widget(self, *args, **kwargs):
        return mark_safe(self.image_widget_html(*args, **kwargs))
