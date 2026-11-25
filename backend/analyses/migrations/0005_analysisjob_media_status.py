from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analyses", "0004_camerasession")]

    operations = [
        migrations.AddField(
            model_name="analysisjob", name="media_status",
            field=models.CharField(blank=True, max_length=12),
        ),
    ]
