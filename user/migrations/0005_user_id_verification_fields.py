# Generated migration file

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('user', '0004_passwordresettoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='id_photo',
            field=models.ImageField(blank=True, null=True, upload_to='id_photos/'),
        ),
        migrations.AddField(
            model_name='user',
            name='id_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='id_verified_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='id_verified_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='id_verified_users', to='user.user'),
        ),
    ]

