# Generated migration file

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0004_exam_expiration_time'),
    ]

    operations = [
        migrations.AlterField(
            model_name='exam',
            name='year_level',
            field=models.CharField(max_length=50),
        ),
    ]
