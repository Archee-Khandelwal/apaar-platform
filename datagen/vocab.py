"""Invented vocabulary for the synthetic dataset.

Institution names are built from made-up word combinations. CLAUDE.md section 5 rule 13:
never a real college name, especially in a fraud scenario.
"""
from __future__ import annotations

# Invented place-like words (not real cities) used as institution name stems.
NAME_STEMS: tuple[str, ...] = (
    "Vindhyashree", "Kharapur", "Tamravati", "Nilgiriya", "Saptagiri Nandan",
    "Chandrapuri", "Arunvalli", "Meghdoot", "Suryagarh", "Rathnapura",
    "Virajpet Nagar", "Bhairavkund", "Kaveripura", "Tungabhadri", "Shivalik Nandan",
    "Panchvati", "Amaravati Nandan", "Girnarpur", "Dwarkeshwar", "Narmadapuri",
    "Udaygiri", "Kanchanpur", "Sahyadri Nandan", "Brahmaputri", "Maruthvalli",
    "Yamunotri", "Aravalli Nandan", "Kolhanpur", "Pampavati", "Satpuri",
    "Mahanadi Nandan", "Trivendri", "Kundalini Nagar", "Charminara", "Vaitarna",
    "Godavari Nandan", "Sindhupuri", "Ratangarh Nandan", "Chenabpura", "Kaladgi",
)

INSTITUTION_SUFFIXES: tuple[str, ...] = (
    "Institute of Technology",
    "College of Engineering",
    "Technical Institute",
    "Institute of Engineering and Technology",
    "College of Engineering and Management",
    "Institute of Science and Technology",
)

INSTITUTION_TYPES: tuple[str, ...] = (
    "private_unaided",
    "private_unaided",
    "private_unaided",
    "government",
    "government_aided",
    "autonomous",
)

# (state, region)
STATES: tuple[tuple[str, str], ...] = (
    ("Madhya Pradesh", "Central"),
    ("Maharashtra", "West"),
    ("Tamil Nadu", "South"),
    ("Karnataka", "South"),
    ("Uttar Pradesh", "North"),
    ("Odisha", "East"),
    ("Gujarat", "West"),
    ("Telangana", "South"),
    ("Rajasthan", "North"),
    ("West Bengal", "East"),
)

BTECH_BRANCHES: tuple[str, ...] = (
    "Computer Science and Engineering",
    "Electronics and Communication Engineering",
    "Mechanical Engineering",
    "Civil Engineering",
    "Electrical Engineering",
    "Information Technology",
    "Artificial Intelligence and Data Science",
)

# (course, branch, level, mode)
PG_PROGRAMS: tuple[tuple[str, str, str, str], ...] = (
    ("MBA", "General", "PG", "regular"),
    ("MCA", "General", "PG", "regular"),
)

ONLINE_PROGRAMS: tuple[tuple[str, str, str, str], ...] = (
    ("MBA", "General (Online/ODL)", "PG", "online"),
    ("MCA", "General (Online/ODL)", "PG", "online"),
    ("B.Tech", "Computer Science and Engineering (Online/ODL)", "UG", "online"),
)

# AICTE approves intake in multiples of 30. Occupancy in private technical
# institutions is commonly 40-70%, which the generator reproduces.
INTAKE_CHOICES: tuple[int, ...] = (30, 60, 60, 60, 120, 120, 180)

CATEGORIES: tuple[str, ...] = ("GEN", "OBC-NCL", "SC", "ST", "EWS")
CATEGORY_WEIGHTS: tuple[float, ...] = (0.38, 0.30, 0.15, 0.07, 0.10)

GENDERS: tuple[str, ...] = ("M", "F", "O")
GENDER_WEIGHTS: tuple[float, ...] = (0.66, 0.335, 0.005)

VERIFIER_NAMES: tuple[str, ...] = (
    "Nilgiri Softworks Pvt Ltd",
    "Brahmaputri Analytics LLP",
    "Suryagarh State Scholarship Board",
)
