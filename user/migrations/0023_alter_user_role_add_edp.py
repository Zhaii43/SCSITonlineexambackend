from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0022_subjectassignment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('student', 'Student'),
                    ('instructor', 'Instructor'),
                    ('dean', 'Dean'),
                    ('edp', 'EDP'),
                ],
                default='student',
                max_length=10,
            ),
        ),
    ]
