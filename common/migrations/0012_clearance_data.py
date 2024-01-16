from django.db import migrations


def add_clearance(apps, schema_editor):
    from common.enums import ClearanceType
    from common.models import Clearance as ClearanceModelType

    Clearance: ClearanceModelType = apps.get_model("common", "Clearance")

    Clearance.objects.bulk_create(
        [Clearance(name=j) for j in [i[0] for i in ClearanceType.choices]],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0011_clearance_temporarymedia_status_userclearance_and_more"),
    ]

    operations = [
        migrations.RunPython(
            code=add_clearance,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
