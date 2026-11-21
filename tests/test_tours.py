from datetime import date

import pytest
from sqlalchemy import select

from app.models import Tour
from app.services import tours as tour_service
from app.services.seed import load_seed_records

from .conftest import TODAY


def test_seed_codes_are_unique_and_telegram_safe():
    records = load_seed_records()
    codes = [r["tour_code"] for r in records]
    assert len(codes) == len(set(codes))
    assert all(tour_service.is_valid_tour_code(code) for code in codes)


def test_copy_from_inherits_content_and_overrides_dates():
    records = {r["tour_code"]: r for r in load_seed_records()}
    original, demo = records["burgundy_2026_11"], records["burgundy_2027_11"]
    assert demo["title"] == original["title"]
    assert demo["program"] == original["program"]
    assert demo["start_date"] == date(2027, 11, 20)
    assert demo["dates_are_demo"] is True
    assert original["dates_are_demo"] is False


def test_georgia_keeps_source_dates():
    georgia = {r["tour_code"]: r for r in load_seed_records()}["georgia_2027_03"]
    assert (georgia["start_date"], georgia["end_date"]) == (date(2027, 3, 20), date(2027, 3, 27))
    assert georgia["dates_are_demo"] is False


def test_finished_tour_hidden_but_kept_in_db(db):
    public_codes = {t.tour_code for t in tour_service.list_public_tours(db, TODAY)}
    assert "burgundy_2026_11" not in public_codes
    assert "burgundy_2027_11" in public_codes
    assert db.scalar(select(Tour).where(Tour.tour_code == "burgundy_2026_11")) is not None


def test_public_list_changes_with_date(db):
    later = date(2027, 3, 5)  # Андалусия уже идёт, Грузия ещё впереди
    codes = {t.tour_code for t in tour_service.list_public_tours(db, later)}
    assert "andalusia_2027_03" not in codes
    assert "georgia_2027_03" in codes
    assert "lisbon_2027_01" not in codes


def test_public_tours_sorted_by_start_date(db):
    starts = [t.start_date for t in tour_service.list_public_tours(db, TODAY)]
    assert starts == sorted(starts)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("georgia_2027_03", tour_service.LookupStatus.OK),
        ("burgundy_2026_11", tour_service.LookupStatus.UNAVAILABLE),
        ("unknown_code", tour_service.LookupStatus.NOT_FOUND),
        ("", tour_service.LookupStatus.NOT_FOUND),
        ("bad code!", tour_service.LookupStatus.NOT_FOUND),
    ],
)
def test_find_public_tour(db, code, expected):
    assert tour_service.find_public_tour(db, code, TODAY).status is expected


def test_build_start_link():
    assert (tour_service.build_start_link("@my_bot", "georgia_2027_03")
            == "https://t.me/my_bot?start=georgia_2027_03")
    assert tour_service.build_start_link("", "georgia_2027_03") is None
    with pytest.raises(ValueError):
        tour_service.build_start_link("my_bot", "bad code")


def test_format_date_range():
    assert tour_service.format_date_range(date(2027, 3, 20), date(2027, 3, 27)) == "20–27 марта 2027"
    assert (tour_service.format_date_range(date(2027, 6, 28), date(2027, 7, 8))
            == "28 июня — 8 июля 2027")


def test_unlisted_tour_kept_and_reachable(db):
    codes = {t.tour_code for t in tour_service.list_public_tours(db, TODAY)}
    assert "lisbon_2027_01" not in codes
    assert tour_service.find_public_tour(db, "lisbon_2027_01", TODAY).status is tour_service.LookupStatus.OK


def test_init_db_adds_listed_column_to_old_database(tmp_path):
    import sqlite3
    from app.database import init_engine
    from app.services.seed import init_db
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE tours (id INTEGER PRIMARY KEY, tour_code VARCHAR(64) UNIQUE, title VARCHAR(200), "
                 "subtitle VARCHAR(300), destination VARCHAR(100), start_date DATE, end_date DATE, "
                 "dates_are_demo BOOLEAN, date_note TEXT, duration VARCHAR(100), transport VARCHAR(100), "
                 "image VARCHAR(200), image_note TEXT, price_label VARCHAR(200), summary TEXT, route JSON, "
                 "logistics JSON, program JSON, prices JSON, included JSON, extras JSON, notes JSON)")
    conn.commit()
    conn.close()
    engine = init_engine(f"sqlite:///{path.as_posix()}")
    init_db(engine)
    with engine.connect() as c:
        cols = [row[1] for row in c.exec_driver_sql("PRAGMA table_info(tours)")]
    engine.dispose()
    assert "listed" in cols
