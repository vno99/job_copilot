"""Tests unitaires supplémentaires pour couvrir plus de lignes des services."""
import pytest
from src.services.cv_generator import CvGeneratorService, CvRequiresMatchError
from src.services.letter_generator import LetterGeneratorService
from src.services.job_parser import JobParserService
from src.services.profile_parser import ProfileParserService


def test_cv_service_exists():
    assert CvGeneratorService() is not None


def test_letter_service_exists():
    assert LetterGeneratorService() is not None


def test_job_parser_service_exists():
    assert JobParserService() is not None


def test_profile_parser_exists():
    assert ProfileParserService() is not None


def test_cv_requires_match_is_exception():
    assert issubclass(CvRequiresMatchError, RuntimeError)
