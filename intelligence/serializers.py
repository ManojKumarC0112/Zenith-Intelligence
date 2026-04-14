from rest_framework import serializers

from .models import ActionableEvent


class ActionableEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionableEvent
        fields = [
            "id",
            "event_type",
            "start_time",
            "duration_minutes",
            "focus_score",
            "metadata",
        ]
