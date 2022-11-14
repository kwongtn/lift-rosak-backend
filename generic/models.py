from django.contrib.gis.db import models


class WebLocationModel(models.Model):
    accuracy = models.DecimalField(
        blank=True, null=True, default=None, max_digits=12, decimal_places=6
    )
    altitude = models.DecimalField(
        blank=True, null=True, default=None, max_digits=12, decimal_places=6
    )
    altitude_accuracy = models.DecimalField(
        blank=True, null=True, default=None, max_digits=12, decimal_places=6
    )
    heading = models.DecimalField(
        blank=True, null=True, default=None, max_digits=9, decimal_places=5
    )
    speed = models.DecimalField(
        blank=True, null=True, default=None, max_digits=9, decimal_places=3
    )

    # Combination of 'latitude', 'longitude' and altitude fields
    location = models.PointField(
        blank=False,
        null=False,
    )

    class Meta:
        abstract = True
