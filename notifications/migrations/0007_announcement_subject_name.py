from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0006_announcement_year_level'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='subject_name',
            field=models.CharField(max_length=120, blank=True, null=True, help_text='Subject this announcement targets (instructor announcements)'),
        ),
    ]
