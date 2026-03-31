# Generated migration file

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0003_examresult_graded_at_examresult_is_graded'),
    ]

    operations = [
        migrations.AddField(
            model_name='exam',
            name='expiration_time',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
