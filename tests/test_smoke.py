from meetup_bot import main


def test_main_importable() -> None:
    assert callable(main)
