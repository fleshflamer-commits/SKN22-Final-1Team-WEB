from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mirrai_app", "0010_client_terminology_alignment"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Partner",
            new_name="AdminAccount",
        ),
        migrations.AlterModelTable(
            name="adminaccount",
            table="admin_accounts",
        ),
        migrations.RenameField(
            model_name="styleselection",
            old_name="is_sent_to_designer",
            new_name="is_sent_to_admin",
        ),
        migrations.RenameField(
            model_name="consultationrequest",
            old_name="partner",
            new_name="admin",
        ),
        migrations.RenameField(
            model_name="clientsessionnote",
            old_name="partner",
            new_name="admin",
        ),
    ]
