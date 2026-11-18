"""The Steam client, tested without going online: requests is replaced by a fake."""

from unittest.mock import Mock

import pytest
import requests

import api
import config
from conftest import FAKE_KEY


def steam_says(monkeypatch, payload=None, status=200, error=None):
    """Make the next Steam call return this payload (or raise this error)."""
    reply = Mock(status_code=status, ok=status < 400)
    reply.json.return_value = {"response": payload or {}}
    get = Mock(return_value=reply, side_effect=error)
    monkeypatch.setattr(api._session, "get", get)
    return get


# --- working out who the user means ---


def test_a_plain_id_needs_no_lookup(monkeypatch):
    get = steam_says(monkeypatch)
    assert api.resolve_steam_id(" 76561197960287930 ") == "76561197960287930"
    get.assert_not_called()


def test_profile_link_with_an_id(monkeypatch):
    get = steam_says(monkeypatch)
    link = "https://steamcommunity.com/profiles/76561197960287930/games/?tab=all"
    assert api.resolve_steam_id(link) == "76561197960287930"
    get.assert_not_called()


def test_custom_name_is_looked_up_once(monkeypatch):
    get = steam_says(monkeypatch, {"success": 1, "steamid": "76561197960287930"})
    assert api.resolve_steam_id("https://steamcommunity.com/id/GabeLoganNewell/") == "76561197960287930"
    assert api.resolve_steam_id("gabelogannewell") == "76561197960287930"
    assert get.call_count == 1  # the second answer came from the cache


def test_unknown_custom_name(monkeypatch):
    steam_says(monkeypatch, {"success": 42, "message": "No match"})
    with pytest.raises(api.ProfileNotFound) as caught:
        api.resolve_steam_id("nobody-here")
    assert "nobody-here" in caught.value.message


def test_gibberish_is_rejected_without_asking_steam(monkeypatch):
    get = steam_says(monkeypatch)
    with pytest.raises(api.ProfileNotFound):
        api.resolve_steam_id("not a real name!!")
    get.assert_not_called()


def test_empty_input():
    with pytest.raises(api.EmptyQuery):
        api.resolve_steam_id("   ")


# --- things that go wrong ---


def test_no_key_configured(monkeypatch):
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    with pytest.raises(api.MissingKey):
        api.get_player("76561197960287930")


@pytest.mark.parametrize(
    "status, expected",
    [(401, api.BadKey), (403, api.BadKey), (429, api.RateLimited), (500, api.SteamDown), (503, api.SteamDown)],
)
def test_bad_status_codes(monkeypatch, status, expected):
    steam_says(monkeypatch, status=status)
    with pytest.raises(expected):
        api.get_player("76561197960287930")


@pytest.mark.parametrize(
    "error, expected",
    [
        (requests.Timeout("slow"), api.SteamTimeout),
        (requests.ConnectionError("no wifi"), api.NoConnection),
        (requests.TooManyRedirects("loop"), api.SteamError),
    ],
)
def test_network_trouble(monkeypatch, error, expected):
    steam_says(monkeypatch, error=error)
    with pytest.raises(expected):
        api.get_player("76561197960287930")


def test_errors_never_carry_the_key(monkeypatch):
    leaky = requests.ConnectionError(f"GET https://api.steampowered.com/?key={FAKE_KEY} failed")
    steam_says(monkeypatch, error=leaky)
    with pytest.raises(api.SteamError) as caught:
        api.get_player("76561197960287930")
    assert FAKE_KEY not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_reply_that_is_not_json(monkeypatch):
    get = steam_says(monkeypatch)
    get.return_value.json.side_effect = ValueError("not json")
    with pytest.raises(api.SteamDown):
        api.get_player("76561197960287930")


# --- reading a player ---


def test_get_player_tidies_the_fields(monkeypatch):
    steam_says(
        monkeypatch,
        {
            "players": [
                {
                    "steamid": "76561197960287930",
                    "personaname": "Rabscuttle",
                    "avatarfull": "https://avatars.steamstatic.com/abc_full.jpg",
                    "profileurl": "https://steamcommunity.com/id/gabelogannewell/",
                    "personastate": 3,
                    "communityvisibilitystate": 3,
                    "timecreated": 1063407589,
                }
            ]
        },
    )
    player = api.get_player("76561197960287930")
    assert player["name"] == "Rabscuttle"
    assert player["status"] == "Away"
    assert player["is_public"] is True
    assert player["created"] == 1063407589


def test_get_player_that_does_not_exist(monkeypatch):
    steam_says(monkeypatch, {"players": []})
    with pytest.raises(api.ProfileNotFound):
        api.get_player("76561197960287930")


def test_level_is_optional(monkeypatch):
    steam_says(monkeypatch, status=500)
    assert api.get_level("76561197960287930") is None


def test_owned_games_are_renamed_to_our_fields(monkeypatch):
    steam_says(
        monkeypatch,
        {
            "game_count": 2,
            "games": [
                {
                    "appid": 730,
                    "name": "Counter-Strike 2",
                    "playtime_forever": 48720,
                    "playtime_2weeks": 372,
                    "img_icon_url": "8dbc71957312bbd3baea65848b545be9eae2a355",
                    "rtime_last_played": 1731800000,
                    "has_community_visible_stats": True,
                },
                {"appid": 620, "name": "Portal 2", "playtime_forever": 0, "img_icon_url": "", "rtime_last_played": 0},
            ],
        },
    )
    counter_strike, portal = api.get_owned_games("76561197960287930")
    assert counter_strike == {
        "app_id": 730,
        "name": "Counter-Strike 2",
        "icon": "8dbc71957312bbd3baea65848b545be9eae2a355",
        "minutes": 48720,
        "minutes_2weeks": 372,
        "last_played": 1731800000,
        "has_stats": True,
    }
    assert portal["minutes_2weeks"] == 0 and portal["last_played"] is None and portal["icon"] is None
    assert portal["has_stats"] is False  # Steam leaves the flag out instead of sending false


def test_private_library(monkeypatch):
    steam_says(monkeypatch, {})
    with pytest.raises(api.PrivateProfile):
        api.get_owned_games("76561197960287930")


def test_empty_library_is_not_an_error(monkeypatch):
    steam_says(monkeypatch, {"game_count": 0})
    assert api.get_owned_games("76561197960287930") == []


# --- checking a key ---


def test_key_shape():
    assert api.looks_like_key(FAKE_KEY)
    assert not api.looks_like_key("too-short")


def test_key_works_asks_steam(monkeypatch):
    steam_says(monkeypatch, {"players": []})
    assert api.key_works(FAKE_KEY) is True
    steam_says(monkeypatch, status=403)
    assert api.key_works(FAKE_KEY) is False


# --- achievements ---


def steam_replies(monkeypatch, body, status=200):
    """Like steam_says, for the endpoints that don't wrap their answer in "response"."""
    reply = Mock(status_code=status, ok=status < 400)
    reply.json.return_value = body
    get = Mock(return_value=reply)
    monkeypatch.setattr(api._session, "get", get)
    return get


def test_achievements_are_renamed_to_our_fields(monkeypatch):
    get = steam_replies(monkeypatch, {"playerstats": {"steamID": "76561197960287930", "gameName": "Hades", "success": True,
        "achievements": [
            {"apiname": "ESCAPE", "achieved": 1, "unlocktime": 1731800000, "name": "Is There No Escape?", "description": "Escape."},
            {"apiname": "OLD_ONE", "achieved": 1, "unlocktime": 0, "name": "Before Records"},
            {"apiname": "LOCKED", "achieved": 0, "unlocktime": 0},
        ]}})
    escape, old, locked = api.get_achievements("76561197960287930", 1145360)
    assert escape == {"api_name": "ESCAPE", "name": "Is There No Escape?", "description": "Escape.",
                      "achieved": True, "unlocked_at": 1731800000}
    assert old["achieved"] and old["unlocked_at"] is None  # unlocked, but Steam doesn't know when
    assert locked == {"api_name": "LOCKED", "name": "LOCKED", "description": "", "achieved": False, "unlocked_at": None}
    assert get.call_args.kwargs["params"]["appid"] == 1145360


def test_a_game_without_achievements_is_an_empty_list(monkeypatch):
    steam_replies(monkeypatch, {"playerstats": {"error": "Requested app has no stats", "success": False}}, status=400)
    assert api.get_achievements("76561197960287930", 220) == []


def test_private_achievements_are_not_mistaken_for_a_bad_key(monkeypatch):
    steam_replies(monkeypatch, {"playerstats": {"error": "Profile is not public", "success": False}}, status=403)
    with pytest.raises(api.PrivateAchievements):
        api.get_achievements("76561197960287930", 220)


def test_a_real_bad_key_still_says_so_on_the_achievement_call(monkeypatch):
    steam_replies(monkeypatch, "<html>Forbidden</html>", status=403)
    with pytest.raises(api.BadKey):
        api.get_achievements("76561197960287930", 220)


def test_achievement_icons_come_from_the_schema(monkeypatch):
    steam_replies(monkeypatch, {"game": {"gameName": "Hades", "availableGameStats": {"achievements": [
        {"name": "ESCAPE", "displayName": "Is There No Escape?", "hidden": 0,
         "icon": "https://cdn.fastly.steamstatic.com/steamcommunity/public/images/apps/1145360/escape.jpg"},
        {"name": "NO_ICON", "displayName": "?"},
    ]}}})
    assert api.get_achievement_icons(1145360) == {
        "ESCAPE": "https://cdn.fastly.steamstatic.com/steamcommunity/public/images/apps/1145360/escape.jpg",
    }


def test_global_percentages_accept_numbers_and_text(monkeypatch):
    steam_replies(monkeypatch, {"achievementpercentages": {"achievements": [
        {"name": "ESCAPE", "percent": 41.5}, {"name": "RARE", "percent": "0.8"}, {"name": "BROKEN", "percent": None},
    ]}})
    assert api.get_global_percentages(1145360) == {"ESCAPE": 41.5, "RARE": 0.8}
