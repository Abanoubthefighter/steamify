"""The routes, exercised through Flask's test client. Steam itself is always faked."""

import io
import json
from datetime import date

import pytest

import api
import app as app_module
import config
import demo
import storage
import sync
from conftest import FAKE_KEY, PNG, WEBP, make_achievements, make_game, make_profile

ME = "76561198000000001"
FRIEND = "76561198000000002"
DEMO_PAGE = f"/player/{demo.PLAYER_ID}"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(demo, "STEP_DELAY", 0)
    app_module.prepare()
    return app_module.app.test_client()


@pytest.fixture
def steam(monkeypatch):
    """A pretend Steam with two players. FRIEND's library is private."""

    def owned_games(steam_id):
        if steam_id == FRIEND:
            raise api.PrivateProfile()
        return [make_game(730, "Counter-Strike 2", hours=10), make_game(620, "Portal 2")]

    monkeypatch.setattr(api, "resolve_steam_id", lambda text: {"me": ME, "friend": FRIEND}[text])
    monkeypatch.setattr(api, "get_player", lambda steam_id: make_profile(steam_id, name=f"player {steam_id[-1]}"))
    monkeypatch.setattr(api, "get_level", lambda steam_id: 7)
    monkeypatch.setattr(api, "get_owned_games", owned_games)
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: [])  # these games have none


def timing_out(steam_id, app_id):
    """A get_achievements that never gets an answer, so no game ends up checked."""
    raise api.SteamTimeout()


def scan(client, **form):
    """Post to /scan and return the streamed lines as dicts."""
    reply = client.post("/scan", data=form)
    assert reply.status_code == 200
    return [json.loads(line) for line in reply.text.splitlines()]


# --- pages ---


def test_first_run_opens_the_demo_player(client):
    reply = client.get("/")
    assert reply.status_code == 302
    assert reply.headers["Location"] == f"{DEMO_PAGE}?vs={demo.FRIEND_ID}"


def test_dashboard_has_every_window(client):
    page = client.get(f"{DEMO_PAGE}?vs={demo.FRIEND_ID}").text
    for title in ("scan.exe", "profile.exe", "warning.exe", "sync.exe", "playtime_history.wmv",
                  "C:\\top_games", "versus.exe", "library.exe", "sort.exe"):
        assert title in page, f"{title} is missing from the dashboard"
    assert "player_one" in page and "player_two" in page
    assert 'id="tracks-data"' in page


def test_about_box_shows_the_version(client):
    page = client.get(DEMO_PAGE).text
    assert f"Version {config.APP_VERSION}" in page


def test_demo_views_are_not_remembered(client):
    client.get(DEMO_PAGE)
    assert storage.get_setting("last_player") is None


def test_unknown_player_gets_the_themed_404(client):
    reply = client.get("/player/nobody")
    assert reply.status_code == 404
    assert "error.exe" in reply.text and "File not found" in reply.text


def test_names_from_steam_are_escaped(client):
    storage.save_snapshot(make_profile(ME, name="<script>alert(1)</script>"), [make_game(1, "<b>Bold</b> Game", hours=3)])
    page = client.get(f"/player/{ME}").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<b>Bold</b>" not in page


def test_security_headers_are_on_every_reply(client):
    headers = client.get(DEMO_PAGE).headers
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"


# --- library.exe and the game popup ---


def test_library_rows_can_be_sorted_searched_and_expanded(client):
    first_page = client.get(f"{DEMO_PAGE}/library").text
    assert first_page.count('class="row"') == config.LIBRARY_PAGE_SIZE
    assert "Show all" in first_page

    everything = client.get(f"{DEMO_PAGE}/library?all=1").text
    assert everything.count('class="row"') == len(demo.FAVOURITES) + len(demo.SHELF)

    never = client.get(f"{DEMO_PAGE}/library?sort=never").text
    assert "Counter-Strike 2" not in never

    search = client.get(f"{DEMO_PAGE}/library?q=elden").text
    assert search.count('class="row"') == 1 and "Elden Ring" in search

    assert "Nothing called" in client.get(f"{DEMO_PAGE}/library?q=zzzz").text


def test_game_card(client):
    game = storage.get_library(demo.PLAYER_ID)[0]
    card = client.get(f"{DEMO_PAGE}/game/{game['app_id']}").text
    assert game["name"] in card
    assert "Store page" not in card  # demo games have no real store page
    assert client.get(f"{DEMO_PAGE}/game/424242").status_code == 404


def test_real_games_link_to_their_art_and_store_page(client):
    storage.save_snapshot(make_profile(ME), [{**make_game(730, "Counter-Strike 2", hours=10), "icon": "abc123"}])
    card = client.get(f"/player/{ME}/game/730").text
    assert "store.steampowered.com/app/730" in card and "/apps/730/header.jpg" in card
    assert "/apps/730/abc123.jpg" in client.get(f"/player/{ME}/library").text


# --- scanning ---


def test_scan_streams_progress_then_points_at_the_dashboard(client, steam):
    events = scan(client, player="me")
    steps = len(sync.STEPS)
    # A long step sends extra lines ("Checking achievements 12/40") with the same step number.
    assert list(dict.fromkeys(event["step"] for event in events[:-1])) == list(range(1, steps + 1))
    assert all(event["steps"] == steps for event in events[:-1])
    assert events[-1] == {"done": True, "gained": 0, "url": f"/player/{ME}"}

    assert client.get(f"/player/{ME}").status_code == 200
    assert client.get("/").headers["Location"] == f"/player/{ME}"  # remembered for next launch


def test_scan_without_a_key_explains_what_is_missing(client, monkeypatch):
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    events = scan(client, player="76561197960287930")
    assert events[-1]["error"]["code"] == "missing-key"
    assert events[-1]["url"] is None


def test_scan_with_nothing_typed(client):
    assert scan(client, player="  ")[-1]["error"]["code"] == "empty"


def test_a_private_friend_does_not_block_the_players_own_dashboard(client, steam):
    events = scan(client, player="me", friend="friend")
    first_friend_step = next(event for event in events if event.get("step") == len(sync.STEPS) + 1)
    assert first_friend_step["label"].startswith("Friend: ")
    assert events[-1]["error"]["code"] == "private"
    assert events[-1]["url"] == f"/player/{ME}"


def test_the_demo_player_can_be_synced_without_a_key(client, monkeypatch):
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    events = scan(client, player=demo.PLAYER_ID, friend=demo.FRIEND_ID, force="1")
    assert len(events) == 2 * len(sync.STEPS) + 1  # two players, every step each, then the result
    assert events[-1]["url"] == f"{DEMO_PAGE}?vs={demo.FRIEND_ID}"


def test_an_unexpected_crash_still_ends_the_stream_politely(client, steam, monkeypatch):
    monkeypatch.setattr(storage, "save_snapshot", lambda *args, **kwargs: 1 / 0)
    assert scan(client, player="me")[-1]["error"]["code"] == "steam-error"


# --- saving an API key ---


def test_key_must_look_like_a_key(client):
    reply = client.post("/settings/key", data={"key": "nope"})
    assert reply.status_code == 400 and "32 letters" in reply.json["message"]


def test_key_is_checked_with_steam_before_saving(client, monkeypatch):
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    monkeypatch.setattr(api, "key_works", lambda key: False)
    reply = client.post("/settings/key", data={"key": FAKE_KEY})
    assert reply.status_code == 502 and reply.json["code"] == "bad-key"
    assert config.STEAM_API_KEY == "" and not config.ENV_FILE.exists()


def test_a_working_key_is_written_to_the_env_file(client, monkeypatch):
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    monkeypatch.setattr(api, "key_works", lambda key: True)
    reply = client.post("/settings/key", data={"key": FAKE_KEY})
    assert reply.json == {"ok": True}
    assert config.STEAM_API_KEY == FAKE_KEY
    assert FAKE_KEY in config.ENV_FILE.read_text()


def test_the_key_never_appears_in_a_page(client):
    assert FAKE_KEY not in client.get(DEMO_PAGE).text


# --- only our own window may talk to the server ---


def test_posts_from_other_websites_are_refused(client):
    reply = client.post("/scan", data={"player": "me"}, headers={"Origin": "https://evil.example"})
    assert reply.status_code == 403


def test_requests_for_another_host_are_refused(client):
    assert client.get(DEMO_PAGE, headers={"Host": "evil.example"}).status_code == 403


# --- Wallpaper ----------------------------------------------------------------


def test_every_page_starts_with_the_default_wallpaper(client):
    assert f'class="wallpaper pattern--{config.DEFAULT_WALLPAPER}"' in client.get(DEMO_PAGE).text
    assert f'class="wallpaper pattern--{config.DEFAULT_WALLPAPER}"' in client.get("/player/nobody").text


def test_picking_a_pattern_changes_the_page(client):
    reply = client.post("/wallpaper", data={"pattern": "checker", "dim": "55"})
    assert reply.status_code == 200
    assert reply.json == {"pattern": "checker", "dim": 55, "picture": None, "picture_url": None, "pictures": []}
    page = client.get(DEMO_PAGE).text
    assert 'class="wallpaper pattern--checker"' in page
    assert "--wallpaper-dim: 0.55" in page


def test_an_unknown_pattern_gets_a_popup_message(client):
    reply = client.post("/wallpaper", data={"pattern": "rainbow"})
    assert reply.status_code == 400
    assert reply.json["title"] and reply.json["message"]


def test_reset_brings_back_the_default(client):
    client.post("/wallpaper", data={"pattern": "plain"})
    assert client.post("/wallpaper/reset").json["pattern"] == config.DEFAULT_WALLPAPER


def test_only_pictures_in_the_list_are_served(client):
    assert client.get("/wallpaper/picture/wallpaper-nope.png").status_code == 404
    assert client.get("/wallpaper/picture/..%2Ftest.db").status_code == 404


def test_wallpaper_exe_is_in_the_start_menu_with_every_pattern(client):
    page = client.get(DEMO_PAGE).text
    assert 'data-menu="wallpaper"' in page
    assert 'data-title="wallpaper.exe"' in page
    for key, label in config.WALLPAPER_PATTERNS.items():
        assert f'value="{key}"' in page and label in page


def upload(client, data, filename="photo.png"):
    return client.post("/wallpaper/picture", data={"picture": (io.BytesIO(data), filename)},
                       content_type="multipart/form-data")


def test_an_imported_picture_is_served_and_drawn_on_every_page(client):
    reply = upload(client, PNG)
    assert reply.status_code == 200
    url = reply.json["picture_url"]
    assert reply.json["pattern"] == "picture" and url.startswith("/wallpaper/picture/wallpaper-")

    picture = client.get(url)
    assert picture.status_code == 200
    assert picture.mimetype == "image/png" and picture.data == PNG

    page = client.get(DEMO_PAGE).text
    assert 'class="wallpaper pattern--picture"' in page and f'src="{url}"' in page


def test_a_webp_picture_gets_the_right_type(client):
    url = upload(client, WEBP, "photo.webp").json["picture_url"]
    assert client.get(url).mimetype == "image/webp"


def test_a_file_that_isnt_a_picture_gets_a_popup_message(client):
    reply = upload(client, b"not a picture at all", "sneaky.png")
    assert reply.status_code == 400 and reply.json["title"]


def test_importing_with_no_file_gets_a_popup_message(client):
    reply = client.post("/wallpaper/picture", data={}, content_type="multipart/form-data")
    assert reply.status_code == 400 and reply.json["message"]


def test_a_huge_upload_is_stopped_before_it_is_read(client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", 100)
    reply = upload(client, PNG * 10)
    assert reply.status_code == 413 and reply.json["title"] == "That picture is too big"


def test_every_picture_in_the_list_is_served_and_can_be_picked(client):
    older = upload(client, PNG).json
    newer = upload(client, WEBP, "photo.webp").json
    assert [p["name"] for p in newer["pictures"]] == [newer["picture"], older["picture"]]
    for picture in newer["pictures"]:
        assert client.get(picture["url"]).status_code == 200

    reply = client.post("/wallpaper", data={"pattern": "picture", "picture": older["picture"]})
    assert reply.json["picture_url"] == older["picture_url"]
    assert f'src="{older["picture_url"]}"' in client.get(DEMO_PAGE).text


def test_a_deleted_picture_leaves_the_list_and_stops_being_served(client):
    picture = upload(client, PNG).json
    assert client.get(picture["picture_url"]).headers["Cache-Control"] == "no-store"  # no copy left in a cache
    reply = client.post(f"/wallpaper/picture/{picture['picture']}/delete")
    assert reply.status_code == 200
    assert reply.json["pictures"] == [] and reply.json["pattern"] == config.DEFAULT_WALLPAPER
    assert client.get(picture["picture_url"]).status_code == 404


def test_deleting_a_picture_thats_already_gone_gets_a_popup_message(client):
    reply = client.post("/wallpaper/picture/wallpaper-000000000000.png/delete")
    assert reply.status_code == 404 and reply.json["title"]


def test_reset_keeps_the_pictures(client):
    upload(client, PNG)
    reply = client.post("/wallpaper/reset").json
    assert reply["pattern"] == config.DEFAULT_WALLPAPER and len(reply["pictures"]) == 1


def test_the_hills_drawing_is_on_every_page_and_in_its_preview(client):
    for page in (client.get(DEMO_PAGE).text, client.get("/player/nobody").text):
        assert page.count('class="wallpaper__art art--hills"') == 2  # the desktop + the preview in wallpaper.exe


def test_achievement_progress_shows_up_in_the_scan_stream(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_owned_games", lambda steam_id: [
        make_game(1, "Hades", hours=5, has_stats=True), make_game(2, "Celeste", hours=2, has_stats=True)])
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: [])
    events = scan(client, player="me")
    step = sync.STEPS.index("Checking achievements") + 1
    labels = [event["label"] for event in events if event.get("step") == step]
    assert labels == ["Checking achievements", "Checking achievements 1/2", "Checking achievements 2/2"]


# --- achievements.exe ---------------------------------------------------------


def test_the_demo_player_has_achievements_to_show(client):
    page = client.get(DEMO_PAGE).text
    assert "achievements.exe" in page
    for heading in ("All games", "Latest unlocks", "So close"):
        assert heading in page


def test_achievements_wait_for_a_scan_when_none_were_checked(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_achievements", timing_out)
    scan(client, player="me")
    page = client.get(f"/player/{ME}").text
    assert "Achievements come in with the next scan" in page


def test_achievements_explain_the_key_when_there_is_none(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_achievements", timing_out)
    scan(client, player="me")
    monkeypatch.setattr(config, "STEAM_API_KEY", "")
    assert "Achievements need a Steam API key" in client.get(f"/player/{ME}").text


def test_achievements_say_how_many_played_games_are_still_to_check(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_owned_games", lambda steam_id: [
        make_game(1, "Hades", hours=40, has_stats=True), make_game(2, "Portal", hours=8),
    ])

    def answer(steam_id, app_id):
        if app_id == 2:
            raise api.SteamTimeout()
        return make_achievements(1, unlocked=3, locked=1)

    monkeypatch.setattr(api, "get_achievements", answer)
    scan(client, player="me")
    assert "1 of 2 played games still to check" in client.get(f"/player/{ME}").text


def test_private_achievements_are_explained(client, steam, monkeypatch):
    def private(steam_id, app_id):
        raise api.PrivateAchievements()

    monkeypatch.setattr(api, "get_achievements", private)
    scan(client, player="me")
    assert "Steam won't share this player's achievements" in client.get(f"/player/{ME}").text


def test_a_library_with_no_achievements_at_all_says_so(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_owned_games", lambda steam_id: [make_game(1, "Garry's Mod", hours=3, has_stats=True)])
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: [])
    scan(client, player="me")
    assert "None of the games played so far have achievements" in client.get(f"/player/{ME}").text


def test_versus_compares_achievements_on_shared_games(client):
    page = client.get(f"{DEMO_PAGE}?vs={demo.FRIEND_ID}").text
    duel = storage.get_shared_achievements(demo.PLAYER_ID, demo.FRIEND_ID)
    assert f"Achievements, on {duel['games']} shared games" in page
    assert "Perfect games" in page


def test_versus_leaves_achievements_out_when_there_are_none_to_compare(client, steam):
    scan(client, player="me")
    page = client.get(f"/player/{ME}?vs={demo.PLAYER_ID}").text
    assert "Achievements, on" not in page


def test_the_rarest_unlock_shows_with_its_share_of_players(client):
    page = client.get(DEMO_PAGE).text
    rarest = storage.get_rarest_unlock(demo.PLAYER_ID)
    assert "Rarest unlock" in page and rarest["name"] in page
    assert "of players have it" in page


# --- Forgetting a player ------------------------------------------------------

FRIEND = "76561198000000002"


def save_friend():
    """A friend with a library, a day of history and some achievements."""
    storage.save_snapshot(make_profile(FRIEND, "pal"), [make_game(1, "Hades", hours=10)])
    storage.add_history(FRIEND, [("2026-11-01", 1, 60)])
    storage.save_achievements(FRIEND, 1, 600, make_achievements(1, unlocked=2, locked=1))


def test_forgetting_a_player_deletes_everything_about_them(client):
    save_friend()
    reply = client.post(f"/player/{FRIEND}/forget")
    assert reply.status_code == 200
    assert storage.get_player(FRIEND) is None
    assert storage.get_library(FRIEND) == []
    assert storage.first_log_day(FRIEND) is None
    assert storage.get_achievement_summary(FRIEND)["checked"] == 0
    assert client.get(f"/player/{FRIEND}").status_code == 404


def test_a_forgotten_player_isnt_reopened_on_the_next_launch(client):
    save_friend()
    storage.set_setting("last_player", FRIEND)
    storage.set_setting("last_friend", FRIEND)
    client.post(f"/player/{FRIEND}/forget")
    assert storage.get_setting("last_player") is None and storage.get_setting("last_friend") is None
    assert client.get("/").headers["Location"] == f"{DEMO_PAGE}?vs={demo.FRIEND_ID}"


def test_the_demo_players_cant_be_forgotten(client):
    for steam_id in (demo.PLAYER_ID, demo.FRIEND_ID):
        reply = client.post(f"/player/{steam_id}/forget")
        assert reply.status_code == 400 and reply.json["title"]
        assert storage.get_player(steam_id)


def test_forgetting_someone_already_gone_gets_a_popup_message(client):
    reply = client.post(f"/player/{FRIEND}/forget")
    assert reply.status_code == 404 and reply.json["message"]


def test_the_start_menu_offers_to_forget_real_players_but_not_the_demo(client):
    save_friend()
    page = client.get(DEMO_PAGE).text
    assert f'data-forget-player="{FRIEND}"' in page
    assert f'data-forget-player="{demo.PLAYER_ID}"' not in page


# --- trophies.exe ---


def test_achievements_exe_links_to_trophies_exe(client):
    assert "data-open-trophies" in client.get(DEMO_PAGE).text


def test_trophies_lists_every_game_with_achievements(client):
    page = client.get(f"{DEMO_PAGE}/trophies").text
    games = storage.get_achievement_games(demo.PLAYER_ID)
    assert 'data-title="trophies.exe"' in page
    assert page.count("data-trophy-game=") == len(games)
    assert "average completion" in page and f"unlocked in {date.today().year}" in page


def test_trophy_rows_can_be_sorted_and_searched(client):
    perfect = client.get(f"{DEMO_PAGE}/trophies/rows?sort=perfect").text
    finished = [game for game in storage.get_achievement_games(demo.PLAYER_ID) if game["unlocked"] == game["total"]]
    assert perfect.count("data-trophy-game=") == len(finished)
    name = finished[0]["name"]
    found = client.get(f"{DEMO_PAGE}/trophies/rows", query_string={"q": name}).text
    assert f'data-trophy-game="{finished[0]["app_id"]}"' in found
    assert "No game with achievements called" in client.get(f"{DEMO_PAGE}/trophies/rows?q=zzzz").text
    assert client.get(f"{DEMO_PAGE}/trophies/rows?sort=nonsense").status_code == 200  # falls back to the default


def test_trophies_for_an_unknown_player_is_not_found(client):
    assert client.get("/player/76561190000000000/trophies").status_code == 404


def test_a_games_page_lists_unlocked_then_locked_achievements(client):
    game = next(game for game in storage.get_achievement_games(demo.PLAYER_ID) if 0 < game["unlocked"] < game["total"])
    page = client.get(f"{DEMO_PAGE}/trophies/{game['app_id']}").text
    assert f"Unlocked ({game['unlocked']})" in page
    assert f"Still to get ({game['total'] - game['unlocked']})" in page
    assert page.count("<li class=\"achievement") == game["total"]  # every one, locked or not


def test_a_game_without_achievements_has_no_page(client):
    assert client.get(f"{DEMO_PAGE}/trophies/123456").status_code == 404


def test_opening_a_real_game_fetches_its_missing_icons_once(client, steam, monkeypatch):
    monkeypatch.setattr(api, "get_owned_games", lambda steam_id: [make_game(1, "Hades", hours=40, has_stats=True)])
    monkeypatch.setattr(api, "get_achievements", lambda steam_id, app_id: make_achievements(1, unlocked=2, locked=1))
    scan(client, player="me")
    asked = []
    icons = {"A1_0": "https://example.test/0.jpg", "A1_1": "https://example.test/1.jpg", "B1_0": "https://example.test/b.jpg"}
    monkeypatch.setattr(api, "get_achievement_icons", lambda app_id: asked.append(app_id) or icons)
    page = client.get(f"/player/{ME}/trophies/1").text
    assert "https://example.test/b.jpg" in page
    client.get(f"/player/{ME}/trophies/1")
    assert asked == [1]  # all saved the first time, so Steam isn't asked again
