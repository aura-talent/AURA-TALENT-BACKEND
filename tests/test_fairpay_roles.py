from app.services.fairpay_roles import find_role, match_role

ROLES = [
    {"id": "software-engineer", "title": "Software Engineer"},
    {"id": "backend-engineer", "title": "Backend Engineer"},
    {"id": "frontend-developer", "title": "Frontend Developer"},
    {"id": "full-stack-developer", "title": "Full-Stack Developer"},
    {"id": "machine-learning-engineer", "title": "Machine Learning Engineer"},
    {"id": "data-analyst", "title": "Data Analyst"},
    {"id": "ui-ux-designer", "title": "UI/UX Designer"},
]


def test_find_role_by_id():
    assert find_role(ROLES, "backend-engineer")["title"] == "Backend Engineer"


def test_find_role_unknown_id_is_none():
    assert find_role(ROLES, "barista") is None
    assert find_role(ROLES, None) is None


def test_exact_title_match():
    assert match_role(ROLES, "Software Engineer")["id"] == "software-engineer"


def test_title_inside_headline(self=None):
    assert match_role(ROLES, "Senior Backend Engineer at Grab")["id"] == "backend-engineer"


def test_longest_title_wins():
    # "Machine Learning Engineer" contains "Engineer"-ish fragments; the
    # most specific (longest) matching title must win.
    assert match_role(ROLES, "Machine Learning Engineer, 5 yrs")["id"] == "machine-learning-engineer"


def test_alias_swe():
    assert match_role(ROLES, "SWE @ FAANG")["id"] == "software-engineer"


def test_alias_software_developer():
    assert match_role(ROLES, "Software Developer")["id"] == "software-engineer"


def test_alias_full_stack_spacing():
    assert match_role(ROLES, "Full Stack Developer")["id"] == "full-stack-developer"


def test_first_matching_text_wins_across_candidates():
    assert match_role(ROLES, None, "Frontend Developer")["id"] == "frontend-developer"


def test_no_match_is_none():
    assert match_role(ROLES, "Marine Biologist") is None
    assert match_role(ROLES, None, "") is None


def test_alias_requires_word_boundary():
    # "answered" contains the letters s-w-e; must NOT match software-engineer
    assert match_role(ROLES, "Answered support tickets") is None
