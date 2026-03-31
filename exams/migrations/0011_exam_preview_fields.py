# Generated migration file

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0010_examphoto_violation_reason_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='exam',
            name='preview_rules',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='exam',
            name='sample_questions',
            field=models.JSONField(blank=True, null=True),
        ),
    ]

