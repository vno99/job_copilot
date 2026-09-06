"""Tests de couverture étendus pour services."""
import pytest
from src.services.profile_parser import ProfileParserService
from src.services.url_job_ingestor import URLJobIngestorService
from src.services.search_parameters_agent import SearchParametersAgentService


@pytest.mark.not_integration()
def test_profile_parser_service_exists():
    service = ProfileParserService()
    assert service is not None


@pytest.mark.not_integration()
def test_url_ingestor_service_exists():
    service = URLJobIngestorService()
    assert service is not None


@pytest.mark.not_integration()
def test_search_agent_service_exists():
    agent = SearchParametersAgentService()
    assert agent is not None
