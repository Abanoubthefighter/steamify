"""The Flask app: routes, and nothing clever.

Each route asks the other modules for data and hands it to a template.
Talking to Steam happens in api.py, the maths in stats.py, the SQL in
storage.py. This file shouldn't need to know how any of those work.

Run it directly (py app.py) to use the dashboard in a normal browser.
desktop.py wraps the very same app in a native window.
"""

import json
from datetime import date

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
    url_for,
)

import api
import background
import captions
import charts
import config
import demo
import formatting
import preferences
import stats
import storage
import sync
import wallpaper

app = Flask(__name__)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
# The biggest request the server reads: an imported wallpaper, plus a little
# room for the form around it. wallpaper.py checks the picture's exact size.
app.config["MAX_CONTENT_LENGTH"] = (config.WALLPAPER_MAX_MB + 1) * 1024 * 1024

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    f"img-src 'self' data: {config.IMAGE_HOSTS}; "
    "style-src 'self' 'unsafe-inline'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def prepare() -> None:
    """Get the database ready. Call once at startup, before the first request."""
    storage.init_db()
    demo.install()


# --- Helpers the templates can use -------------------------------------------


def icon_url(game: dict) -> str | None:
    """Where Steam hosts a game's small icon. None for games without one (demo games, for a start)."""
    if game["app_id"] > 0 and game["icon"]:
        return config.STEAM_ICON_URL.format(app_id=game["app_id"], icon=game["icon"])
    return None


def art_url(game: dict) -> str | None:
    """The wide banner picture from the game's store page."""
    return config.STEAM_ART_URL.format(app_id=game["app_id"]) if game["app_id"] > 0 else None


def store_url(game: dict) -> str | None:
    return config.STEAM_STORE_PAGE.format(app_id=game["app_id"]) if game["app_id"] > 0 else None


app.jinja_env.filters.update(
    hours=formatting.hours,
    ago=formatting.time_ago,
    every=formatting.every,
    plural=formatting.plural,
    number=formatting.number,
    share=formatting.share,
    last_played=formatting.last_played,
    long_date=formatting.long_date,
    year=formatting.year,
    filename=formatting.filename,
    icon_url=icon_url,
    art_url=art_url,
    store_url=store_url,
)


@app.context_processor
def template_globals() -> dict:
    """Values every template may need, so each route doesn't have to pass them."""
    return {
        "has_key": bool(config.STEAM_API_KEY),
        "key_page": config.STEAM_KEY_PAGE,
        "app_version": config.APP_VERSION,
        # A function, not a value: only base.html calls it, so the small page
        # fragments (library rows, game card) don't read the setting for nothing.
        "wallpaper": wallpaper_state,
        "wallpaper_patterns": config.WALLPAPER_PATTERNS,
        "wallpaper_max_mb": config.WALLPAPER_MAX_MB,
        "wallpaper_dim_max": config.WALLPAPER_DIM_MAX,
        "preferences": preferences.current,  # a function, for the same reason as wallpaper
        "background_sync_minutes": config.BACKGROUND_SYNC_MINUTES,
        # desktop.py sets this. In a browser tab there's no tray, so settings.exe says so.
        "desktop_app": app.config.get("DESKTOP_APP", False),
    }


def wallpaper_state(choice: dict | None = None) -> dict:
    """The wallpaper as the page and wallpaper.exe need it.

    The pattern, the dim level, which picture is picked (and its address),
    and every imported picture for the list in wallpaper.exe.
    """
    choice = choice or wallpaper.current()
    picture = choice["picture"]
    return {
        "pattern": choice["pattern"],
        "dim": choice["dim"],
        "picture": picture,
        "picture_url": url_for("wallpaper_picture", name=picture) if picture else None,
        "pictures": [
            {"name": name, "url": url_for("wallpaper_picture", name=name)} for name in wallpaper.pictures()
        ],
    }


# --- Pages -------------------------------------------------------------------


@app.get("/")
def home():
    """Open whoever was on screen last time. On a first run that's the demo player."""
    last = storage.get_setting("last_player")
    if last and storage.get_player(last):
        friend = storage.get_setting("last_friend")
    else:
        last, friend = demo.PLAYER_ID, demo.FRIEND_ID
    return redirect(url_for("dashboard", steam_id=last, vs=friend or None))


@app.get("/player/<steam_id>")
def dashboard(steam_id: str):
    """The whole desktop for one player, drawn from what's saved in SQLite."""
    player = storage.get_player(steam_id) or abort(404)
    friend = storage.get_player(request.args.get("vs", ""))
    games = storage.get_library(steam_id)
    summary = stats.summarize(games)
    is_demo = demo.is_demo(steam_id)
    if not is_demo:
        _remember(player, friend)

    return render_template(
        "dashboard.html",
        player=player,
        friend=friend,
        is_demo=is_demo,
        summary=summary,
        alerts=captions.build_alerts(games, summary, is_demo=is_demo),
        top_games=stats.top_games(games, config.TOP_GAMES_COUNT),
        recent_games=stats.recent_games(games, config.RECENT_GAMES_COUNT),
        tracks=charts.build_tracks(player, games, summary),
        versus=_versus(player, summary, friend),
        achievements=_achievements(steam_id),
        library=_library_page(games, request.args),
        sort_choices=stats.sort_choices(),
        players=_menu_players(),
        scan_defaults={
            "player": config.DEFAULT_STEAM_ID if is_demo else steam_id,
            "friend": friend["steam_id"] if friend and not is_demo else "",
        },
        # Saved data goes on screen straight away. If it's old, the page asks
        # for a fresh scan in the background once it has loaded.
        autosync=config.AUTO_SYNC and not is_demo and bool(config.STEAM_API_KEY) and not sync.is_fresh(player),
        background_round=background.last_round(),
        stamp=_data_stamp(games, steam_id),
    )


@app.get("/player/<steam_id>/stamp")
def data_stamp(steam_id: str):
    """A short summary of this player's numbers. The page asks now and then to spot a background sync."""
    storage.get_player(steam_id) or abort(404)
    return jsonify(stamp=_data_stamp(storage.get_library(steam_id), steam_id))


def _data_stamp(games: list[dict], steam_id: str) -> str:
    """Games owned, minutes played, achievements unlocked: "137-147060-512".

    It only changes when something on screen would. The time of the last sync
    alone wouldn't do: every hourly sync changes it, even when nothing was played.
    """
    unlocked = storage.get_achievement_summary(steam_id)["unlocked"]
    return f"{len(games)}-{sum(game['minutes'] for game in games)}-{unlocked}"


@app.get("/player/<steam_id>/library")
def library_rows(steam_id: str):
    """Just the rows of library.exe, re-sorted or filtered. The page swaps them in without reloading."""
    storage.get_player(steam_id) or abort(404)
    return render_template("partials/library_rows.html", library=_library_page(storage.get_library(steam_id), request.args))


@app.get("/player/<steam_id>/game/<int(signed=True):app_id>")
def game_card(steam_id: str, app_id: int):
    """The details popup for one game."""
    games = storage.get_library(steam_id)
    game, rank = stats.find_game(games, app_id) or abort(404)
    total = sum(each["minutes"] for each in games)
    return render_template(
        "partials/game_card.html",
        game=game,
        rank=rank,
        game_count=len(games),
        share=stats.percent(game["minutes"], total),
    )


@app.get("/player/<steam_id>/trophies")
def trophies(steam_id: str):
    """trophies.exe: every game with achievements. Fetched when "View all" in achievements.exe is pressed."""
    storage.get_player(steam_id) or abort(404)
    games = storage.get_achievement_games(steam_id)
    year = str(date.today().year)
    return render_template(
        "partials/trophies.html",
        overview=stats.achievement_overview(games),
        year=year,
        this_year=sum(row["unlocks"] for row in storage.get_unlock_counts(steam_id, "year", since=year)),
        coverage=storage.get_achievement_coverage(steam_id),
        trophy_choices=stats.trophy_choices(),
        trophies=_trophy_page(games, request.args),
    )


@app.get("/player/<steam_id>/trophies/rows")
def trophy_rows(steam_id: str):
    """Just the game list of trophies.exe, re-sorted or filtered. The page swaps it in."""
    storage.get_player(steam_id) or abort(404)
    page = _trophy_page(storage.get_achievement_games(steam_id), request.args)
    return render_template("partials/trophy_rows.html", trophies=page)


@app.get("/player/<steam_id>/trophies/<int(signed=True):app_id>")
def trophy_game(steam_id: str, app_id: int):
    """One game's achievements, locked ones included: what a row in trophies.exe opens."""
    owned = {game["app_id"]: game for game in storage.get_achievement_games(steam_id)}
    game = owned.get(app_id) or abort(404)
    sync.fetch_icons(app_id)  # asks Steam only if some icons are still missing
    achievements = storage.get_game_achievements(steam_id, app_id)
    return render_template(
        "partials/trophy_game.html",
        game={**game, "percent": stats.completion(game)},
        unlocked=[item for item in achievements if item["achieved"]],
        locked=[item for item in achievements if not item["achieved"]],
    )


def _trophy_page(games: list[dict], args) -> dict:
    """Sort and filter trophies.exe's game list the way the request asked for."""
    order = args.get("sort", stats.DEFAULT_TROPHY_ORDER)
    if order not in stats.TROPHY_ORDERS:
        order = stats.DEFAULT_TROPHY_ORDER
    query = args.get("q", "").strip()
    matches = stats.search_games(stats.sort_trophies(games, order), query)
    rows = [{**game, "percent": stats.completion(game)} for game in matches]
    return {"rows": rows, "total": len(games), "order": order, "query": query}


def _menu_players() -> list[dict]:
    """The saved players for the start menu. The demo friend is left out, and the demo can't be forgotten."""
    return [
        {**person, "can_forget": not demo.is_demo(person["steam_id"])}
        for person in storage.list_players(config.PLAYERS_IN_MENU)
        if person["steam_id"] != demo.FRIEND_ID
    ]


def _remember(player: dict, friend: dict | None) -> None:
    """Note who is on screen, so the next launch opens straight to them."""
    wanted = {"last_player": player["steam_id"], "last_friend": friend["steam_id"] if friend else None}
    for key, value in wanted.items():
        if storage.get_setting(key) != value:
            storage.set_setting(key, value)


def _library_page(games: list[dict], args) -> dict:
    """Sort, filter and trim the game list the way the request asked for."""
    order = args.get("sort", stats.DEFAULT_SORT)
    if order not in stats.SORT_ORDERS:
        order = stats.DEFAULT_SORT
    query = args.get("q", "").strip()
    matches = stats.search_games(stats.sort_games(games, order), query)
    rows = matches if args.get("all") else matches[: config.LIBRARY_PAGE_SIZE]
    return {"rows": rows, "match_count": len(matches), "total": len(games), "order": order, "query": query}


def _versus(player: dict, summary: dict, friend: dict | None) -> dict | None:
    """The numbers behind versus.exe, or None when there's nobody to compare with."""
    if not friend or friend["steam_id"] == player["steam_id"]:
        return None
    theirs = stats.summarize(storage.get_library(friend["steam_id"]))
    shared, shared_count = storage.get_shared_games(player["steam_id"], friend["steam_id"], config.SHARED_GAMES_COUNT)
    for game in shared:
        both = game["my_minutes"] + game["their_minutes"]
        game["my_share"] = stats.percent(game["my_minutes"], both) if both else 50
    return {
        "friend": friend,
        "theirs": theirs,
        "shared": shared,
        "shared_count": shared_count,
        "caption": captions.versus_caption(friend["name"], summary["total_minutes"] - theirs["total_minutes"]),
        "achievements": _achievement_duel(player, friend),
    }


def _achievement_duel(player: dict, friend: dict) -> dict | None:
    """Achievements in versus.exe: both players over the games with achievements they share."""
    duel = storage.get_shared_achievements(player["steam_id"], friend["steam_id"])
    if not duel["games"]:
        return None
    unlocked = duel["my_unlocked"] + duel["their_unlocked"]
    perfect = duel["my_perfect"] + duel["their_perfect"]
    return {
        **duel,
        # Where each split bar is cut: your share on the left. An empty contest splits down the middle.
        "unlocked_share": stats.percent(duel["my_unlocked"], unlocked) if unlocked else 50,
        "perfect_share": stats.percent(duel["my_perfect"], perfect) if perfect else 50,
        "caption": captions.versus_achievement_caption(friend["name"], duel),
    }


def _achievements(steam_id: str) -> dict | None:
    """The numbers behind achievements.exe, or None if there's nothing to say yet.

    Also says how complete they are: played games still waiting for a check,
    and whether Steam keeps this player's achievements private.
    """
    totals = storage.get_achievement_summary(steam_id)
    coverage = storage.get_achievement_coverage(steam_id)
    if not totals["checked"] and not coverage["private"]:
        return None
    percent = stats.percent(totals["unlocked"], totals["total"])
    nearly = storage.get_nearly_done(steam_id, config.NEARLY_DONE_PERCENT, config.NEARLY_DONE_COUNT)
    return {
        **totals,
        **coverage,
        "percent": percent,
        "caption": captions.achievement_caption(totals, percent),
        "recent": storage.get_recent_unlocks(steam_id, config.RECENT_UNLOCKS_COUNT),
        "nearly": [{**game, "percent": stats.percent(game["unlocked"], game["total"])} for game in nearly],
        "nearly_percent": config.NEARLY_DONE_PERCENT,
        "rarest": storage.get_rarest_unlock(steam_id),
    }


# --- Actions -----------------------------------------------------------------


@app.post("/scan")
def scan():
    """Scan a player (and optionally a friend), sending progress back as it happens.

    The reply is a stream of small JSON objects, one per line. The page reads
    each line as it arrives and moves the progress bar, instead of waiting in
    silence until everything is done.
    """
    form = request.form
    events = _scan_events(form.get("player", ""), form.get("friend", ""), force=form.get("force") == "1")
    return Response(stream_with_context(events), mimetype="application/x-ndjson")


def _scan_events(player_text: str, friend_text: str, force: bool):
    """Run the scans and describe them line by line (see scan above)."""
    queries = [player_text.strip()] + ([friend_text.strip()] if friend_text.strip() else [])
    step_count = len(queries) * len(sync.STEPS)
    found, gained = [], 0

    for number, query in enumerate(queries):
        scanner = demo.scan if demo.is_demo(query) else sync.scan
        prefix = "Friend: " if number else ""
        step = number * len(sync.STEPS)
        try:
            for event in scanner(query, force=force):
                if "label" in event:
                    step += 1
                    label = prefix + event["label"]
                    yield _line(step=step, steps=step_count, label=label)
                elif "detail" in event:  # progress inside a long step, like "12/40"
                    yield _line(step=step, steps=step_count, label=f"{label} {event['detail']}")
                else:
                    found.append(event["steam_id"])
                    gained += event["gained"]
        except api.SteamError as error:
            # If it was the friend who failed, `url` still points at the player's own dashboard.
            yield _line(error=error.as_dict(), url=_dashboard_url(found))
            return
        except Exception:
            app.logger.exception("Scan failed")
            yield _line(error=api.SteamError("The scan stopped halfway. Nothing was lost, so just try again.").as_dict())
            return

    yield _line(done=True, gained=gained, url=_dashboard_url(found))


def _line(**event) -> str:
    return json.dumps(event) + "\n"


def _dashboard_url(found: list[str]) -> str | None:
    """Where to go after a scan: the first ID is the player, the second (if any) the friend."""
    if not found:
        return None
    return url_for("dashboard", steam_id=found[0], vs=found[1] if len(found) > 1 else None)


@app.post("/player/<steam_id>/forget")
def forget_player(steam_id: str):
    """Delete a saved player and everything the app knows about them. Their Steam account isn't touched."""
    if demo.is_demo(steam_id):
        return jsonify(title="The demo stays", message="The made-up players come back every day anyway."), 400
    if not storage.get_player(steam_id):
        return jsonify(title="Already gone", message="That player isn't saved in the app any more."), 404
    storage.forget_player(steam_id)  # their library, history and achievements go with them
    # Don't reopen them on the next launch either.
    for key in ("last_player", "last_friend"):
        if storage.get_setting(key) == steam_id:
            storage.set_setting(key, None)
    return jsonify(ok=True)


@app.post("/settings/key")
def save_key():
    """Check an API key with Steam and, if it works, keep it in .env."""
    key = request.form.get("key", "").strip()
    if not api.looks_like_key(key):
        return jsonify(
            title="That doesn't look like a key",
            message="A Steam API key is 32 letters and digits. Copy it again from the key page.",
        ), 400
    try:
        if not api.key_works(key):
            raise api.BadKey()
    except api.SteamError as error:
        return jsonify(error.as_dict()), 502
    config.save_api_key(key)
    return jsonify(ok=True)


# --- Wallpaper (wallpaper.exe) ------------------------------------------------


@app.post("/settings")
def change_settings():
    """settings.exe: turn a setting on ("1") or off ("0"). Replies with every setting."""
    changes = {}
    for key in preferences.defaults():
        if key in request.form:
            if request.form[key] not in ("0", "1"):
                return jsonify(title="Can't save that", message="That setting only takes on or off."), 400
            changes[key] = request.form[key] == "1"
    return jsonify(preferences.update(**changes))


@app.post("/wallpaper")
def change_wallpaper():
    """Pick a pattern (or which picture), a dim level, or both. Replies with the new wallpaper."""
    try:
        if "pattern" in request.form:
            wallpaper.choose(request.form["pattern"], request.form.get("picture"))
        if "dim" in request.form:
            wallpaper.set_dim(request.form["dim"])
    except wallpaper.WallpaperError as error:
        return jsonify(error.as_dict()), 400
    return jsonify(wallpaper_state())


@app.post("/wallpaper/picture")
def import_wallpaper():
    """Copy a picture from the user's computer, add it to the list and make it the wallpaper."""
    upload = request.files.get("picture")
    if upload is None:
        return jsonify(title="No picture", message="Pick a picture to import first."), 400
    try:
        choice = wallpaper.import_picture(upload.read())
    except wallpaper.WallpaperError as error:
        return jsonify(error.as_dict()), 400
    return jsonify(wallpaper_state(choice))


@app.post("/wallpaper/picture/<name>/delete")
def delete_wallpaper_picture(name: str):
    """Remove one imported picture from the app. The original file is never touched."""
    try:
        choice = wallpaper.delete_picture(name)
    except wallpaper.WallpaperError as error:
        return jsonify(error.as_dict()), 404
    return jsonify(wallpaper_state(choice))


@app.post("/wallpaper/reset")
def reset_wallpaper():
    """Back to the default wallpaper. Imported pictures stay in the list."""
    return jsonify(wallpaper_state(wallpaper.reset()))


@app.get("/wallpaper/picture/<name>")
def wallpaper_picture(name: str):
    """One imported picture. Only names in the list are ever handed out, nothing else in the folder."""
    if name not in wallpaper.pictures():
        abort(404)
    response = send_from_directory(config.WALLPAPER_DIR, name)
    # Don't let the window keep its own copy. A deleted picture should really
    # be gone, not linger in a cache folder. It comes from this computer's own
    # disk, so loading it again is quick.
    response.headers["Cache-Control"] = "no-store"
    return response


# --- Safety nets -------------------------------------------------------------


@app.before_request
def only_this_computer():
    """Refuse anything that didn't come from our own window.

    The server only listens on 127.0.0.1, but a website open in a normal
    browser could still try to send it a request. Browsers attach an Origin
    header to those, so a mismatch means "not us".
    """
    if request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
        abort(403)
    origin = request.headers.get("Origin")
    if request.method == "POST" and origin and origin != request.host_url.rstrip("/"):
        abort(403)


@app.after_request
def add_security_headers(response: Response) -> Response:
    """Names on Steam are written by strangers. Templates escape them, and this is the second lock."""
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.errorhandler(404)
def not_found(error):
    return render_template(
        "error.html",
        title="File not found",
        message="There's nothing at this address. Maybe that player was never scanned?",
    ), 404


@app.errorhandler(413)
def too_big(error):
    # Only an imported picture can be this big, and wallpaper.exe shows the reply as a popup.
    return jsonify(title="That picture is too big", message=f"Pick one under {config.WALLPAPER_MAX_MB} MB."), 413


@app.errorhandler(500)
def server_error(error):
    return render_template(
        "error.html",
        title="Something broke",
        message="That one's on the app, not on you. Going back to the desktop usually sorts it out.",
    ), 500


if __name__ == "__main__":
    prepare()
    app.run(host=config.HOST, port=config.DEV_PORT, debug=config.DEBUG, threaded=True)
