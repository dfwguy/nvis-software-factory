# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.
"""The repository endpoints, which are where a URL from a user first enters the system.

Author: Rafael M. Koike & Cursor Agent ("Ada")

A repository URL is the most dangerous input this application accepts: it is a network
destination that a server-side process will connect to. Most of what follows is about the
boundary rather than the CRUD -- that a refused URL is refused here rather than several minutes
later inside a clone, and that credentials embedded in a URL do not come back out in a response.
"""

from __future__ import annotations

import uuid


def _unique_url(host="gitlab.example.com"):
    """A fresh URL per test.

    The app fixture is session-scoped, so its database persists across this file. Reusing a URL
    would silently exercise the upsert path in a test that meant to exercise the insert path.
    """
    return f"https://{host}/nvis/example-{uuid.uuid4().hex[:10]}.git"


def test_adding_a_repository_returns_the_parsed_record(app_client):
    response = app_client.post("/api/repositories/", json={"url": _unique_url()})

    assert response.status_code == 200
    record = response.get_json()["repository"]
    assert record["forge"] == "gitlab"
    assert record["namespace"] == "nvis"
    assert record["name"].startswith("example-")
    assert record["added_by"], "the record must say who added it"


def test_a_missing_url_is_a_400_naming_the_field(app_client):
    """Named, because a client cannot fix "invalid request"."""
    response = app_client.post("/api/repositories/", json={})

    assert response.status_code == 400
    body = response.get_json()
    assert body["reason"] == "missing-fields"
    assert "url" in body["error"]


def test_a_whitespace_url_is_refused(app_client):
    """422 rather than 400: it is present, it is just not a URL. The distinction matters to a
    client deciding whether to re-prompt for the field or report it as invalid."""
    assert app_client.post("/api/repositories/", json={"url": "   "}).status_code == 422


def test_a_url_pointing_at_the_loopback_interface_is_refused(app_client):
    """SSRF, refused at the front door.

    This process can reach the host's network and anything the container can route to. Left
    unchecked, "assess this repository" is a request to make an arbitrary outbound connection
    from inside the perimeter.
    """
    response = app_client.post("/api/repositories/", json={"url": "https://127.0.0.1/x/y.git"})

    assert response.status_code == 422
    assert response.get_json()["reason"] == "url-refused"


def test_a_url_pointing_at_the_metadata_service_is_refused(app_client):
    """The specific target that turns SSRF into cloud credentials."""
    response = app_client.post(
        "/api/repositories/", json={"url": "https://169.254.169.254/latest/meta-data"}
    )

    assert response.status_code == 422


def test_a_token_in_a_url_is_stripped_and_never_stored(app_client):
    """A URL with a credential in it gets pasted more often than anyone would like.

    The URL is accepted with the credential removed rather than refused, because the user's intent
    is unambiguous and a refusal tends to be met with a second paste. What must not happen is the
    token being persisted: from the row it would reach the audit trail, every later API response,
    and the assessment report.
    """
    token = "glpat-AAAAAAAAAAAAAAAAAAAA"
    response = app_client.post(
        "/api/repositories/",
        json={"url": f"https://oauth2:{token}@gitlab.example.com/nvis/tokentest.git"},
    )

    assert response.status_code == 200
    assert token not in response.get_data(as_text=True), "the response echoed the credential back"

    stored = response.get_json()["repository"]
    assert "@" not in stored["url"], f"credentials survived into the stored URL: {stored['url']}"

    # And it must still be absent when the record is read back, not merely filtered on the way out.
    reread = app_client.get(f"/api/repositories/{stored['id']}").get_data(as_text=True)
    assert token not in reread


def test_a_non_http_scheme_is_refused(app_client):
    """file:// would make the clone read the container's own filesystem."""
    for url in ("file:///etc/passwd", "ftp://example.com/x.git", "git@github.com:a/b.git"):
        assert app_client.post("/api/repositories/", json={"url": url}).status_code == 422, url


def test_adding_the_same_repository_twice_does_not_duplicate_it(app_client):
    """Upsert, because two rows for one repository split its assessment history in the UI."""
    url = _unique_url()

    first = app_client.post("/api/repositories/", json={"url": url}).get_json()["repository"]
    second = app_client.post("/api/repositories/", json={"url": url}).get_json()["repository"]

    assert first["id"] == second["id"]


def test_equivalent_spellings_of_a_url_are_one_repository(app_client):
    """gitlab.example.com/g/p and .../g/p.git and a trailing slash are the same thing to a human
    and would be three rows without canonicalization."""
    suffix = uuid.uuid4().hex[:10]
    base = f"https://gitlab.example.com/nvis/example-{suffix}"

    ids = {
        app_client.post("/api/repositories/", json={"url": spelling})
        .get_json()["repository"]["id"]
        for spelling in (base, f"{base}.git", f"{base}/")
    }

    assert len(ids) == 1, f"three spellings produced {len(ids)} repositories"


def test_listing_paginates(app_client):
    for _ in range(3):
        app_client.post("/api/repositories/", json={"url": _unique_url()})

    body = app_client.get("/api/repositories/?limit=2&offset=0").get_json()

    assert len(body["repositories"]) <= 2
    assert body["limit"] == 2
    assert body["total"] >= 3, "total counts the whole set, not the page"


def test_an_absurd_limit_is_capped(app_client):
    """Otherwise limit=1000000 is a way to ask the server to build one enormous response."""
    assert app_client.get("/api/repositories/?limit=999999").get_json()["limit"] <= 200


def test_a_nonsense_limit_does_not_500(app_client):
    assert app_client.get("/api/repositories/?limit=abc").status_code == 200


def test_fetching_one_repository_includes_its_assessments(app_client):
    created = app_client.post(
        "/api/repositories/", json={"url": _unique_url()}
    ).get_json()["repository"]

    body = app_client.get(f"/api/repositories/{created['id']}").get_json()

    assert body["repository"]["id"] == created["id"]
    assert body["assessments"] == []


def test_an_unknown_repository_is_a_404(app_client):
    response = app_client.get(f"/api/repositories/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.get_json()["reason"] == "not-found"


def test_notes_are_kept(app_client):
    response = app_client.post(
        "/api/repositories/", json={"url": _unique_url(), "notes": "owned by the OVA team"}
    )

    assert response.get_json()["repository"]["notes"] == "owned by the OVA team"


def test_an_anonymous_caller_cannot_list_or_add(anonymous_client):
    """The endpoints are boring; who can reach them is not."""
    assert anonymous_client.get("/api/repositories/").status_code in {401, 403}
    assert anonymous_client.post(
        "/api/repositories/", json={"url": _unique_url()}
    ).status_code in {401, 403}
