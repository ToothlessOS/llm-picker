"""Read-only HTTP surface, versioned under `/api/v1/leaderboard/`.

Layering is strictly one-way: `views -> selectors -> models`. Nothing in this
package writes, and nothing in it imports a client -- so no request can trigger
an external call, which is the property `tests/test_api_no_network.py` pins
down.
"""
