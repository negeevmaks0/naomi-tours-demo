import re

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

from .conftest import TEST_BOT_USERNAME


def test_home_and_catalog_render(client):
    assert client.get("/").status_code == 200
    response = client.get("/tours")
    assert response.status_code == 200
    assert "Грузия — авиатур" in response.text
    assert "Южная Испания" in response.text


def test_catalog_hides_finished_tour(client):
    html = client.get("/tours").text
    assert "/tours/burgundy_2026_11" not in html
    assert "/tours/burgundy_2027_11" in html


def test_every_catalog_card_opens_own_page(client):
    html = client.get("/tours").text
    links = set(re.findall(r'href="/tours/([A-Za-z0-9_-]+)"', html))
    assert len(links) >= 4
    for code in links:
        page = client.get(f"/tours/{code}")
        assert page.status_code == 200
        assert f"https://t.me/{TEST_BOT_USERNAME}?start={code}" in page.text


def test_tour_page_content(client):
    html = client.get("/tours/georgia_2027_03").text
    assert "Оставить заявку" in html
    assert "900 €" in html and "1 060 €" in html
    assert "Chateau Fort de Manavi" in html
    assert "chip-demo" not in html  # даты Грузии из источника


def test_demo_dates_are_marked(client):
    assert "chip-demo" in client.get("/tours/andalusia_2027_03").text


def test_finished_and_unknown_tours_return_404(client):
    assert client.get("/tours/burgundy_2026_11").status_code == 404
    assert client.get("/tours/no_such_tour").status_code == 404


def test_apply_button_disabled_without_bot_username(settings):
    no_bot = Settings(**{**settings.__dict__, "bot_username": ""})
    with TestClient(create_app(no_bot)) as test_client:
        html = test_client.get("/tours/georgia_2027_03").text
    assert "t.me/" not in html
    assert "btn-disabled" in html


def test_no_payment_details_on_site(client):
    for path in ["/", "/tours", "/tours/georgia_2027_03", "/tours/lisbon_2027_01"]:
        html = client.get(path).text.lower()
        assert "paypal" not in html
        assert "iban" not in html
        assert "@gmx" not in html


def test_catalog_sorting(client):
    def codes(html):
        return re.findall(r'href="/tours/([A-Za-z0-9_-]+)"', html)
    nearest = codes(client.get("/tours").text)
    latest = codes(client.get("/tours", params={"sort": "latest"}).text)
    assert nearest[0] == "andalusia_2027_03"
    assert latest == list(reversed(nearest))
    assert codes(client.get("/tours", params={"sort": "bogus"}).text) == nearest


def test_info_pages_render(client):
    how = client.get("/how")
    assert how.status_code == 200
    assert "Частые вопросы" in how.text
    assert f"https://t.me/{TEST_BOT_USERNAME}" in how.text
    about = client.get("/about")
    assert about.status_code == 200
    assert "Куда мы ездим" in about.text


def test_placeholder_has_no_caption_and_own_color(client):
    html = client.get("/tours").text
    assert "фото будет добавлено" not in html
    hues = set(re.findall(r'placeholder" style="--h: (\d+)"', html))
    assert len(hues) >= 2  # Грузия и Франция — разные оттенки


def test_unlisted_tour_hidden_from_catalog_but_direct_link_works(client):
    assert "/tours/lisbon_2027_01" not in client.get("/tours").text
    assert "/tours/lisbon_2027_01" not in client.get("/").text
    page = client.get("/tours/lisbon_2027_01")
    assert page.status_code == 200
    assert "временно не показан в каталоге" in page.text
    assert f"https://t.me/{TEST_BOT_USERNAME}?start=lisbon_2027_01" in page.text


def test_unknown_page_returns_html_404(client):
    response = client.get("/xyz", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Страница не найдена" in response.text
    assert 'href="/tours"' in response.text


def test_machine_404_stays_json(client):
    assert client.get("/static/nope.css").headers["content-type"].startswith("application/json")
    api_like = client.get("/xyz", headers={"accept": "application/json"})
    assert api_like.status_code == 404
    assert api_like.json() == {"detail": "Not Found"}
    assert client.get("/health").json() == {"status": "ok"}


def test_format_cards_are_not_links_to_catalog(client):
    html = client.get("/").text
    assert 'class="format"' in html
    assert '<a class="format"' not in html


def test_home_has_no_unconfirmed_claims(client):
    text = client.get("/").text + client.get("/about").text
    for phrase in ["на русском языке", "получают инфолист", "сопровождает руководитель",
                   "Путешествия, в которые хочется вернуться", "аэропортов Хан или Карлсруэ"]:
        assert phrase not in text
    assert "Групповые поездки из Франкфурта и Майнца" in text


def test_base_path_prefixes_all_internal_links(settings):
    prefixed = Settings(**{**settings.__dict__, "base_path": "/naomi-tours-demo"})
    with TestClient(create_app(prefixed)) as test_client:
        for path in ["/", "/tours", "/tours/georgia_2027_03", "/how", "/about"]:
            html = test_client.get(path).text
            internal = re.findall(r'(?:href|src|action)="(/[^"]*)"', html)
            assert internal, path
            assert all(link.startswith("/naomi-tours-demo/") for link in internal), path


def test_organizer_block_only_when_configured(client, settings):
    assert "Организатор:" not in client.get("/about").text
    with_org = Settings(**{**settings.__dict__, "organizer_name": "Тестовый организатор"})
    with TestClient(create_app(with_org)) as test_client:
        assert "Тестовый организатор" in test_client.get("/about").text


def test_static_export(tmp_path, settings, monkeypatch):
    from app import export_static
    monkeypatch.setattr(export_static, "load_settings", lambda: settings)
    out = tmp_path / "site"
    written = export_static.export(out, "/naomi-tours-demo", database_url=settings.database_url)
    for page in ["index.html", "tours/index.html", "tours/latest/index.html", "how/index.html",
                 "about/index.html", "404.html", "tours/georgia_2027_03/index.html",
                 "tours/lisbon_2027_01/index.html"]:
        assert page in written and (out / page).exists(), page
    assert not (out / "tours/burgundy_2026_11").exists()  # завершившийся тур не публикуется
    assert (out / "static/css/style.css").exists() and (out / ".nojekyll").exists()
    catalog = (out / "tours/index.html").read_text(encoding="utf-8")
    assert 'href="/naomi-tours-demo/tours/georgia_2027_03"' in catalog
    assert 'data-url="/naomi-tours-demo/tours/latest/"' in catalog
    assert "Страница не найдена" in (out / "404.html").read_text(encoding="utf-8")
