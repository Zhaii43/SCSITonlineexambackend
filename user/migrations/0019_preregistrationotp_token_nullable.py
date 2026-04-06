from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0018_user_declaration_verified'),
    ]

    operations = [
        migrations.AlterField(
            model_name='preregistrationotp',
            name='token',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
    ]
