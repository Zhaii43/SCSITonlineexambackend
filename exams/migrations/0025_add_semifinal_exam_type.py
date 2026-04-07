from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0024_backfill_is_draft'),
    ]

    operations = [
        migrations.AlterField(
            model_name='exam',
            name='exam_type',
            field=models.CharField(
                choices=[
                    ('prelim', 'Prelim'),
                    ('midterm', 'Midterm'),
                    ('semifinal', 'Semi-Final'),
                    ('final', 'Final'),
                    ('quiz', 'Quiz'),
                    ('practice', 'Practice'),
                ],
                max_length=10,
            ),
        ),
    ]
