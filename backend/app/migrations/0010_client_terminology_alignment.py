from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mirrai_app", "0009_customer_age_fields"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Customer",
            new_name="Client",
        ),
        migrations.AlterModelTable(
            name="client",
            table="clients",
        ),
        migrations.RenameField(
            model_name="survey",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameField(
            model_name="capturerecord",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameField(
            model_name="faceanalysis",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameField(
            model_name="formerrecommendation",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameField(
            model_name="styleselection",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameField(
            model_name="consultationrequest",
            old_name="customer",
            new_name="client",
        ),
        migrations.RenameModel(
            old_name="CustomerSessionNote",
            new_name="ClientSessionNote",
        ),
        migrations.AlterModelTable(
            name="clientsessionnote",
            table="client_session_notes",
        ),
        migrations.RenameField(
            model_name="clientsessionnote",
            old_name="customer",
            new_name="client",
        ),
    ]
