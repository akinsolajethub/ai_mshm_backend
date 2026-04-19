from django.db import migrations

NIGERIAN_STATES = [
    ("Abuja", "FCT", "NC"),
    ("Abia", "ABV", "SE"),
    ("Adamawa", "ADA", "NE"),
    ("Akwa Ibom", "AKW", "SS"),
    ("Anambra", "ANM", "SE"),
    ("Bauchi", "BAU", "NE"),
    ("Bayelsa", "BAY", "SS"),
    ("Benue", "BEN", "NC"),
    ("Borno", "BOR", "NE"),
    ("Cross River", "CRS", "SS"),
    ("Delta", "DEL", "SS"),
    ("Ebonyi", "EBO", "SE"),
    ("Edo", "EDO", "SE"),
    ("Ekiti", "EKI", "SW"),
    ("Enugu", "ENU", "SE"),
    ("Gombe", "GOM", "NE"),
    ("Imo", "IMO", "SE"),
    ("Jigawa", "JIG", "NW"),
    ("Kaduna", "KAD", "NW"),
    ("Kano", "KAN", "NW"),
    ("Katsina", "KAT", "NW"),
    ("Kebbi", "KEB", "NW"),
    ("Kogi", "KOG", "NC"),
    ("Kwara", "KWA", "NC"),
    ("Lagos", "LAG", "SW"),
    ("Nasarawa", "NAS", "NC"),
    ("Niger", "NIG", "NC"),
    ("Ogun", "OGU", "SW"),
    ("Ondo", "OND", "SW"),
    ("Osun", "OSU", "SW"),
    ("Oyo", "OYO", "SW"),
    ("Plateau", "PLA", "NC"),
    ("Sokoto", "SOK", "NW"),
    ("Taraba", "TAR", "NE"),
    ("Yobe", "YOB", "NE"),
    ("Zamfara", "ZAM", "NW"),
]


def populate_states(apps, schema_editor):
    Country = apps.get_model("centers", "Country")
    State = apps.get_model("centers", "State")

    nigeria = Country.objects.filter(name="Nigeria").first()
    if not nigeria:
        return

    for name, code, zone in NIGERIAN_STATES:
        State.objects.get_or_create(
            name=name,
            country=nigeria,
            defaults={"code": code, "zone": zone, "is_active": True}
        )


def reverse_states(apps, schema_editor):
    State = apps.get_model("centers", "State")
    State.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("centers", "0010_state"),
    ]

    operations = [
        migrations.RunPython(populate_states, reverse_states),
    ]