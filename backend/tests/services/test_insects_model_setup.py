from unittest.mock import MagicMock

import pytest

from scripts import setup_insects_model as setup


def model_files(directory):
    for name in setup.REQUIRED_FILES:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")


def test_local_mode_copies_files_without_download(tmp_path, monkeypatch):
    source, target = tmp_path / "source", tmp_path / "target"
    model_files(source)
    download = MagicMock()
    monkeypatch.setattr(setup, "prepare_insects_model", download)
    setup.prepare_image_model(target, "local", source)
    assert setup.check_insects_files(target)
    assert (target / ".mode").read_text() == "local\n"
    download.assert_not_called()


@pytest.mark.parametrize("mode", ["invalid", "LOCAL", ""])
def test_invalid_mode_fails_before_creating_directory(tmp_path, mode):
    target = tmp_path / "target"
    with pytest.raises(setup.InsectsModelSetupError, match="INSECTS_MODEL_MODE"):
        setup.prepare_image_model(target, mode)
    assert not target.exists()


def test_disabled_mode_does_not_prepare_model(tmp_path, monkeypatch, caplog):
    download = MagicMock()
    monkeypatch.setattr(setup, "prepare_insects_model", download)
    setup.prepare_image_model(tmp_path, "disabled")
    assert sorted(p.name for p in tmp_path.iterdir()) == [".mode"]
    assert "disabled" in caplog.text
    download.assert_not_called()


def test_download_mode_prepares_model(tmp_path, monkeypatch):
    download = MagicMock(side_effect=model_files)
    monkeypatch.setattr(setup, "prepare_insects_model", download)
    setup.prepare_image_model(tmp_path, "download")
    download.assert_called_once_with(tmp_path)
    assert (tmp_path / ".mode").read_text() == "download\n"


@pytest.mark.parametrize("empty", [False, True])
def test_local_mode_rejects_incomplete_source(tmp_path, empty):
    source = tmp_path / "source"
    model_files(source)
    weight = source / "_best/model.pt"
    weight.write_bytes(b"") if empty else weight.unlink()
    with pytest.raises(setup.InsectsModelSetupError, match="incomplete"):
        setup.prepare_image_model(tmp_path / "target", "local", source)


def test_local_mode_validates_copied_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    model_files(source)
    monkeypatch.setattr(setup.shutil, "copytree", lambda *args, **kwargs: None)
    with pytest.raises(setup.InsectsModelSetupError, match="validation failed"):
        setup.prepare_image_model(tmp_path / "target", "local", source)


def test_model_mode_comes_from_image_file(tmp_path, monkeypatch):
    marker = tmp_path / ".mode"
    monkeypatch.setattr(setup, "MODEL_MODE_FILE", marker)
    assert setup.installed_model_mode() == "download"
    marker.write_text("disabled\n")
    monkeypatch.setenv("INSECTS_MODEL_MODE", "download")
    assert setup.installed_model_mode() == "disabled"


@pytest.mark.parametrize("explicit", [False, True])
def test_download_error_reports_underlying_network_failure(tmp_path, monkeypatch, caplog, explicit):
    monkeypatch.setattr(setup, "_copy_from_cache", lambda _: False)
    def download(_):
        try:
            raise ConnectionResetError("Connection reset by peer")
        except ConnectionResetError as error:
            if explicit:
                raise ValueError("Invalid hugging face repo id") from error
            raise ValueError("Invalid hugging face repo id")
    sleep = MagicMock()
    with pytest.raises(setup.InsectsModelSetupError, match="ConnectionResetError: Connection reset by peer") as failure:
        setup.prepare_insects_model(tmp_path, attempts=2, download_model=download, sleep=sleep)
    assert isinstance(failure.value.__cause__, ValueError)
    assert "Connection reset by peer" in caplog.text
    assert "Invalid hugging face repo id" not in caplog.text
    sleep.assert_called_once_with(5.0)


def test_error_reason_handles_cycles():
    first, second = ValueError("first"), OSError("second")
    first.__cause__, second.__context__ = second, first
    assert setup.error_reason(first) == "OSError: second"


def test_preparation_validates_attempts(tmp_path):
    with pytest.raises(ValueError, match="attempts"):
        setup.prepare_insects_model(tmp_path, attempts=0)


def test_preparation_uses_complete_cache(tmp_path, monkeypatch):
    source = tmp_path / "cache"
    model_files(source)
    monkeypatch.setattr(setup, "CACHE_SEARCH_PATHS", [tmp_path / "missing", source])
    download = MagicMock()
    assert setup.prepare_insects_model(tmp_path / "target", download_model=download)
    download.assert_not_called()
    assert not setup.prepare_insects_model(tmp_path / "target", download_model=download)


def test_preparation_rejects_incomplete_download(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "CACHE_SEARCH_PATHS", [])
    with pytest.raises(setup.InsectsModelSetupError, match="file validation failed"):
        setup.prepare_insects_model(tmp_path, attempts=1, download_model=lambda _: None)


def test_main_uses_configured_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("INSECTS_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("INSECTS_MODEL_MODE", "disabled")
    assert setup.main() == 0
    monkeypatch.setenv("INSECTS_MODEL_MODE", "bad")
    assert setup.main() == 1


def test_cache_copy_preserves_existing_subdirectory(tmp_path, monkeypatch):
    source, target = tmp_path / "cache", tmp_path / "target"
    model_files(source)
    (target / "_best").mkdir(parents=True)
    monkeypatch.setattr(setup, "CACHE_SEARCH_PATHS", [source])
    assert not setup._copy_from_cache(target)


@pytest.mark.parametrize("same_directory", [False, True])
def test_download_copies_prepared_model(tmp_path, monkeypatch, same_directory):
    import sys
    source, target = tmp_path / "source", tmp_path / "target"
    model_files(source)
    hub = MagicMock()
    hub.create_model_path.return_value = str(source)
    factory = MagicMock(return_value=hub)
    monkeypatch.setitem(sys.modules, "autrainer.serving.model_paths", MagicMock(HubModelPath=factory))
    if same_directory:
        target = source
    setup._download_insects_model(target)
    assert setup.check_insects_files(target)
    factory.assert_called_once_with("hf:AlexanderGbd/insects-base-cnn10-96k-t", trust_remote=False)
    if not same_directory:
        setup._download_insects_model(target)


def test_main_reports_filesystem_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("INSECTS_MODEL_DIR", str(tmp_path))
    monkeypatch.setattr(setup, "prepare_image_model", MagicMock(side_effect=OSError("read-only directory")))
    assert setup.main() == 1
