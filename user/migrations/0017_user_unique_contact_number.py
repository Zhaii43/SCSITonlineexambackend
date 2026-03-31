from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0016_user_special_approval_fields'),
    ]

    operations = [
        migrations.RunSQL(
            "UPDATE user_user SET contact_number = NULL WHERE contact_number = '';"
        ),
        migrations.AlterField(
            model_name='user',
            name='contact_number',
            field=models.CharField(blank=True, max_length=15, null=True, unique=True),
        ),
    ]
