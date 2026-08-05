"""Unit tests for AnalysisService."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from app.models import Annotation
from app.models.media import AudioSetting, Media
from app.models.taxon import Taxon
from app.services.analysis_service import AnalysisService


class TestAnalysisService:
    """Tests for AnalysisService."""

    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=Session)

    @pytest.fixture
    def service(self):
        return AnalysisService()

    def test_lazy_loading(self, service):
        """Analyzers are lazy-loaded on property access."""
        with patch("app.services.analysis_service.BirdNETAnalyzer") as mock_bird:
            _ = service.birdnet
            mock_bird.assert_called_once()
            
        with patch("app.services.analysis_service.BatDetect2Analyzer") as mock_bat:
            _ = service.batdetect
            mock_bat.assert_called_once()
            
        with patch("app.services.analysis_service.InsectAnalyzer") as mock_insect:
            _ = service.insects
            mock_insect.assert_called_once()

        with patch("app.services.analysis_service.AcousticIndexAnalyzer") as mock_index:
            _ = service.acoustic_index
            mock_index.assert_called_once()

    @patch("app.services.analysis_service.site_repository")
    def test_get_media_context_resolves_site_coordinates(self, mock_site_repo, service, mock_session):
        """Media context should include resolved site fallback coordinates."""
        media = Media(media_id=10, filename="test.wav", directory=1, audio_setting_id=7, site_id=3)
        media.audio_setting = AudioSetting(
            audio_setting_id=7,
            sampling_rate_hz=48000,
            duration_s=10,
            channel_num=2,
        )
        mock_site_repo.resolve_analysis_coordinates.return_value = (120.5, 30.2)

        context = service._get_media_context(mock_session, media)

        assert context["site_id"] == 3
        assert context["resolved_lon"] == 120.5
        assert context["resolved_lat"] == 30.2
        mock_site_repo.resolve_analysis_coordinates.assert_called_once_with(mock_session, 3)

    @patch("app.services.analysis_service.site_repository")
    def test_get_media_context_without_site_skips_coordinate_resolution(self, mock_site_repo, service, mock_session):
        """Media without site_id should not try to resolve fallback coordinates."""
        media = Media(media_id=10, filename="test.wav", directory=1, audio_setting_id=7, site_id=None)
        media.audio_setting = AudioSetting(
            audio_setting_id=7,
            sampling_rate_hz=48000,
            duration_s=10,
            channel_num=2,
        )

        context = service._get_media_context(mock_session, media)

        assert context["site_id"] is None
        assert context["resolved_lon"] is None
        assert context["resolved_lat"] is None
        mock_site_repo.resolve_analysis_coordinates.assert_not_called()

    @patch("app.services.analysis_service.resolve_existing_analysis_audio_media_path")
    def test_resolve_audio_path_prefers_database_filename(self, mock_resolve_existing, service, mock_session):
        """The stored filename is always the first lookup target."""
        media = Media(media_id=10, filename="clip.flac", directory=1, audio_setting_id=7)
        mock_session.exec.return_value.first.return_value = 12
        mock_resolve_existing.return_value = Path("/data/sounds/12/1/clip.flac")

        path = service._resolve_audio_path(mock_session, media, media.media_id)

        assert path == "/data/sounds/12/1/clip.flac"
        first_call = mock_resolve_existing.call_args_list[0]
        assert first_call.args[:3] == (12, 1, "clip.flac")

    @patch("app.services.analysis_service.resolve_existing_analysis_audio_media_path")
    def test_resolve_audio_path_uses_same_stem_wav_candidate(self, mock_resolve_existing, service, mock_session):
        """Non-WAV records can resolve to a same-stem WAV file."""
        media = Media(media_id=10, filename="clip.mp3", directory=1, audio_setting_id=7)
        mock_session.exec.return_value.first.return_value = 12
        mock_resolve_existing.side_effect = [Path("/data/sounds/12/1/clip.wav")]

        path = service._resolve_audio_path(mock_session, media, media.media_id)

        assert path == "/data/sounds/12/1/clip.wav"

    @patch("app.services.analysis_service.resolve_existing_analysis_audio_media_path")
    def test_resolve_audio_path_raises_when_no_supported_audio_exists(self, mock_resolve_existing, service, mock_session):
        """Analysis requires a resolvable WAV or FLAC file."""
        media = Media(media_id=10, filename="clip.mp3", directory=1, audio_setting_id=7)
        mock_session.exec.return_value.first.return_value = 12
        mock_resolve_existing.return_value = None

        with pytest.raises(FileNotFoundError, match="No supported analysis audio file found"):
            service._resolve_audio_path(mock_session, media, media.media_id)

    @patch("app.services.analysis_service.prepare_acoustic_selection", side_effect=lambda path, **_kwargs: path)
    @patch("app.services.analysis_service.index_log_repository")
    def test_analyze_and_store_acoustic_index(self, mock_log_repo, _mock_selection, service, mock_session):
        """Generic acoustic index storage should merge params and write logs."""
        service._acoustic_index = MagicMock()
        service._acoustic_index.run_index.return_value = {"ACI_sum": 123.45}
        service._acoustic_index.get_version.return_value = "1.0"
        media = Media(media_id=10, filename="test.wav", directory=1, audio_setting_id=7)
        media.audio_setting = AudioSetting(
            audio_setting_id=7,
            sampling_rate_hz=48000,
            duration_s=10,
            channel_num=2,
        )
        mock_session.get.return_value = media
        mock_log_repo.create_from_results.return_value = 1
        result = service.analyze_and_store_acoustic_index(
            session=mock_session,
            audio_path=Path("test.wav"),
            media_id=10,
            user_id=1,
            index_type_name="temporal_median",
            index_id=1,
            params={"Nt": 512},
            channel="right",
            min_time=1.25,
            max_time=8.5,
            min_frequency=200,
            max_frequency=8000,
            log_id=1234,
        )

        assert result["stored_count"] == 1
        assert result["ACI_sum"] == 123.45
        service._acoustic_index.run_index.assert_called_once()
        mock_log_repo.create_from_results.assert_called_once()
        kwargs = mock_log_repo.create_from_results.call_args.kwargs
        assert kwargs["output_first"] is False
        assert kwargs["min_time"] == "1.25"
        assert kwargs["max_time"] == "8.5"
        assert kwargs["min_frequency"] == "200"
        assert kwargs["max_frequency"] == "8000"
        assert kwargs["log_id"] == 1234
        assert kwargs["params"]["Channel"] == "Right"
        assert kwargs["params"]["Nt"] == 512

    @patch("app.services.analysis_service.prepare_acoustic_selection", side_effect=lambda path, **_kwargs: path)
    @patch("app.services.analysis_service.index_log_repository")
    def test_analyze_and_store_acoustic_index_forces_mono_for_single_channel(self, mock_log_repo, _mock_selection, service, mock_session):
        """Single-channel media should be analyzed and logged as mono even if a channel is requested."""
        service._acoustic_index = MagicMock()
        service._acoustic_index.run_index.return_value = {"med": 1.0}
        service._acoustic_index.get_version.return_value = "1.0"
        media = Media(media_id=10, filename="test.wav", directory=1, audio_setting_id=7)
        media.audio_setting = AudioSetting(
            audio_setting_id=7,
            sampling_rate_hz=48000,
            duration_s=10,
            channel_num=1,
        )
        mock_session.get.return_value = media
        mock_log_repo.create_from_results.return_value = 1

        service.analyze_and_store_acoustic_index(
            session=mock_session,
            audio_path=Path("test.wav"),
            media_id=10,
            user_id=1,
            index_type_name="temporal_median",
            index_id=1,
            params={"Nt": 512},
            channel="left",
        )

        assert service._acoustic_index.run_index.call_args.kwargs["channel"] == "mono"
        assert mock_log_repo.create_from_results.call_args.kwargs["params"]["Channel"] == "Mono"

    @patch("app.services.analysis_service.index_log_repository")
    def test_analyze_and_store_acoustic_index_requires_index_id(self, mock_log_repo, service, mock_session):
        with pytest.raises(ValueError, match="index_id is required"):
            service.analyze_and_store_acoustic_index(
                session=mock_session,
                audio_path=Path("test.wav"),
                media_id=10,
                user_id=1,
                index_type_name="max_frequency",
                index_id=None,
            )

        mock_log_repo.create_from_results.assert_not_called()

    @patch("app.services.analysis_service.prepare_acoustic_selection", side_effect=lambda path, **_kwargs: Path("selected.wav"))
    def test_analyze_max_frequency_restores_historical_result(self, mock_selection, service, mock_session):
        service._acoustic_index = MagicMock()
        service._acoustic_index.run_index.return_value = {"value": "609"}

        result = service.analyze_acoustic_selection(
            session=mock_session,
            audio_path=Path("source.wav"),
            media_id=10,
            user_id=1,
            analysis_type="max_frequency",
            params={"ignored": 1},
            channel="right",
            min_time=10,
            max_time=20,
            min_frequency=1000,
            max_frequency=8000,
            filter_enabled=True,
        )

        mock_selection.assert_called_once_with(
            Path("source.wav"),
            media_id=10,
            min_time=0,
            max_time=None,
            min_frequency=1000,
            max_frequency=8000,
            filter_enabled=True,
        )
        run_kwargs = service._acoustic_index.run_index.call_args.kwargs
        assert run_kwargs["index_name"] == "max_frequency"
        assert run_kwargs["params"] == {}
        assert run_kwargs["min_time"] == 10
        assert run_kwargs["max_time"] == 20
        assert result == {"stored_count": 1, "Frequency of maximum energy": "609"}

    def test_resolve_acoustic_index_channel_uses_bulk_defaults(self, service):
        """Missing API channel follows the bulk analysis channel setting."""
        assert service._resolve_acoustic_index_channel(1, None) == "mono"
        assert service._resolve_acoustic_index_channel(2, None) == "right"
        assert service._resolve_acoustic_index_channel(None, None) == "left"
        assert service._resolve_acoustic_index_channel(3, None) == "left"
        assert service._resolve_acoustic_index_channel(2, "left") == "left"
        assert service._resolve_acoustic_index_channel(1, "right") == "mono"

    def test_build_index_params_merges_defaults(self, service):
        """Concrete defaults should be merged with explicit overrides."""
        raw_param = [
            {"key": "mode", "default": "fast", "value_type": "string"},
            {"key": "Nt", "default": 512, "value_type": "number"},
            {"key": "rejectDuration", "default": None, "value_type": "string"},
        ]

        merged = service.build_index_params(raw_param, {"Nt": 1024, "display": False})

        assert merged == {
            "mode": "fast",
            "Nt": 1024,
            "display": False,
        }

    def test_build_index_params_skips_null_defaults(self, service):
        """Null metadata defaults should not override analyzer defaults."""
        raw_param = [
            {"key": "mode", "default": "dB", "value_type": "string"},
            {"key": "min_peak_val", "default": None, "value_type": "string"},
            {"key": "min_freq_dist", "default": 200, "value_type": "number"},
            {"key": "prominence", "default": None, "value_type": "string"},
        ]

        merged = service.build_index_params(raw_param, {})

        assert merged == {
            "mode": "dB",
            "min_freq_dist": 200,
        }

    def test_analyze_and_store_birdnet(self, service, mock_session):
        """analyze_and_store_birdnet creates annotations for detections."""
        service._birdnet = MagicMock()
        service._birdnet.version = "2.4"
        service._birdnet.analyze.return_value = [
            {"species": "S1", "confidence": 0.9, "start_time": 0, "end_time": 3},
            {"species": "S2", "confidence": 0.8, "start_time": 3, "end_time": 6},
        ]

        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            mock_taxon = MagicMock(taxon_id=50)
            unknown_taxon = MagicMock(taxon_id=999)

            def find_local(_session, scientific_name):
                if scientific_name == "Unknown":
                    return unknown_taxon
                if scientific_name == "S1":
                    return mock_taxon
                return None

            mock_find_local_taxon.side_effect = find_local
            created_a = MagicMock(annotation_id=101)
            created_b = MagicMock(annotation_id=102)
            mock_repo.create_batch.return_value = [created_a, created_b]

            result = service.analyze_and_store_birdnet(
                session=mock_session,
                audio_path=Path("test.wav"),
                media_id=10,
                creator_id=1,
                min_frequency=1,
                max_frequency=12000,
            )

            assert result["detection_count"] == 2
            assert result["annotation_count"] == 2

            mock_repo.create_batch.assert_called_once()
            annotations = mock_repo.create_batch.call_args[0][1]
            assert len(annotations) == 2
            assert annotations[0].taxon_id == 50
            assert annotations[1].taxon_id == 999
            assert annotations[0].comments == ""
            assert annotations[1].comments == "S2"
            assert annotations[0].min_y == 1
            assert annotations[1].min_y == 1
            assert annotations[0].max_y == 12000
            assert annotations[1].max_y == 12000
            assert result["annotation_ids"] == [101, 102]
            assert result["unmatched_species"] == ["S2"]
            assert result["unmatched_species_count"] == 1
            assert result["analysis_message_model"] == "BirdNET v2.4"
            service._birdnet.analyze.assert_called_once_with(
                Path("test.wav"),
                min_confidence=0.1,
                overlap=0.0,
                sensitivity=1.0,
                sf_thresh=0.03,
                lat=None,
                lon=None,
                week=None,
                locale="en_us",
                top_n=None,
                cancellation_token=None,
            )

    def test_analyze_and_store_birdnet_keeps_scientific_name_when_taxon_is_unknown(self, service, mock_session):
        """Unknown fallback should preserve the scientific name in comments and unmatched_species."""
        service._birdnet = MagicMock()
        service._birdnet.version = "2.4"
        service._birdnet.analyze.return_value = [
            {"species": "Phylloscopus sibilatrix", "confidence": 0.9, "start_time": 12, "end_time": 15, "max_freq": 15000},
        ]

        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.create_batch.return_value = [MagicMock()]

            result = service.analyze_and_store_birdnet(
                session=mock_session,
                audio_path=Path("test.wav"),
                media_id=10,
                creator_id=1,
            )

            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == "Phylloscopus sibilatrix"
            assert result["unmatched_species"] == ["Phylloscopus sibilatrix"]

    def test_analyze_and_store_birdnet_uses_local_taxa_only(self, service, mock_session):
        """BirdNET should not bridge missing taxa from the remote XR table."""
        service._birdnet = MagicMock()
        service._birdnet.version = "2.4"
        service._birdnet.analyze.return_value = [
            {"species": "Dryocopus martius", "confidence": 0.5, "start_time": 0, "end_time": 3},
        ]

        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            remote_taxon = MagicMock(taxon_id=1234)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.find_taxon.return_value = remote_taxon
            mock_repo.create_batch.return_value = [MagicMock()]

            result = service.analyze_and_store_birdnet(
                session=mock_session,
                audio_path=Path("test.wav"),
                media_id=10,
                creator_id=1,
            )

            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == "Dryocopus martius"
            assert result["unmatched_species"] == ["Dryocopus martius"]
            mock_repo.find_taxon.assert_not_called()

    def test_find_local_taxon_matches_scientific_name_case_insensitively(self, service, db):
        """BirdNET taxon lookup should tolerate casing differences in local scientific names."""
        taxon = Taxon(cached_scientific_name="Accipiter gentilis", cached_common_name="Northern Goshawk")
        db.add(taxon)
        db.commit()
        db.refresh(taxon)

        found = service._find_local_taxon(db, " accipiter   GENTILIS ")

        assert found is not None
        assert found.taxon_id == taxon.taxon_id

    def test_analyze_and_store_birdnet_no_detections(self, service, mock_session):
        """analyze_and_store_birdnet returns empty if no detections."""
        service._birdnet = MagicMock()
        service._birdnet.version = "2.4"
        service._birdnet.analyze.return_value = []
        result = service.analyze_and_store_birdnet(mock_session, Path("test.wav"), 10, 1)
        assert result["detection_count"] == 0
        assert result["unmatched_species_count"] == 0
        assert result["analysis_message_model"] == "BirdNET v2.4"

    def test_analyze_and_store_batdetect(self, service, mock_session):
        """analyze_and_store_batdetect creates annotations for detections."""
        service._batdetect = MagicMock()
        service._batdetect.version = "0.1.2"
        service._batdetect.analyze.return_value = [
            {"species": "Bat1", "confidence": 0.95, "start_time": 1, "end_time": 2}
        ]
        
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            def find_local(_session, scientific_name):
                if scientific_name == "Bat1":
                    return MagicMock(taxon_id=60)
                if scientific_name == "Unknown":
                    return MagicMock(taxon_id=999)
                return None

            mock_find_local_taxon.side_effect = find_local
            mock_repo.create_batch.return_value = [MagicMock()]
            
            result = service.analyze_and_store_batdetect(
                session=mock_session,
                audio_path=Path("test.wav"),
                media_id=10,
                creator_id=1,
            )
            
            assert result["detection_count"] == 1
            assert result["annotation_count"] == 1
            assert result["unmatched_species_count"] == 0
            assert result["analysis_message_model"] == "Batdetect2 0.1.2"
            mock_repo.create_batch.assert_called_once()
            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].comments == ""
            service._batdetect.analyze.assert_called_once_with(
                Path("test.wav"),
                detection_threshold=0.3,
                chunk_size=2.0,
                cancellation_token=None,
            )

    def test_analyze_and_store_batdetect_no_detections(self, service, mock_session):
        """analyze_and_store_batdetect handles no detections."""
        service._batdetect = MagicMock()
        service._batdetect.version = "1.0"
        service._batdetect.analyze.return_value = []
        result = service.analyze_and_store_batdetect(mock_session, Path("test.wav"), 10, 1)
        assert result["detection_count"] == 0

    def test_analyze_and_store_batdetect_no_taxon(self, service, mock_session):
        """analyze_and_store_batdetect handles missing taxon."""
        service._batdetect = MagicMock()
        service._batdetect.version = "1.0"
        service._batdetect.analyze.return_value = [{"species": "Unknown"}]
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.create_batch.return_value = [MagicMock()]
            
            result = service.analyze_and_store_batdetect(mock_session, Path("test.wav"), 10, 1)
            assert result["detection_count"] == 1
            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == ""

    def test_analyze_and_store_batdetect_uses_local_taxa_only(self, service, mock_session):
        """batdetect2 should not bridge missing taxa from the remote XR table."""
        service._batdetect = MagicMock()
        service._batdetect.version = "1.0"
        service._batdetect.analyze.return_value = [{"species": "BatX", "start_time": 1, "end_time": 2}]
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.find_taxon.return_value = MagicMock(taxon_id=123)
            mock_repo.create_batch.return_value = [MagicMock()]

            result = service.analyze_and_store_batdetect(mock_session, Path("test.wav"), 10, 1)

            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == "BatX"
            assert result["unmatched_species"] == ["BatX"]
            assert result["unmatched_species_count"] == 1
            mock_repo.find_taxon.assert_not_called()

    def test_analyze_and_store_insects(self, service, mock_session):
        """analyze_and_store_insects creates annotations."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = [{"species": "Insect1", "confidence": 0.7, "start_time": 1, "end_time": 2}]
        
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            def find_local(_session, scientific_name):
                if scientific_name == "Insect1":
                    return MagicMock(taxon_id=70)
                if scientific_name == "Unknown":
                    return MagicMock(taxon_id=999)
                return None

            mock_find_local_taxon.side_effect = find_local
            mock_repo.create_batch.return_value = [MagicMock()]
            
            result = service.analyze_and_store_insects(mock_session, Path("test.wav"), 10, 1)
            assert result["detection_count"] == 1
            assert result["unmatched_species_count"] == 0
            assert result["analysis_message_model"] == "insects-base-cnn10-96k-t"
            annotations = mock_repo.create_batch.call_args[0][1]
            # max_y should use the passed max_freq (default 48000 in direct service call)
            assert annotations[0].max_y == 48000
            # min_y is always 1
            assert annotations[0].min_y == 1
            assert annotations[0].comments == ""

    def test_analyze_and_store_insects_no_detections(self, service, mock_session):
        """analyze_and_store_insects handles no detections."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = []
        result = service.analyze_and_store_insects(mock_session, Path("test.wav"), 10, 1)
        assert result["detection_count"] == 0

    def test_analyze_and_store_insects_no_taxon(self, service, mock_session):
        """analyze_and_store_insects handles missing taxon."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = [{"species": "Unknown", "start_time": 1, "end_time": 2}]
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.create_batch.return_value = [MagicMock()]
            
            result = service.analyze_and_store_insects(mock_session, Path("test.wav"), 10, 1)
            assert result["detection_count"] == 1
            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == ""

    def test_analyze_and_store_insects_custom_max_freq(self, service, mock_session):
        """analyze_and_store_insects uses the provided max_freq for annotation bbox."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = [{"species": "Insect2", "confidence": 0.6, "start_time": 1, "end_time": 2}]

        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            def find_local(_session, scientific_name):
                if scientific_name == "Insect2":
                    return MagicMock(taxon_id=71)
                if scientific_name == "Unknown":
                    return MagicMock(taxon_id=999)
                return None

            mock_find_local_taxon.side_effect = find_local
            mock_repo.create_batch.return_value = [MagicMock()]

            service.analyze_and_store_insects(mock_session, Path("test.wav"), 10, 1, max_freq=22050)
            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].max_y == 22050

    def test_analyze_and_store_insects_uses_local_taxa_only(self, service, mock_session):
        """Insects should not bridge missing taxa from the remote XR table."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = [{"species": "InsectX", "start_time": 1, "end_time": 2}]
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            mock_find_local_taxon.side_effect = lambda _session, scientific_name: unknown_taxon if scientific_name == "Unknown" else None
            mock_repo.find_taxon.return_value = MagicMock(taxon_id=123)
            mock_repo.create_batch.return_value = [MagicMock()]

            result = service.analyze_and_store_insects(mock_session, Path("test.wav"), 10, 1)

            annotations = mock_repo.create_batch.call_args[0][1]
            assert annotations[0].taxon_id == 999
            assert annotations[0].comments == "InsectX"
            assert result["unmatched_species"] == ["InsectX"]
            assert result["unmatched_species_count"] == 1
            mock_repo.find_taxon.assert_not_called()

    def test_analyze_and_store_insects_warns_for_invalid_time_bounds(self, service, mock_session):
        """Invalid insect detections are skipped and reported as a warning."""
        service._insects = MagicMock()
        service._insects.version = "1.0"
        service._insects.analyze.return_value = [
            {"species": "Insect1", "confidence": 0.7, "start_time": 1, "end_time": 2},
            {"species": "Insect1", "confidence": 0.7, "start_time": 9, "end_time": 12},
        ]

        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            def find_local(_session, scientific_name):
                if scientific_name == "Insect1":
                    return MagicMock(taxon_id=70)
                if scientific_name == "Unknown":
                    return MagicMock(taxon_id=999)
                return None

            mock_find_local_taxon.side_effect = find_local
            mock_repo.create_batch.return_value = [MagicMock(annotation_id=101)]

            result = service.analyze_and_store_insects(
                mock_session,
                Path("test.wav"),
                10,
                1,
                recording_duration=10,
            )

            assert result["detection_count"] == 2
            assert result["annotation_count"] == 1
            assert result["warning"] == (
                "1 detections were skipped because their time bounds were outside the audio duration."
            )

    def test_merge_annotations_confidence_is_mean_with_existing_comments(self, service, mock_session):
        """Merged confidence uses arithmetic mean; original comments are preserved."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo:
            ann_a = MagicMock(spec=Annotation, annotation_id=1, taxon_id=5, min_x=0, max_x=2, min_y=1, max_y=10000, confidence=0.6, creator_id=1, creator_type="BirdNET-Analyzer 2.4", sound_id=6, media_id=1, comments="Some species")
            ann_b = MagicMock(spec=Annotation, annotation_id=2, taxon_id=5, min_x=1, max_x=3, min_y=1, max_y=10000, confidence=0.8, creator_id=1, creator_type="BirdNET-Analyzer 2.4", sound_id=6, media_id=1, comments="Some species")
            mock_repo.find_taxon.return_value = MagicMock(taxon_id=999)
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b]

            service.merge_annotations(mock_session, 1, "BirdNET-Analyzer 2.4", max_gap=5.0, annotation_ids=[1, 2])

            merged_anns = mock_repo.create_batch.call_args[0][1]
            assert len(merged_anns) == 1
            assert merged_anns[0].confidence == pytest.approx(0.7, abs=1e-4)
            # original comment preserved and merge info appended
            assert "Some species" in merged_anns[0].comments
            assert "merged 2 BirdNET tags" in merged_anns[0].comments

    def test_merge_annotations(self, service, mock_session):
        """merge_annotations merges close annotations of same taxon."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo:
            # Taxon 1: Ann A (0-3s), Ann B (2-5s) -> Merge
            # Taxon 1: Ann C (10-13s) -> Stay isolated
            # Taxon 2: Ann D (0-4s) -> Stay isolated
            
            ann_a = MagicMock(spec=Annotation, annotation_id=1, taxon_id=1, min_x=0, max_x=3, min_y=100, max_y=500, confidence=0.8, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments=None)
            ann_b = MagicMock(spec=Annotation, annotation_id=2, taxon_id=1, min_x=2, max_x=5, min_y=150, max_y=550, confidence=0.9, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments=None)
            ann_c = MagicMock(spec=Annotation, annotation_id=3, taxon_id=1, min_x=10, max_x=13, min_y=100, max_y=500, confidence=0.7, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments=None)
            ann_d = MagicMock(spec=Annotation, annotation_id=4, taxon_id=2, min_x=0, max_x=4, min_y=200, max_y=600, confidence=0.6, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments=None)
            
            mock_repo.find_taxon.return_value = MagicMock(taxon_id=999)
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b, ann_c, ann_d]
            
            count = service.merge_annotations(mock_session, 10, "T1", max_gap=1.0, annotation_ids=[1, 2, 3, 4])
            
            assert count == 1  # one merged group for Taxon 1
            mock_repo.create_batch.assert_called_once()
            merged_anns = mock_repo.create_batch.call_args[0][1]
            assert len(merged_anns) == 1
            assert merged_anns[0].min_x == 0
            assert merged_anns[0].max_x == 5
            # confidence must be arithmetic mean of 0.8 and 0.9
            assert merged_anns[0].confidence == pytest.approx(0.85, abs=1e-4)
            # comments must include merge info with confidence scores
            assert "merged 2 T1 tags" in merged_anns[0].comments
            assert "0.8" in merged_anns[0].comments
            assert "0.9" in merged_anns[0].comments
            
            mock_repo.delete_by_ids.assert_not_called()

    def test_merge_annotations_keep_merged_only_keeps_isolated_rows_unchanged(self, service, mock_session):
        """keep_merged_only rewrites the full creator batch, including isolated rows."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo:
            ann_a = Annotation(
                annotation_id=1,
                media_id=10,
                creator_id=1,
                sound_id=6,
                taxon_id=1,
                min_x=0,
                max_x=3,
                min_y=1,
                max_y=10,
                reference=False,
                uncertain=True,
                sound_distance_m=42,
                animal_sound_type="call",
            )
            ann_b = Annotation(
                annotation_id=2,
                media_id=10,
                creator_id=1,
                sound_id=6,
                taxon_id=1,
                min_x=10,
                max_x=13,
                min_y=1,
                max_y=10,
                reference=False,
                uncertain=False,
                sound_distance_m=84,
                animal_sound_type="song",
            )
            mock_repo.find_taxon.return_value = MagicMock(taxon_id=999)
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b]
            
            service.merge_annotations(mock_session, 10, "T1", max_gap=0, keep_merged_only=True, annotation_ids=[1, 2])
            
            mock_repo.delete_by_ids.assert_called_once_with(
                mock_session,
                [1, 2],
                commit=True,
            )
            mock_repo.create_batch.assert_called_once()
            recreated = mock_repo.create_batch.call_args[0][1]
            assert len(recreated) == 2
            assert recreated[0].taxon_id == 1
            assert recreated[1].taxon_id == 1
            assert recreated[0].uncertain is True
            assert recreated[0].sound_distance_m == 42
            assert recreated[0].animal_sound_type == "call"
            assert recreated[1].uncertain is False
            assert recreated[1].sound_distance_m == 84
            assert recreated[1].animal_sound_type == "song"

    def test_merge_annotations_keep_all_preserves_originals_and_adds_merge(self, service, mock_session):
        """keep_merged_only=False keeps originals and appends merged rows."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon", return_value=MagicMock(taxon_id=999)):
            ann_a = Annotation(annotation_id=1, media_id=10, creator_id=1, sound_id=6, taxon_id=1, min_x=0, max_x=2, min_y=1, max_y=10, confidence=0.5, reference=False)
            ann_b = Annotation(annotation_id=2, media_id=10, creator_id=1, sound_id=6, taxon_id=1, min_x=2, max_x=4, min_y=1, max_y=10, confidence=0.7, reference=False)
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b]

            count = service.merge_annotations(mock_session, 10, "BirdNET-Analyzer 2.4", max_gap=0.5, keep_merged_only=False, annotation_ids=[1, 2])

            assert count == 1
            mock_repo.delete_by_ids.assert_not_called()
            mock_repo.create_batch.assert_called_once()
            merged = mock_repo.create_batch.call_args[0][1]
            assert len(merged) == 1
            assert "merged 2 BirdNET tags" in merged[0].comments

    def test_merge_annotations_groups_unknown_by_comment(self, service, mock_session):
        """Unknown taxon rows only merge when their comments match."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            ann_a = MagicMock(spec=Annotation, annotation_id=1, taxon_id=999, min_x=0, max_x=2, min_y=1, max_y=10, confidence=0.5, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments="Species A")
            ann_b = MagicMock(spec=Annotation, annotation_id=2, taxon_id=999, min_x=2, max_x=4, min_y=2, max_y=11, confidence=0.7, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments="Species A")
            ann_c = MagicMock(spec=Annotation, annotation_id=3, taxon_id=999, min_x=2, max_x=4, min_y=2, max_y=11, confidence=0.9, creator_id=1, creator_type="T1", sound_id=1, media_id=10, comments="Species B")
            mock_find_local_taxon.return_value = unknown_taxon
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b, ann_c]

            count = service.merge_annotations(mock_session, 10, "T1", max_gap=0.5, annotation_ids=[1, 2, 3])

            assert count == 1
            merged_anns = mock_repo.create_batch.call_args[0][1]
            assert len(merged_anns) == 1
            assert merged_anns[0].comments.startswith("Species A")

    def test_merge_annotations_does_not_merge_unknown_rows_with_different_comments(self, service, mock_session):
        """Unknown comment text remains part of the merge key."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon") as mock_find_local_taxon:
            unknown_taxon = MagicMock(taxon_id=999)
            ann_a = Annotation(annotation_id=1, media_id=10, creator_id=1, sound_id=6, taxon_id=999, min_x=0, max_x=2, min_y=1, max_y=10, confidence=0.5, reference=False, comments="Species A")
            ann_b = Annotation(annotation_id=2, media_id=10, creator_id=1, sound_id=6, taxon_id=999, min_x=2, max_x=4, min_y=1, max_y=10, confidence=0.7, reference=False, comments="Species B")
            mock_find_local_taxon.return_value = unknown_taxon
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b]

            count = service.merge_annotations(mock_session, 10, "BirdNET-Analyzer 2.4", max_gap=0.5, annotation_ids=[1, 2])

            assert count == 0
            mock_repo.create_batch.assert_not_called()

    def test_merge_annotations_truncates_comments_to_annotation_limit(self, service, mock_session):
        """Merged comments must fit the current annotation.comments column size."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo, \
             patch.object(service, "_find_local_taxon", return_value=MagicMock(taxon_id=999)):
            long_comment = "Species A " + ("x" * 480)
            ann_a = Annotation(annotation_id=1, media_id=10, creator_id=1, sound_id=6, taxon_id=1, min_x=0, max_x=2, min_y=1, max_y=10, confidence=0.5, reference=False, comments=long_comment)
            ann_b = Annotation(annotation_id=2, media_id=10, creator_id=1, sound_id=6, taxon_id=1, min_x=2, max_x=4, min_y=1, max_y=10, confidence=0.7, reference=False, comments=long_comment)
            mock_session.exec.return_value.all.return_value = [ann_a, ann_b]

            service.merge_annotations(mock_session, 10, "BirdNET-Analyzer 2.4", max_gap=0.5, annotation_ids=[1, 2])

            merged = mock_repo.create_batch.call_args[0][1]
            assert len(merged[0].comments) == 500

    def test_merge_annotations_no_data(self, service, mock_session):
        """merge_annotations returns 0 if no annotations found."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo:
            mock_repo.get_by_media_and_creator_type.return_value = []
            assert service.merge_annotations(mock_session, 10, "T1", annotation_ids=[]) == 0

    def test_merge_annotations_only_uses_current_batch_ids(self, service, mock_session):
        """Repeat runs should merge only the current batch, not historical annotations."""
        with patch("app.services.analysis_service.annotation_repository") as mock_repo:
            current_a = Annotation(
                annotation_id=2,
                media_id=10,
                creator_id=1,
                sound_id=6,
                taxon_id=1,
                min_x=10,
                max_x=12,
                min_y=1,
                max_y=10,
                confidence=0.5,
                reference=False,
            )
            current_b = Annotation(
                annotation_id=3,
                media_id=10,
                creator_id=1,
                sound_id=6,
                taxon_id=1,
                min_x=12,
                max_x=14,
                min_y=1,
                max_y=10,
                confidence=0.7,
                reference=False,
            )
            mock_session.exec.return_value.all.return_value = [current_a, current_b]

            count = service.merge_annotations(
                mock_session,
                10,
                "BirdNET-Analyzer 2.4",
                max_gap=0.5,
                annotation_ids=[2, 3],
            )

            assert count == 1
            mock_repo.create_batch.assert_called_once()
            merged = mock_repo.create_batch.call_args[0][1]
            assert len(merged) == 1
            assert merged[0].min_x == 10
            assert merged[0].max_x == 14
            mock_repo.get_by_media_and_creator_type.assert_not_called()
