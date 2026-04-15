from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0023_alter_user_role_add_edp'),
    ]

    operations = [
        migrations.CreateModel(
            name='MasterlistImportRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('department', models.CharField(blank=True, max_length=10)),
                ('filename', models.CharField(blank=True, max_length=255)),
                ('status', models.CharField(choices=[('processing', 'Processing'), ('completed', 'Completed'), ('completed_with_warnings', 'Completed With Warnings'), ('failed', 'Failed')], default='processing', max_length=30)),
                ('success_count', models.PositiveIntegerField(default=0)),
                ('error_count', models.PositiveIntegerField(default=0)),
                ('email_total', models.PositiveIntegerField(default=0)),
                ('email_sent', models.PositiveIntegerField(default=0)),
                ('email_failed', models.PositiveIntegerField(default=0)),
                ('email_pending', models.PositiveIntegerField(default=0)),
                ('row_errors', models.JSONField(blank=True, default=list)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='masterlist_import_runs', to='user.user')),
            ],
            options={
                'db_table': 'masterlist_import_runs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MasterlistImportEmailStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('school_id', models.CharField(blank=True, max_length=20)),
                ('email', models.EmailField(max_length=254)),
                ('first_name', models.CharField(blank=True, max_length=100)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('error_message', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('import_run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_statuses', to='user.masterlistimportrun')),
            ],
            options={
                'db_table': 'masterlist_import_email_statuses',
                'ordering': ['id'],
            },
        ),
    ]
