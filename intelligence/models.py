from django.db import models
from django.utils import timezone


class ActionableEvent(models.Model):
    event_type = models.CharField(max_length=100, db_index=True)
    start_time = models.DateTimeField(default=timezone.now)
    duration_minutes = models.IntegerField(help_text="Duration in minutes")

    focus_score = models.IntegerField(
        null=True,
        blank=True,
        help_text="Subjective score 1-10",
    )

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-start_time"]

    def __str__(self) -> str:
        return (
            f"{self.event_type} - {self.duration_minutes}m on "
            f"{self.start_time.strftime('%Y-%m-%d')}"
        )


class ActivityEmbedding(models.Model):
    event = models.OneToOneField(
        ActionableEvent,
        on_delete=models.CASCADE,
        related_name="embedding_record",
    )
    text_input = models.TextField()
    embedding = models.JSONField(default=list, blank=True)
    predicted_class = models.CharField(max_length=20, db_index=True)
    confidence = models.FloatField(default=0.0)
    used_fallback = models.BooleanField(default=False)
    cluster_id = models.IntegerField(null=True, blank=True, db_index=True)
    classifier_version = models.CharField(max_length=50, default="phase2-v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class RegimeSnapshot(models.Model):
    snapshot_date = models.DateField(unique=True, db_index=True)
    regime_label = models.CharField(max_length=30, db_index=True)
    regime_score = models.FloatField(default=0.0)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-snapshot_date"]


class InterventionLog(models.Model):
    action = models.CharField(max_length=60, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    predicted_uplift = models.FloatField(default=0.0)
    reward = models.FloatField(null=True, blank=True)
    accepted = models.BooleanField(default=True)
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class HabitInfluenceEdge(models.Model):
    source_label = models.CharField(max_length=255, db_index=True)
    target_label = models.CharField(max_length=255, db_index=True)
    weight = models.FloatField(default=0.0)
    transition_count = models.IntegerField(default=0)
    avg_gap_minutes = models.FloatField(default=0.0)
    positive_impact = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-weight"]
        unique_together = ("source_label", "target_label")
