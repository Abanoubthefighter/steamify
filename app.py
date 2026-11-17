"""The Flask app: routes, and nothing clever.

Each route asks the other modules for data and hands it to a template.
Talking to Steam happens in api.py, the maths in stats.py, the SQL in
storage.py. This file shouldn't need to know how any of those work.

Run it directly (py app.py) to use the dashboard in a normal browser.
desktop.py wraps the very same app in a native window.
"""

import json

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, stream_with_context, url_for

import api
import captions
import charts
import config
import demo
import formatting
import stats
import storage
import sync

app = Flask(__name__)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True

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
    plural=formatting.plural,
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
        library=_library_page(games, request.args),
        sort_choices=stats.sort_choices(),
        players=[person for person in storage.list_players(config.PLAYERS_IN_MENU) if person["steam_id"] != demo.FRIEND_ID],
        scan_defaults={
            "player": config.DEFAULT_STEAM_ID if is_demo else steam_id,
            "friend": friend["steam_id"] if friend and not is_demo else "",
        },
        # Saved data goes on screen straight away. If it's old, the page asks
        # for a fresh scan in the background once it has loaded.
        autosync=config.AUTO_SYNC and not is_demo and bool(config.STEAM_API_KEY) and not sync.is_fresh(player),
    )


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
                    yield _line(step=step, steps=step_count, label=prefix + event["label"])
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
