from django.db import models


class DataSources(models.TextChoices):
    PRASARANA = "PRASARANA"
    MLPTF = "MLPTF"
    MTREC = "MTREC"
    MRFC = "MRFC"
