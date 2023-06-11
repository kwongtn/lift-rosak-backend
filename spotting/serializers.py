from rest_framework import serializers


class SnippetSerializer(serializers.Serializer):
    spotting_event_id = serializers.IntegerField()
    image = serializers.ImageField()
