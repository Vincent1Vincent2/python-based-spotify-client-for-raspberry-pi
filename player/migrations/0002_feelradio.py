from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('player', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeelRadio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('active', models.BooleanField(default=False)),
                ('continue_forever', models.BooleanField(default=True)),
                ('emotions', models.JSONField(default=list)),
                ('feel_name', models.CharField(blank=True, max_length=40)),
                ('counters', models.JSONField(default=dict)),
                ('pool', models.JSONField(default=list)),
                ('queued_tracks', models.JSONField(default=list)),
                ('unsnapshotted', models.JSONField(default=list)),
                ('latest_batch', models.JSONField(default=list)),
                ('live_playlist_id', models.CharField(blank=True, max_length=64)),
                ('live_playlist_name', models.CharField(blank=True, max_length=120)),
                ('snapshots', models.JSONField(default=list)),
                ('last_extend_uri', models.CharField(blank=True, max_length=128)),
                ('extend_blocked', models.BooleanField(default=False)),
                ('source_name', models.CharField(blank=True, max_length=200)),
                ('last_reads', models.JSONField(default=list)),
                ('last_query', models.CharField(blank=True, max_length=120)),
                ('account', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='feel_radio', to='player.spotifyaccount')),
            ],
        ),
    ]
