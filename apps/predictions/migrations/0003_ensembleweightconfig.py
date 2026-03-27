# Generated migration for EnsembleWeightConfig and ComprehensivePredictionResult updates

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("predictions", "0002_comprehensivepredictionresult"),
    ]

    operations = [
        # Add new fields to ComprehensivePredictionResult
        migrations.AddField(
            model_name="comprehensivepredictionresult",
            name="pcos_specific_score",
            field=models.FloatField(
                blank=True,
                help_text="PCOS-specific risk score with clinical rule adjustments",
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(0.0),
                    django.core.validators.MaxValueValidator(1.0),
                ],
            ),
        ),
        migrations.AddField(
            model_name="comprehensivepredictionresult",
            name="per_disease_scores",
            field=models.JSONField(
                default=dict, help_text="Disease-specific scores: {'PCOS': 0.42, 'CVD': 0.55, ...}"
            ),
        ),
        migrations.AddField(
            model_name="comprehensivepredictionresult",
            name="weights_used",
            field=models.JSONField(
                default=dict, help_text="Final weights after data quality adjustment"
            ),
        ),
        migrations.AddField(
            model_name="comprehensivepredictionresult",
            name="clinical_rules_triggered",
            field=models.JSONField(
                default=list, help_text="List of clinical rules that were applied"
            ),
        ),
        migrations.AddField(
            model_name="comprehensivepredictionresult",
            name="calculation_breakdown",
            field=models.JSONField(
                default=dict, help_text="Full breakdown: base scores, boost applied, data quality"
            ),
        ),
        # Create EnsembleWeightConfig model
        migrations.CreateModel(
            name="EnsembleWeightConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "disease_name",
                    models.CharField(
                        choices=[
                            ("PCOS", "PCOS"),
                            ("CVD", "Cardiovascular Disease"),
                            ("T2D", "Type 2 Diabetes"),
                            ("Infertility", "Infertility"),
                            ("Dysmenorrhea", "Dysmenorrhea"),
                            ("Metabolic", "Metabolic Syndrome"),
                            ("MentalHealth", "Mental Health"),
                            ("Stroke", "Stroke Risk"),
                            ("Endometrial", "Endometrial Cancer"),
                        ],
                        help_text="Disease this weight configuration applies to",
                        max_length=50,
                        unique=True,
                    ),
                ),
                (
                    "symptom_weight",
                    models.FloatField(
                        default=0.3,
                        help_text="Weight for Symptom Intensity model (0.0-1.0)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "menstrual_weight",
                    models.FloatField(
                        default=0.25,
                        help_text="Weight for Menstrual model (0.0-1.0)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "rppg_weight",
                    models.FloatField(
                        default=0.25,
                        help_text="Weight for rPPG/HRV model (0.0-1.0)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "mood_weight",
                    models.FloatField(
                        default=0.2,
                        help_text="Weight for Mood model (0.0-1.0)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "rotterdam_2_criteria_boost",
                    models.FloatField(
                        default=0.05,
                        help_text="Boost when 2 Rotterdam criteria are met (+0.05 default)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(0.2),
                        ],
                    ),
                ),
                (
                    "rotterdam_3_criteria_boost",
                    models.FloatField(
                        default=0.1,
                        help_text="Boost when all 3 Rotterdam criteria are met (+0.10 default)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(0.3),
                        ],
                    ),
                ),
                (
                    "metabolic_reproductive_boost",
                    models.FloatField(
                        default=0.05,
                        help_text="Boost when metabolic + reproductive both high (+0.05 default)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(0.2),
                        ],
                    ),
                ),
                (
                    "mood_rppg_stress_boost",
                    models.FloatField(
                        default=0.03,
                        help_text="Boost when mood + rPPG stress both moderate+ (+0.03 default)",
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(0.2),
                        ],
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True, help_text="Whether this configuration is currently active"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Ensemble Weight Configuration",
                "verbose_name_plural": "Ensemble Weight Configurations",
            },
        ),
        # Data migration: Initialize default weights for all diseases
        migrations.RunPython(init_default_weights),
    ]


def init_default_weights(apps, schema_editor):
    """Initialize default weight configurations for all diseases."""
    EnsembleWeightConfig = apps.get_model("predictions", "EnsembleWeightConfig")

    default_configs = [
        {
            "disease_name": "PCOS",
            "symptom_weight": 0.30,
            "menstrual_weight": 0.35,
            "rppg_weight": 0.20,
            "mood_weight": 0.15,
        },
        {
            "disease_name": "CVD",
            "symptom_weight": 0.20,
            "menstrual_weight": 0.20,
            "rppg_weight": 0.40,
            "mood_weight": 0.20,
        },
        {
            "disease_name": "T2D",
            "symptom_weight": 0.25,
            "menstrual_weight": 0.25,
            "rppg_weight": 0.35,
            "mood_weight": 0.15,
        },
        {
            "disease_name": "Infertility",
            "symptom_weight": 0.25,
            "menstrual_weight": 0.40,
            "rppg_weight": 0.20,
            "mood_weight": 0.15,
        },
        {
            "disease_name": "Dysmenorrhea",
            "symptom_weight": 0.40,
            "menstrual_weight": 0.35,
            "rppg_weight": 0.10,
            "mood_weight": 0.15,
        },
        {
            "disease_name": "Metabolic",
            "symptom_weight": 0.20,
            "menstrual_weight": 0.20,
            "rppg_weight": 0.45,
            "mood_weight": 0.15,
        },
        {
            "disease_name": "MentalHealth",
            "symptom_weight": 0.20,
            "menstrual_weight": 0.15,
            "rppg_weight": 0.25,
            "mood_weight": 0.40,
        },
        {
            "disease_name": "Stroke",
            "symptom_weight": 0.20,
            "menstrual_weight": 0.20,
            "rppg_weight": 0.35,
            "mood_weight": 0.25,
        },
        {
            "disease_name": "Endometrial",
            "symptom_weight": 0.30,
            "menstrual_weight": 0.45,
            "rppg_weight": 0.15,
            "mood_weight": 0.10,
        },
    ]

    for config in default_configs:
        EnsembleWeightConfig.objects.create(**config)
