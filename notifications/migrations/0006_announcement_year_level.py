from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0005_alter_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='year_level',
            field=models.CharField(
                blank=True,
                choices=[('1', '1st Year'), ('2', '2nd Year'), ('3', '3rd Year'), ('4', '4th Year')],
                help_text='Leave blank for all year levels (students only)',
                max_length=1,
                null=True,
            ),
        ),
    ]
