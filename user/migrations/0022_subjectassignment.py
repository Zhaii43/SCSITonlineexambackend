from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0021_add_force_password_change'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubjectAssignment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('department', models.CharField(choices=[('BSHM', 'Hospitality Management'), ('BSIT', 'Information Technology'), ('BSEE', 'Electrical Engineering'), ('BSBA', 'Business Administration'), ('BSCRIM', 'Criminology'), ('BSED', 'Education'), ('BSCE', 'Civil Engineering'), ('BSChE', 'Chemical Engineering'), ('BSME', 'Mechanical Engineering'), ('GENERAL', 'General Education')], max_length=10)),
                ('subject_name', models.CharField(max_length=120)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_subject_assignments', to='user.user')),
                ('instructor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subject_assignments', to='user.user')),
            ],
            options={
                'db_table': 'subject_assignments',
                'ordering': ['department', 'subject_name'],
            },
        ),
        migrations.AddConstraint(
            model_name='subjectassignment',
            constraint=models.UniqueConstraint(fields=('instructor', 'department', 'subject_name'), name='unique_instructor_subject_assignment'),
        ),
    ]
