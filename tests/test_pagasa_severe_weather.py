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


def test_outside_region_same_name_is_not_assigned_to_region2_quirino():
    html = """
    <html><body>
      <h1>Tropical Cyclone Bulletin # 3</h1>
      <p>Issued at 11:00 AM, 05 August 2026</p>
      <p>Tropical Storm TEST</p>
      <section>
        Wind Signal No. 1 Affected Areas Quirino, Ilocos Sur Meteorological Condition
      </section>
    </body></html>
    """

    parsed = parse_severe_weather_bulletin(html)

    assert parsed["region2_affected"] is False
    assert parsed["signal_levels"]["Quirino"] == 0
    assert parsed["affected_municipalities"] == []


def test_partial_province_matches_only_named_municipalities():
    html = """
    <html><body>
      <h1>Tropical Cyclone Bulletin # 4</h1>
      <p>Issued at 11:00 AM, 05 August 2026</p>
      <p>Tropical Storm TEST</p>
      <section>
        Wind Signal No. 2 Affected Areas portions of Isabela (Quirino, Roxas) Meteorological Condition
      </section>
    </body></html>
    """

    parsed = parse_severe_weather_bulletin(html)
    affected = {(item["municipality"], item["province"]) for item in parsed["affected_municipalities"]}

    assert parsed["municipality_validation"]["coverage_scope"] == "municipality"
    assert ("Quirino", "Isabela") in affected
    assert ("Roxas", "Isabela") in affected
    assert all(item["province"] == "Isabela" for item in parsed["affected_municipalities"])
    assert len(parsed["affected_municipalities"]) == 2
