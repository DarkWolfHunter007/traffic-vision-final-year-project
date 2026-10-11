from backend.config import ConfigError, config_hash, load_config


def test_config_hash_is_stable_for_equivalent_mappings() -> None:
    first = load_config(overrides={"logging": {"level": "DEBUG"}})
    second = load_config(overrides={"logging": {"level": "DEBUG"}})
    assert config_hash(first) == config_hash(second)


def test_config_rejects_non_decoder_pts_strategy() -> None:
    try:
        load_config(overrides={"timestamp": {"strategy": "fps"}})
    except ConfigError as error:
        assert "decoder_pts" in str(error)
    else:
        raise AssertionError("Expected a config validation error")
