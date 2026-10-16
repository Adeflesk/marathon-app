def test_peak_default(settings):
    assert settings["peak_weekly_km"] == 60


def test_new_paces(settings):
    assert settings["paces"]["interval"] == 300
    assert settings["paces"]["subthreshold"] == 332
