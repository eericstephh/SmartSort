"""User-defined categories.

Built-in categories are the ones that ship with the app; these are the ones the
user adds. The rules matter because the name becomes a folder on disk.
"""

from __future__ import annotations

import pytest

from smartsort.app.core.organizer import Organizer
from smartsort.app.storage.models import OrganizeRequest
from smartsort.app.storage.repositories import CategoryError, Repositories
from tests.conftest import make_file


def request(path, **kwargs) -> OrganizeRequest:
    kwargs.setdefault("origin", "browser")
    return OrganizeRequest(source_path=str(path), **kwargs)


# -- name validation ------------------------------------------------------
def test_a_name_is_trimmed_and_collapsed(repos: Repositories) -> None:
    category_id = repos.categories.create("  Motion   Graphics  ", ["aep"])
    category = repos.categories.get(category_id)
    assert category is not None
    assert category.name == "Motion Graphics"


@pytest.mark.parametrize(
    "name, code",
    [
        ("", "name_empty"),
        ("   ", "name_empty"),
        ("x" * 41, "name_too_long"),
        ("a/b", "name_invalid_chars"),
        ("a:b", "name_invalid_chars"),
        ("a?b", "name_invalid_chars"),
        ("a|b", "name_invalid_chars"),
        ("Photos.", "name_invalid_chars"),
        ("CON", "name_reserved"),
        ("lpt1", "name_reserved"),
        ("images", "name_duplicate"),
        ("  Images ", "name_duplicate"),
    ],
)
def test_bad_names_are_rejected(
    repos: Repositories, name: str, code: str
) -> None:
    with pytest.raises(CategoryError) as excinfo:
        repos.categories.create(name, [])
    assert excinfo.value.code == code


def test_a_persian_name_is_accepted(repos: Repositories) -> None:
    category_id = repos.categories.create("طراحی", ["psd"])
    category = repos.categories.get(category_id)
    assert category is not None
    assert category.name == "طراحی"


# -- creation -------------------------------------------------------------
def test_a_new_category_is_appended_and_not_builtin(repos: Repositories) -> None:
    builtin = repos.categories.list_all()
    category_id = repos.categories.create("Design", ["psd"])

    categories = repos.categories.list_all()
    assert len(categories) == len(builtin) + 1
    created = categories[-1]
    assert created.id == category_id == "design"
    assert created.builtin is False
    assert created.enabled is True
    assert created.sort_order == max(c.sort_order for c in builtin) + 1


def test_extensions_are_normalised(repos: Repositories) -> None:
    category_id = repos.categories.create("Design", [".PSD", "*.ai", " sketch "])
    category = repos.categories.get(category_id)
    assert category is not None
    assert category.extensions == ("psd", "ai", "sketch")


def test_ids_stay_unique_when_the_slug_collides(repos: Repositories) -> None:
    # Two different names that reduce to the same slug.
    first = repos.categories.create("De sign", [])
    second = repos.categories.create("De-sign", [])
    assert first == "de-sign"
    assert second == "de-sign-2"


def test_a_name_with_no_latin_characters_still_gets_an_id(repos: Repositories) -> None:
    first = repos.categories.create("طراحی", [])
    second = repos.categories.create("موسیقی", [])
    assert first.startswith("cat-")
    assert second.startswith("cat-")
    assert first != second


# -- rename and delete ----------------------------------------------------
def test_a_user_category_can_be_renamed(repos: Repositories) -> None:
    category_id = repos.categories.create("Design", [])
    repos.categories.rename(category_id, "Creative")
    category = repos.categories.get(category_id)
    assert category is not None
    assert category.name == "Creative"


def test_builtin_categories_cannot_be_renamed(repos: Repositories) -> None:
    with pytest.raises(CategoryError) as excinfo:
        repos.categories.rename("images", "Pictures")
    assert excinfo.value.code == "builtin_protected"


def test_renaming_to_an_existing_name_is_refused(repos: Repositories) -> None:
    category_id = repos.categories.create("Design", [])
    with pytest.raises(CategoryError) as excinfo:
        repos.categories.rename(category_id, "Images")
    assert excinfo.value.code == "name_duplicate"


def test_a_user_category_can_be_deleted(repos: Repositories) -> None:
    category_id = repos.categories.create("Design", [])
    repos.categories.delete(category_id)
    assert repos.categories.get(category_id) is None


def test_builtin_categories_cannot_be_deleted(repos: Repositories) -> None:
    for category_id in ("images", "other"):
        with pytest.raises(CategoryError) as excinfo:
            repos.categories.delete(category_id)
        assert excinfo.value.code == "builtin_protected"


def test_deleting_an_unknown_category_is_refused(repos: Repositories) -> None:
    with pytest.raises(CategoryError) as excinfo:
        repos.categories.delete("nope")
    assert excinfo.value.code == "not_found"


# -- the classifier follows ----------------------------------------------
def test_a_new_category_receives_its_own_extension(
    organizer: Organizer, configured, repos: Repositories, downloads_dir
) -> None:
    repos.categories.create("Design", ["psd"])
    organizer.invalidate_classifier()

    source = make_file(downloads_dir, "mockup.psd", b"x")
    result = organizer.organize(request(source))

    assert result.status == "organized"
    assert result.category == "design"
    assert "Design" in result.final_path


def test_an_extension_already_claimed_stays_with_the_first_category(
    organizer: Organizer, configured, repos: Repositories, downloads_dir
) -> None:
    """New categories are appended, so a built-in keeps the extensions it owns."""
    repos.categories.create("Design", ["png"])
    organizer.invalidate_classifier()

    source = make_file(downloads_dir, "shot.png", b"x")
    assert organizer.organize(request(source)).category == "images"


def test_extension_owners_reports_the_winner(repos: Repositories) -> None:
    owners = repos.categories.extension_owners()
    assert owners["png"] == "Images"
    assert owners["pdf"] == "Documents"

    repos.categories.create("Design", ["png", "psd"])
    owners = repos.categories.extension_owners()
    assert owners["png"] == "Images"
    assert owners["psd"] == "Design"


def test_extension_owners_can_ignore_one_category(repos: Repositories) -> None:
    owners = repos.categories.extension_owners(exclude_id="images")
    assert "png" not in owners
