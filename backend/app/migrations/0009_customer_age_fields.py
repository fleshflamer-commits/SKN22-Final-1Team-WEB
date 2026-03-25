from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mirrai_app", "0008_alter_capturerecord_filename_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="age_input",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customer",
            name="birth_year_estimate",
            field=models.PositiveSmallIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
