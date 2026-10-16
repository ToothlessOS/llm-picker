"""No request may ever trigger an external call.

This is the single most important test in the suite. The project's central
promise is that the frontend reads a local database and nothing else: the two
upstream sources are fetched twice a day by Celery, and a page load must never
depend on -- or wait for -- artificialanalysis.ai or the Hugging Face Hub. That
promise is what makes the API fast, free, and able to answer while either source
is down.

The enforcement is deliberately *hostile*: every outbound seam is replaced with
something that raises, so a call is not slow or logged but fatal. And the
assertion is not merely "200 OK" -- each response is also checked to be
*correct*, because an endpoint that returned an empty 200 by catching the
exception would pass a status-code check while being just as broken.

Note what is *not* patched: `leaderboard.api.views` imports no client, no
transport and no `datasets`. A request cannot reach the network because there is
no code path from a view to one. These tests exist to keep it that way -- a
future import of a client into a view would fail here rather than in production.
"""

from __future__ import annotations

import socket

import pytest

from leaderboard.tests.test_api import BASE, seed, seed_discussions


@pytest.fixture
def sealed(monkeypatch, db):
    """Make every outbound path raise, and fail the test if one is even touched.

    Depends on `db` so the test database exists *before* the seal goes on: the
    socket patch is broad enough that it should not be live while any fixture is
    still doing its own work.

    Three layers, from the general to the specific:

    * `socket.socket.connect` -- the narrowest waist every networking library in
      the Python ecosystem passes through. `requests`, `urllib3`, `huggingface_hub`
      and `datasets` all end up here, so this one patch covers libraries that do
      not exist yet.
    * the AA transport, which is the seam the client was injected through, so the
      failure message names the offending code rather than a socket call.
    * the LMArena loader, which is the only thing in the project that imports
      `datasets`, and it does so lazily and inside this callable.
    * the Hacker News transport factory, which exists for this reason -- a named
      function rather than an inline `RequestsTransport()`, so this fixture can
      replace one seam and see a failure naming our code.
    """

    def explode(*args, **kwargs):
        raise AssertionError(
            "an API request attempted an external call -- the read path must "
            "never leave the database"
        )

    import leaderboard.clients.hackernews as hackernews
    import leaderboard.clients.http as http
    import leaderboard.clients.lmarena as lmarena

    monkeypatch.setattr(socket.socket, "connect", explode)
    monkeypatch.setattr(http.RequestsTransport, "get", explode, raising=False)
    monkeypatch.setattr(lmarena, "_default_loader", explode)
    monkeypatch.setattr(hackernews, "_default_transport", explode)
    return explode


ENDPOINTS = [
    "/overview/",
    "/categories/",
    "/categories/agent/",
    "/categories/document/",
    "/categories/webdev/",
    "/artificial-analysis/",
    "/artificial-analysis/?retained=false",
    "/models/claude-opus-5-high/",
    "/metadata/",
    "/unmatched/",
    "/discussions/",
    "/discussions/?entity=anthropic",
    "/discussions/?search=a",
    "/discussions/entities/",
    "/discussions/{hn_id}/",
]


class TestNoNetwork:
    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_every_endpoint_answers_with_the_network_sealed(self, client, sealed, path):
        seed()
        discussions = seed_discussions()
        path = path.format(hn_id=discussions["hn_id"])

        response = client.get(f"{BASE}{path}")

        assert response.status_code == 200, f"{path} -> {response.status_code}"

    @pytest.mark.parametrize("path", ENDPOINTS)
    def test_the_answer_is_real_data_not_an_empty_200(self, client, sealed, path):
        """The stronger form: a handler that swallowed the exception and returned
        an empty payload would satisfy a status-code check while being useless."""
        seed()
        discussions = seed_discussions()
        path = path.format(hn_id=discussions["hn_id"])

        body = client.get(f"{BASE}{path}").json()

        assert body, f"{path} returned an empty body"

    def test_the_discussion_views_reach_no_matcher(self, client, sealed):
        """The same seal, against a *populated* bank.

        An empty bank answers the discussion endpoints without ever joining a tag
        or reading a comment, so the parametrized cases above would pass even if a
        view matched entities at request time. A seeded bank exercises the join,
        which is where an eager inference would live.
        """
        discussions = seed_discussions()

        body = client.get(f"{BASE}/discussions/{discussions['hn_id']}/").json()

        assert body["comments"]
        assert body["thread"]["entities"]

    def test_the_configuration_report_does_not_probe_the_source(self, client, sealed):
        """`configured` is read from the environment.

        The tempting implementation -- "is the key valid?" -- would spend one of
        a hundred shared daily requests on every page load, and would make the
        metadata endpoint fail whenever the upstream was down. It must be a
        settings lookup.
        """
        body = client.get(f"{BASE}/metadata/").json()

        assert body["sources"]["artificial_analysis"]["configured"] is True

    def test_the_read_path_imports_no_client_or_service(self):
        """The structural guarantee, asserted directly.

        Behavioural tests can only prove the calls that *would have* happened
        along the paths they exercise. This one closes the whole category: a
        future `from ..clients import ...`, or a `selectors` helper that reaches
        for `services.refresh` to ask a question, fails here at review time --
        rather than the first time an unlucky branch is taken in production.

        `datasets` is called out separately because the cost is different in
        kind: importing it does not merely risk a call, it makes every web worker
        pay a multi-second import to serve requests that never needed it.
        """
        import leaderboard.api.discussion_selectors as discussion_selectors
        import leaderboard.api.discussion_serializers as discussion_serializers
        import leaderboard.api.discussion_views as discussion_views
        import leaderboard.api.errors as errors
        import leaderboard.api.pagination as pagination
        import leaderboard.api.params as params
        import leaderboard.api.selectors as selectors
        import leaderboard.api.serializers as serializers
        import leaderboard.api.throttling as throttling
        import leaderboard.api.urls as urls
        import leaderboard.api.views as views

        forbidden = (
            "clients.http",
            "clients.artificial_analysis",
            "clients.lmarena",
            "clients.hackernews",
            "services.refresh",
            "services.discussions",
            # The ingest-side matcher and sanitizer. A tag is a *stored row*, so
            # matching at request time would be a second source of truth for what
            # the tags say as well as a per-request cost.
            "hn_matching",
            "hn_text",
            "locking",
            "import datasets",
        )
        for module in (
            views,
            selectors,
            serializers,
            params,
            errors,
            pagination,
            throttling,
            urls,
            discussion_views,
            discussion_selectors,
            discussion_serializers,
        ):
            with open(module.__file__) as handle:
                text = handle.read()
            for needle in forbidden:
                assert needle not in text, (
                    f"{module.__name__} references {needle!r}; the read path must "
                    "not be one import away from an external call or from the "
                    "refresh machinery"
                )
