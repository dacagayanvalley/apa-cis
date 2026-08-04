from scripts.fetch_pagasa.pagasa_ingestor import parse_severe_weather_bulletin


def test_final_bulletin_is_not_active_for_region2():
    html = """
    <html><body>
      <h1>Tropical Cyclone Bulletin # 12 FINAL</h1>
      <p>FINAL BULLETIN</p>
      <p>Issued at 11:00 AM, 04 August 2026</p>
      <p>Typhoon TEST</p>
      <section>
        Wind Signal Affected Areas Cagayan, Isabela Meteorological Condition
      </section>
    </body></html>
    """

    parsed = parse_severe_weather_bulletin(html)

    assert parsed["is_final"] is True
    assert parsed["bulletin_status"] == "final"
    assert parsed["active"] is False
    assert parsed["region2_affected"] is False