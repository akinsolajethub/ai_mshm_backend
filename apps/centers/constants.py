"""
Downstream disease constants and routing mappings.
"""

DOWNSTREAM_DISEASES = {
    "type2_diabetes": {
        "name": "Type 2 Diabetes / Metabolic Syndrome",
        "specializations": [
            "diabetology",
            "endocrinology",
            "general_practice",
            "family_medicine",
            "internal_medicine",
            "nutrition",
            "community_health",
        ],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "cardiovascular_disease": {
        "name": "Cardiovascular Disease (CVD, Hypertension)",
        "specializations": [
            "cardiology",
            "hypertension",
            "internal_medicine",
            "general_practice",
            "family_medicine",
            "preventive_medicine",
        ],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "obesity": {
        "name": "Obesity",
        "specializations": [
            "obesity_medicine",
            "endocrinology",
            "nutrition",
            "general_practice",
            "family_medicine",
            "behavioral_medicine",
        ],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "infertility": {
        "name": "Infertility & Reproductive Complications",
        "specializations": [
            "reproductive_endocrinology",
            "obstetrics_gynae",
            "general_practice",
            "family_medicine",
            "adolescent_medicine",
        ],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "endometrial_hyperplasia": {
        "name": "Endometrial Hyperplasia / Cancer",
        "specializations": ["gynecologic_oncology", "obstetrics_gynae"],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "fatty_liver": {
        "name": "Nonalcoholic Fatty Liver Disease (NAFLD)",
        "specializations": ["hepatology", "gastroenterology", "endocrinology", "internal_medicine"],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "sleep_apnea": {
        "name": "Sleep Apnea",
        "specializations": ["sleep_medicine", "pulmonology", "ent"],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "pregnancy_complications": {
        "name": "Pregnancy Complications (GDM, Pre-eclampsia)",
        "specializations": ["maternal_fetal_medicine", "obstetrics_gynae", "diabetology"],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "mental_health": {
        "name": "Mental Health (Depression, Anxiety)",
        "specializations": [
            "psychiatry",
            "clinical_psychology",
            "general_practice",
            "family_medicine",
            "community_mental_health",
        ],
        "severity_tiers": ["low", "moderate", "high"],
    },
    "dermatologic": {
        "name": "Dermatologic Manifestations (Acne, Hirsutism)",
        "specializations": ["dermatology", "endocrinology"],
        "severity_tiers": ["low", "moderate", "high"],
    },
}

DOWNSTREAM_DISEASE_CHOICES = [(key, val["name"]) for key, val in DOWNSTREAM_DISEASES.items()]

SPECIALIZATION_TO_DISEASES = {}
for disease_key, disease_data in DOWNSTREAM_DISEASES.items():
    for spec in disease_data["specializations"]:
        if spec not in SPECIALIZATION_TO_DISEASES:
            SPECIALIZATION_TO_DISEASES[spec] = []
        SPECIALIZATION_TO_DISEASES[spec].append(disease_key)


def get_matching_clinicians(disease: str, fhc_id: str, expertise_list: list = None):
    """
    Get list of clinicians who can treat a specific downstream disease.

    Args:
        disease: downstream disease key (e.g., 'type2_diabetes')
        fhc_id: FederalHealthCenter UUID to filter by
        expertise_list: if provided, filter clinicians whose downstream_expertise contains this disease

    Returns:
        QuerySet of matching ClinicianProfile objects
    """
    from .models import ClinicianProfile

    queryset = ClinicianProfile.objects.filter(
        fhc_id=fhc_id,
        is_verified=True,
        onboarded=True,
    )

    if expertise_list is None:
        disease_info = DOWNSTREAM_DISEASES.get(disease)
        if disease_info:
            expertise_list = disease_info.get("specializations", [])

    if expertise_list:
        queryset = queryset.filter(specialization__in=expertise_list)

    return queryset.select_related("user")


def route_case_to_clinician(disease: str, fhc_id: str):
    """
    Find the best clinician for a case.

    Priority:
    1. Onboarded & verified clinicians with matching downstream_expertise
    2. Onboarded & verified clinicians with matching specialization

    Args:
        disease: downstream disease key
        fhc_id: FederalHealthCenter UUID

    Returns:
        ClinicianProfile or None if no match found
    """
    from .models import ClinicianProfile

    matching_specializations = DOWNSTREAM_DISEASES.get(disease, {}).get("specializations", [])

    if matching_specializations:
        clinicians = ClinicianProfile.objects.filter(
            fhc_id=fhc_id,
            is_verified=True,
            onboarded=True,
            specialization__in=matching_specializations,
        ).order_by("years_of_experience")

        for clinician in clinicians:
            if disease in (clinician.downstream_expertise or []):
                return clinician

        return clinicians.first()

    return None
